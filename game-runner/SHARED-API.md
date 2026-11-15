# Shared implementation API (internal)

Read `src/model.rs` for exact structs. Root owns model.rs, transport.rs, context.rs, adapters/mod.rs, engine.rs, main.rs, Cargo files. Implementers own only assigned files. No live game calls. Use Cargo via `/home/agent/.cargo/bin/cargo`; root handles lib.rs module wiring. No commits by concurrent implementers; coordinator commits integrated changes.

## Store owner

Implement `pub struct Store` (Clone, Send + Sync; retain PathBuf, open SQLite per operation), `pub struct ProviderGuard` holding an OS file lock, and these methods in store.rs:

```
pub fn open(root: impl AsRef<Path>) -> Result<Self>;
pub fn root(&self) -> &Path;
pub fn install_inventory(&self, snapshot: &InventorySnapshot) -> Result<()>;
pub fn inventory(&self, id: Option<&str>) -> Result<InventorySnapshot>; // None = latest
pub fn create_campaign(&self, plan: &CampaignPlan) -> Result<()>; // idempotent same exact plan, reject changed same id
pub fn campaign(&self, id: &str) -> Result<CampaignPlan>;
pub fn acquire_provider(&self, provider: &str) -> Result<ProviderGuard>; // fs2 try_lock_exclusive, canonical alias, no TTL
pub fn create_round(&self, spec: &RoundSpec) -> Result<RoundRecord>; // existing same campaign/job/sample returns unchanged; other active same canonical provider blocks transactionally
pub fn save_session(&self, round_id: &str, owner: &Value) -> Result<()>; // immutable identity: equal repeat OK, different owner forbidden
pub fn session(&self, round_id: &str) -> Result<Option<Value>>;
pub fn start_exchange(&self, round_id: &str, request: &WireRequest) -> Result<u64>; // commit before send; financial requires session; no other unresolved exchange
pub fn finish_exchange(&self, round_id: &str, ordinal: u64, response: &WireResponse) -> Result<()>; // append-only response, no replacement
pub fn fail_exchange(&self, round_id: &str, ordinal: u64, reason: &str) -> Result<()>; // financial => uncertain, persist error
pub fn mark_error(&self, round_id: &str, reason: &str) -> Result<()>; // any prior financial dispatch => uncertain, else blocked
pub fn complete(&self, round_id: &str, outcome: &RoundOutcome) -> Result<RoundRecord>; // recompute checks; false closed=>validation_failed; unclosed=>uncertain
pub fn round(&self, id: &str) -> Result<RoundRecord>;
pub fn rounds(&self) -> Result<Vec<RoundRecord>>;
pub fn exchanges(&self, round_id: &str) -> Result<Vec<ExchangeRecord>>;
pub fn pending_provider(&self, provider: &str) -> Result<Option<RoundRecord>>;
```

Use WAL, FULL, foreign keys, busy timeout. Preserve evidence on every error. Provider lock cannot be replaced/deleted. Restrictive private root permissions on Unix. DB schema constraints and transactions enforce state and uniqueness. Tests must include separate Store handles/process locking, alias, uncertain block, exact owner and append-only responses.

Inventory owner also implements `inventory::load_manifest(path: &Path) -> Result<InventorySnapshot>`. Parse published JSON index `[{id,path,games,modes,sha256, ...}]`; load each provider, validate counts/unique IDs/key; require hash exact or CRLF historical and annotate source. Canonical semantic hash snapshot.id independent of EOL. Reject outside-path traversal, altered data, duplicate provider IDs. Do not modify published JSON.

## Adapter owners

Each module implements `pub async fn execute(ctx: &RunContext, game: &Game, mode: &Mode, settings: &Value) -> Result<RoundOutcome>` in its file. You may add pure parsing/auditing helpers and tests in that file. The coordinator's `context` exposes:

```
pub async fn http(&self, label:&str, method:&str, url:&str, headers:BTreeMap<String,String>, body:String, financial:bool) -> Result<WireResponse>;
pub async fn get(&self,label:&str,url:&str) -> Result<WireResponse>;
pub async fn json(&self,label:&str,url:&str,body:&Value,headers:BTreeMap<String,String>,financial:bool)->Result<Value>;
pub fn save_session(&self, owner:&Value)->Result<()>;
pub async fn websocket(&self,url:&str,origin:&str,subprotocol:Option<&str>,headers:BTreeMap<String,String>)->Result<NativeSocket>;
pub async fn ws_json(&self, socket:&mut NativeSocket,label:&str,request:&Value,financial:bool, request_id:Option<&str>)->Result<Value>;
pub fn max_steps(&self)->usize;
```

`NativeSocket` can only be used through journalled context (no direct sends). `ws_json` correlates requestId or id string if request_id provided and returns the matching full JSON document; records all received messages. Context uses one cookie jar for its HTTP and WS handshake. HTTP no automatic redirects/retries; adapter follows only validated redirects explicitly. `json` requires HTTP2xx, stores response before parsing; field/provider status checks remain adapter's job. URLs must use a fixed per-provider host allowlist (root enforces). Only fresh DEMO bootstrap, verify initial/final currency, native ids, published prices. Call save_session with verified fresh session before financial operation. Keep same roundId through continuations. Use strings/Decimal for native money, no f64 arithmetic. Unexpected state => Err => engine holds existing root; never guesses choices or prices. No stdout from adapters. Native response payloads go in outcome.native_data (private default; engine sanitizer handles export).

Settings may hold nonsecret launch config, e.g. `launch_url`, `wallet` for Peter, `binding` for Playson; never captured credentials. If a needed documented input is missing, fail before financial dispatch with precise error. First supported mode comes from explicit inventory mapping and must be revalidated against fresh native offer. Mode classification must stay accurate. Conditional parent-dependent modes are not independent paid starts.
