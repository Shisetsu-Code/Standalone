use crate::model::*;
use anyhow::{Context, Result, bail, ensure};
use fs2::FileExt;
use rusqlite::{Connection, OptionalExtension, TransactionBehavior, params};
use serde::{Serialize, de::DeserializeOwned};
use serde_json::Value;
use std::{
    fs::{self, File, OpenOptions},
    path::{Path, PathBuf},
    time::Duration,
};
use uuid::Uuid;

#[derive(Clone)]
pub struct Store {
    root: PathBuf,
}
pub struct ProviderGuard {
    _file: File,
}
fn json<T: Serialize>(v: &T) -> Result<String> {
    Ok(serde_json::to_string(v)?)
}
fn decode<T: DeserializeOwned>(s: String) -> Result<T> {
    Ok(serde_json::from_str(&s)?)
}
fn valid_id(id: &str) -> Result<()> {
    ensure!(
        !id.is_empty()
            && id
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-'),
        "invalid provider identifier"
    );
    Ok(())
}
impl Store {
    pub fn open(root: impl AsRef<Path>) -> Result<Self> {
        fs::create_dir_all(root.as_ref())?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(root.as_ref(), fs::Permissions::from_mode(0o700))?;
        }
        let root = root.as_ref().canonicalize()?;
        let this = Self { root };
        let conn = this.conn()?;
        conn.execute_batch("CREATE TABLE IF NOT EXISTS provider_holds(provider TEXT PRIMARY KEY, reason TEXT NOT NULL, created INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS inventories(id TEXT PRIMARY KEY, data TEXT NOT NULL, created INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS inventory_selection(singleton INTEGER PRIMARY KEY CHECK(singleton=1), inventory_id TEXT NOT NULL REFERENCES inventories(id));
          CREATE TABLE IF NOT EXISTS campaigns(id TEXT PRIMARY KEY, inventory_id TEXT NOT NULL REFERENCES inventories(id), data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS rounds(id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id), job INTEGER NOT NULL, sample INTEGER NOT NULL, provider TEXT NOT NULL, spec TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('prepared','in_flight','open','verified','validation_failed','uncertain','blocked')), created INTEGER NOT NULL, updated INTEGER NOT NULL, reason TEXT, outcome TEXT, owner TEXT, UNIQUE(campaign_id,job,sample));
          CREATE UNIQUE INDEX IF NOT EXISTS one_active_provider ON rounds(provider) WHERE status IN ('prepared','in_flight','open','uncertain');
          CREATE TABLE IF NOT EXISTS exchanges(round_id TEXT NOT NULL REFERENCES rounds(id), ordinal INTEGER NOT NULL, request TEXT NOT NULL, request_hash TEXT NOT NULL, financial INTEGER NOT NULL CHECK(financial IN(0,1)), response TEXT, response_hash TEXT, error TEXT, PRIMARY KEY(round_id,ordinal), CHECK(response IS NULL OR error IS NULL));
          CREATE TABLE IF NOT EXISTS received_frames(round_id TEXT NOT NULL, ordinal INTEGER NOT NULL, sequence INTEGER NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL, recorded INTEGER NOT NULL, PRIMARY KEY(round_id,ordinal,sequence), FOREIGN KEY(round_id,ordinal) REFERENCES exchanges(round_id,ordinal));
          CREATE TABLE IF NOT EXISTS bootstrap_retries(round_id TEXT PRIMARY KEY REFERENCES rounds(id), rejected_ordinal INTEGER NOT NULL, owner TEXT, recorded INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS provider_schedule(provider TEXT PRIMARY KEY, next_start INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS operator_actions(id INTEGER PRIMARY KEY, provider TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL, recorded INTEGER NOT NULL);")?;
        Ok(this)
    }
    fn conn(&self) -> Result<Connection> {
        let c = Connection::open(self.root.join("runner.sqlite3"))?;
        c.busy_timeout(Duration::from_secs(10))?;
        c.execute_batch(
            "PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA foreign_keys=ON;",
        )?;
        Ok(c)
    }
    pub fn root(&self) -> &Path {
        &self.root
    }
    /// Reserve a start while holding the canonical provider lock. The deadline
    /// survives a restart and uses the existing suite's minimum interval.
    pub fn reserve_provider_start(&self, provider: &str, seconds: u64) -> Result<Duration> {
        let provider = canonical_provider(provider);
        valid_id(provider)?;
        ensure!(seconds <= 3600, "invalid provider interval");
        if seconds == 0 {
            return Ok(Duration::ZERO);
        }
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let previous: Option<i64> = tx
            .query_row(
                "SELECT next_start FROM provider_schedule WHERE provider=?1",
                [provider],
                |r| r.get(0),
            )
            .optional()?;
        let now = now_ms();
        let start = previous
            .map(u64::try_from)
            .transpose()?
            .unwrap_or(now)
            .max(now);
        tx.execute("INSERT INTO provider_schedule(provider,next_start) VALUES (?1,?2) ON CONFLICT(provider) DO UPDATE SET next_start=excluded.next_start", params![provider,i64::try_from(start + seconds * 1000)?])?;
        tx.commit()?;
        Ok(Duration::from_millis(start - now))
    }
    pub fn bootstrap_attempts(&self, id: &str) -> Result<Vec<Value>> {
        read_bootstrap_attempts(&self.conn()?, id)
    }
    pub fn hold_provider(&self, provider: &str, reason: &str) -> Result<()> {
        let provider = canonical_provider(provider);
        valid_id(provider)?;
        ensure!(!reason.trim().is_empty(), "hold reason missing");
        self.conn()?.execute("INSERT INTO provider_holds(provider,reason,created) VALUES (?1,?2,?3) ON CONFLICT(provider) DO UPDATE SET reason=excluded.reason,created=excluded.created",params![provider,reason,now_ms() as i64])?;
        Ok(())
    }
    pub fn provider_hold(&self, provider: &str) -> Result<Option<String>> {
        let provider = canonical_provider(provider);
        valid_id(provider)?;
        Ok(self
            .conn()?
            .query_row(
                "SELECT reason FROM provider_holds WHERE provider=?1",
                [provider],
                |r| r.get(0),
            )
            .optional()?)
    }
    pub fn release_provider_hold(&self, provider: &str, reason: &str) -> Result<()> {
        let provider = canonical_provider(provider);
        valid_id(provider)?;
        ensure!(!reason.trim().is_empty(), "operator review reason required");
        let _guard = self.acquire_provider(provider)?;
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let pending:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM rounds WHERE provider=?1 AND status IN ('prepared','in_flight','open','uncertain'))",[provider],|r|r.get(0))?;
        ensure!(
            !pending,
            "cannot release a provider with an unresolved round; preserve its original owner"
        );
        let changed = tx.execute("DELETE FROM provider_holds WHERE provider=?1", [provider])?;
        ensure!(changed == 1, "provider has no hold to release");
        tx.execute("INSERT INTO operator_actions(provider,action,reason,recorded) VALUES (?1,'release_hold',?2,?3)",params![provider,reason,now_ms() as i64])?;
        tx.commit()?;
        Ok(())
    }
    /// End a reviewed attempt that provably never recorded financial intent.
    /// The original owner, requests, responses and frames remain immutable.
    /// A new campaign may proceed after any separate provider hold is reviewed.
    pub fn recover_nonfinancial_round(&self, id: &str, reason: &str) -> Result<RoundRecord> {
        ensure!(!reason.trim().is_empty(), "operator review reason required");
        let record = self.round(id)?;
        let provider = canonical_provider(&record.spec.provider);
        let _guard = self.acquire_provider(provider)?;
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let record = read_round(&tx, id)?;
        ensure!(
            matches!(
                record.status,
                RoundStatus::Prepared
                    | RoundStatus::InFlight
                    | RoundStatus::Open
                    | RoundStatus::Uncertain
                    | RoundStatus::Blocked
            ),
            "round is already concluded"
        );
        let financial: bool = tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM exchanges WHERE round_id=?1 AND financial=1)",
            [id],
            |r| r.get(0),
        )?;
        ensure!(
            !financial,
            "financial intent exists; retain the original owner and unresolved root"
        );
        let prior:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM operator_actions WHERE action='recover_nonfinancial_round' AND reason LIKE ?1)",[format!("round {id}:%")],|r|r.get(0))?;
        ensure!(!prior, "nonfinancial attempt was already recovered");
        let audit = format!("round {id}: {reason}");
        tx.execute("UPDATE exchanges SET error=?1 WHERE round_id=?2 AND response IS NULL AND error IS NULL",params![audit,id])?;
        // Preserve an earlier reason as historical evidence instead of replacing it.
        let retained_reason = match record.reason {
            Some(old) => format!("{old}; {audit}"),
            None => audit.clone(),
        };
        tx.execute(
            "UPDATE rounds SET status='blocked',reason=?1,updated=?2 WHERE id=?3",
            params![retained_reason, now_ms() as i64, id],
        )?;
        tx.execute("INSERT INTO operator_actions(provider,action,reason,recorded) VALUES (?1,'recover_nonfinancial_round',?2,?3)",params![provider,audit,now_ms() as i64])?;
        let result = read_round(&tx, id)?;
        tx.commit()?;
        Ok(result)
    }
    /// Called only while the engine owns this provider's lock. This is a new
    /// bootstrap attempt, never a replay of a financial exchange.
    pub(crate) fn prepare_bootstrap_retry(&self, id: &str) -> Result<bool> {
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let record = read_round(&tx, id)?;
        if record.status != RoundStatus::Blocked {
            return Ok(false);
        }
        let prohibited:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM exchanges WHERE round_id=?1 AND financial=1) OR EXISTS(SELECT 1 FROM exchanges WHERE round_id=?1 AND response IS NULL AND error IS NULL) OR EXISTS(SELECT 1 FROM bootstrap_retries WHERE round_id=?1)",[id],|r|r.get(0))?;
        if prohibited {
            return Ok(false);
        }
        let latest:Option<(i64,String,Option<String>)>=tx.query_row("SELECT ordinal,request,response FROM exchanges WHERE round_id=?1 ORDER BY ordinal DESC LIMIT 1",[id],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).optional()?;
        let Some((ordinal, request, Some(response))) = latest else {
            return Ok(false);
        };
        let request: WireRequest = decode(request)?;
        let response: WireResponse = decode(response)?;
        if request.transport != "http"
            || request.financial
            || response.status != 403
            || response
                .headers
                .contains_key("x-evidencia-body-completeness")
            || response
                .headers
                .get("cf-mitigated")
                .is_some_and(|v| v.eq_ignore_ascii_case("challenge"))
        {
            return Ok(false);
        }
        let provider = canonical_provider(&record.spec.provider);
        let held: Option<String> = tx
            .query_row(
                "SELECT reason FROM provider_holds WHERE provider=?1",
                [provider],
                |r| r.get(0),
            )
            .optional()?;
        // Never clear another operator's or another round's hold.
        let expected = format!(
            "HTTP 403 at {}: access rejected; cause not established; explicit operator review required",
            request.label
        );
        if record.reason.as_deref() != Some(expected.as_str())
            || held.as_deref() != Some(expected.as_str())
        {
            return Ok(false);
        }
        let owner: Option<String> =
            tx.query_row("SELECT owner FROM rounds WHERE id=?1", [id], |r| r.get(0))?;
        tx.execute("INSERT INTO bootstrap_retries(round_id,rejected_ordinal,owner,recorded) VALUES (?1,?2,?3,?4)",params![id,ordinal,owner,now_ms() as i64])?;
        tx.execute("INSERT INTO operator_actions(provider,action,reason,recorded) VALUES (?1,'bootstrap_fresh_context',?2,?3)",params![provider,format!("round {id}: one fresh bootstrap after retained HTTP 403 at exchange {ordinal}; no financial intent"),now_ms() as i64])?;
        tx.execute("DELETE FROM provider_holds WHERE provider=?1", [provider])?;
        tx.execute(
            "UPDATE rounds SET status='prepared',owner=NULL,reason=NULL,updated=?1 WHERE id=?2",
            params![now_ms() as i64, id],
        )?;
        tx.commit()?;
        Ok(true)
    }
    pub fn append_frame(&self, id: &str, ordinal: u64, kind: &str, body: &str) -> Result<()> {
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let open:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM exchanges WHERE round_id=?1 AND ordinal=?2 AND response IS NULL AND error IS NULL)",params![id,ordinal as i64],|r|r.get(0))?;
        ensure!(
            open,
            "cannot append a frame to a resolved or missing exchange"
        );
        let next:i64=tx.query_row("SELECT COALESCE(MAX(sequence),0)+1 FROM received_frames WHERE round_id=?1 AND ordinal=?2",params![id,ordinal as i64],|r|r.get(0))?;
        tx.execute("INSERT INTO received_frames(round_id,ordinal,sequence,kind,body,recorded) VALUES (?1,?2,?3,?4,?5,?6)",params![id,ordinal as i64,next,kind,body,now_ms() as i64])?;
        tx.commit()?;
        Ok(())
    }
    pub fn frames(&self, id: &str, ordinal: u64) -> Result<Vec<WireFrame>> {
        read_frames(&self.conn()?, id, ordinal)
    }
    pub fn install_inventory(&self, snapshot: &InventorySnapshot) -> Result<()> {
        self.save_inventory(snapshot, true)
    }
    pub fn cache_inventory(&self, snapshot: &InventorySnapshot) -> Result<()> {
        self.save_inventory(snapshot, false)
    }
    fn save_inventory(&self, snapshot: &InventorySnapshot, select: bool) -> Result<()> {
        let mut c = self.conn()?;
        let tx = c.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let data = json(snapshot)?;
        if !select {
            // Preserve the previous default when opening a database from before inventory_selection.
            tx.execute(
                "INSERT OR IGNORE INTO inventory_selection
                 SELECT 1,id FROM inventories ORDER BY rowid DESC LIMIT 1",
                [],
            )?;
        }
        let old: Option<String> = tx
            .query_row(
                "SELECT data FROM inventories WHERE id=?1",
                [&snapshot.id],
                |r| r.get(0),
            )
            .optional()?;
        if let Some(old) = old {
            let prior: InventorySnapshot = decode(old)?;
            ensure!(
                json(&prior.providers)? == json(&snapshot.providers)?,
                "inventory id collision"
            );
        } else {
            tx.execute(
                "INSERT INTO inventories VALUES (?1,?2,?3)",
                params![snapshot.id, data, now_ms() as i64],
            )?;
        }
        if select {
            tx.execute(
                "INSERT INTO inventory_selection VALUES(1,?1)
                 ON CONFLICT(singleton) DO UPDATE SET inventory_id=excluded.inventory_id",
                [&snapshot.id],
            )?;
        }
        tx.commit()?;
        Ok(())
    }
    pub fn inventory(&self, id: Option<&str>) -> Result<InventorySnapshot> {
        let c = self.conn()?;
        let data: String = if let Some(id) = id {
            c.query_row("SELECT data FROM inventories WHERE id=?1", [id], |r| {
                r.get(0)
            })?
        } else {
            c.query_row(
                "SELECT data FROM inventories
                 WHERE id=COALESCE(
                     (SELECT inventory_id FROM inventory_selection WHERE singleton=1),
                     (SELECT id FROM inventories ORDER BY rowid DESC LIMIT 1)
                 )",
                [],
                |r| r.get(0),
            )?
        };
        decode(data)
    }
    pub fn create_campaign(&self, plan: &CampaignPlan) -> Result<()> {
        let mut c = self.conn()?;
        let tx = c.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let data = json(plan)?;
        let old: Option<String> = tx
            .query_row("SELECT data FROM campaigns WHERE id=?1", [&plan.id], |r| {
                r.get(0)
            })
            .optional()?;
        if let Some(old) = old {
            ensure!(old == data, "campaign id already has a different plan");
        } else {
            tx.execute(
                "INSERT INTO campaigns VALUES (?1,?2,?3)",
                params![plan.id, plan.inventory_id, data],
            )?;
        }
        tx.commit()?;
        Ok(())
    }
    pub fn campaign(&self, id: &str) -> Result<CampaignPlan> {
        decode(
            self.conn()?
                .query_row("SELECT data FROM campaigns WHERE id=?1", [id], |r| r.get(0))?,
        )
    }
    pub fn acquire_provider(&self, provider: &str) -> Result<ProviderGuard> {
        let canonical = canonical_provider(provider);
        valid_id(canonical)?;
        let dir = self.root.join("locks");
        fs::create_dir_all(&dir)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&dir, fs::Permissions::from_mode(0o700))?;
        }
        let f = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(dir.join(format!("{canonical}.lock")))?;
        f.try_lock_exclusive()
            .context("provider is locked by another process")?;
        Ok(ProviderGuard { _file: f })
    }
    pub fn create_round(&self, spec: &RoundSpec) -> Result<RoundRecord> {
        let mut c = self.conn()?;
        let tx = c.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let prior: Option<String> = tx
            .query_row(
                "SELECT id FROM rounds WHERE campaign_id=?1 AND job=?2 AND sample=?3",
                params![spec.campaign_id, spec.job_index, spec.sample_index],
                |r| r.get(0),
            )
            .optional()?;
        if let Some(id) = prior {
            let record = read_round(&tx, &id)?;
            ensure!(
                json(&record.spec)? == json(spec)?,
                "sample already exists with different specification"
            );
            tx.commit()?;
            return Ok(record);
        }
        let plan: CampaignPlan = decode(tx.query_row(
            "SELECT data FROM campaigns WHERE id=?1",
            [&spec.campaign_id],
            |r| r.get(0),
        )?)?;
        ensure!(
            plan.inventory_id == spec.inventory_id,
            "campaign inventory mismatch"
        );
        let job = plan
            .jobs
            .get(spec.job_index as usize)
            .context("job index out of range")?;
        ensure!(
            spec.sample_index < job.samples
                && job.provider == spec.provider
                && job.game == spec.game
                && job.mode == spec.mode
                && job.settings == spec.settings,
            "round does not match campaign job"
        );
        let inventory: InventorySnapshot = decode(tx.query_row(
            "SELECT data FROM inventories WHERE id=?1",
            [&spec.inventory_id],
            |r| r.get(0),
        )?)?;
        let (_, _, mode) = inventory.lookup(&spec.provider, &spec.game, &spec.mode)?;
        ensure!(mode.kind == spec.kind, "round mode kind mismatch");
        let canonical = canonical_provider(&spec.provider);
        valid_id(canonical)?;
        let held: bool = tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM provider_holds WHERE provider=?1)",
            [canonical],
            |r| r.get(0),
        )?;
        ensure!(!held, "provider is held");
        let id = Uuid::new_v4().to_string();
        let now = now_ms() as i64;
        tx.execute("INSERT INTO rounds(id,campaign_id,job,sample,provider,spec,status,created,updated) VALUES (?1,?2,?3,?4,?5,?6,'prepared',?7,?7)",params![id,spec.campaign_id,spec.job_index,spec.sample_index,canonical,json(spec)?,now]).context("provider already has an active or uncertain round")?;
        let record = read_round(&tx, &id)?;
        tx.commit()?;
        Ok(record)
    }
    pub fn save_session(&self, id: &str, owner: &Value) -> Result<()> {
        ensure!(
            !owner.is_null()
                && !matches!(owner,Value::Object(m) if m.is_empty())
                && !matches!(owner,Value::String(s) if s.is_empty()),
            "session owner missing"
        );
        let mut c = self.conn()?;
        let tx = c.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let (old, status): (Option<String>, String) =
            tx.query_row("SELECT owner,status FROM rounds WHERE id=?1", [id], |r| {
                Ok((r.get(0)?, r.get(1)?))
            })?;
        ensure!(
            matches!(status.as_str(), "prepared" | "open" | "in_flight"),
            "round is not active"
        );
        if let Some(old) = old {
            ensure!(
                serde_json::from_str::<Value>(&old)? == *owner,
                "session owner cannot be replaced"
            );
        } else {
            tx.execute(
                "UPDATE rounds SET owner=?1,updated=?2 WHERE id=?3",
                params![json(owner)?, now_ms() as i64, id],
            )?;
        }
        tx.commit()?;
        Ok(())
    }
    pub fn session(&self, id: &str) -> Result<Option<Value>> {
        let owner: Option<String> =
            self.conn()?
                .query_row("SELECT owner FROM rounds WHERE id=?1", [id], |r| r.get(0))?;
        owner.map(decode).transpose()
    }
    pub fn start_exchange(&self, id: &str, request: &WireRequest) -> Result<u64> {
        let mut c = self.conn()?;
        let tx = c.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let (status, owner, provider): (String, Option<String>, String) = tx.query_row(
            "SELECT status,owner,provider FROM rounds WHERE id=?1",
            [id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )?;
        let held: bool = tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM provider_holds WHERE provider=?1)",
            [provider],
            |r| r.get(0),
        )?;
        ensure!(!held, "provider is held");
        ensure!(
            matches!(status.as_str(), "prepared" | "open"),
            "round cannot send in state {status}"
        );
        ensure!(
            !request.financial || owner.is_some(),
            "financial exchange requires original session owner"
        );
        let unresolved:i64=tx.query_row("SELECT COUNT(*) FROM exchanges WHERE round_id=?1 AND response IS NULL AND error IS NULL",[id],|r|r.get(0))?;
        ensure!(unresolved == 0, "unresolved exchange blocks another send");
        let ordinal: i64 = tx.query_row(
            "SELECT COALESCE(MAX(ordinal),0)+1 FROM exchanges WHERE round_id=?1",
            [id],
            |r| r.get(0),
        )?;
        let data = json(request)?;
        tx.execute("INSERT INTO exchanges(round_id,ordinal,request,request_hash,financial) VALUES (?1,?2,?3,?4,?5)",params![id,ordinal,data,sha256(data.as_bytes()),request.financial])?;
        tx.execute(
            "UPDATE rounds SET status='in_flight',updated=?1 WHERE id=?2",
            params![now_ms() as i64, id],
        )?;
        tx.commit()?;
        Ok(ordinal as u64)
    }
    pub fn finish_exchange(&self, id: &str, ordinal: u64, response: &WireResponse) -> Result<()> {
        let mut c = self.conn()?;
        let tx = c.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let data = json(response)?;
        let changed=tx.execute("UPDATE exchanges SET response=?1,response_hash=?2 WHERE round_id=?3 AND ordinal=?4 AND response IS NULL AND error IS NULL",params![data,sha256(data.as_bytes()),id,ordinal as i64])?;
        ensure!(
            changed == 1,
            "exchange response already recorded or exchange missing"
        );
        tx.execute(
            "UPDATE rounds SET status='open',updated=?1 WHERE id=?2 AND status='in_flight'",
            params![now_ms() as i64, id],
        )?;
        tx.commit()?;
        Ok(())
    }
    pub fn fail_exchange(&self, id: &str, ordinal: u64, reason: &str) -> Result<()> {
        let mut c = self.conn()?;
        let tx = c.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let n=tx.execute("UPDATE exchanges SET error=?1 WHERE round_id=?2 AND ordinal=?3 AND response IS NULL AND error IS NULL",params![reason,id,ordinal as i64])?;
        ensure!(n == 1, "exchange already resolved or missing");
        let financial: bool = tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM exchanges WHERE round_id=?1 AND financial=1)",
            [id],
            |r| r.get(0),
        )?;
        tx.execute(
            "UPDATE rounds SET status=?1,reason=?2,updated=?3 WHERE id=?4",
            params![
                if financial { "uncertain" } else { "blocked" },
                reason,
                now_ms() as i64,
                id
            ],
        )?;
        tx.commit()?;
        Ok(())
    }
    pub fn mark_error(&self, id: &str, reason: &str) -> Result<()> {
        let mut c = self.conn()?;
        let tx = c.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let record = read_round(&tx, id)?;
        ensure!(!record.status.terminal(), "round already terminal");
        let financial: bool = tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM exchanges WHERE round_id=?1 AND financial=1)",
            [id],
            |r| r.get(0),
        )?;
        tx.execute(
            "UPDATE rounds SET status=?1,reason=?2,updated=?3 WHERE id=?4",
            params![
                if financial { "uncertain" } else { "blocked" },
                reason,
                now_ms() as i64,
                id
            ],
        )?;
        tx.commit()?;
        Ok(())
    }
    pub fn complete(&self, id: &str, outcome: &RoundOutcome) -> Result<RoundRecord> {
        let mut c = self.conn()?;
        let tx = c.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let record = read_round(&tx, id)?;
        ensure!(
            matches!(record.status, RoundStatus::Open),
            "round is not open"
        );
        let unresolved:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM exchanges WHERE round_id=?1 AND response IS NULL AND error IS NULL)",[id],|r|r.get(0))?;
        ensure!(!unresolved, "unresolved exchange");
        let financial:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM exchanges WHERE round_id=?1 AND financial=1 AND response IS NOT NULL)",[id],|r|r.get(0))?;
        ensure!(financial, "cannot complete without a financial response");
        let mut outcome = outcome.clone();
        let check = outcome.verify();
        let (status, reason) = if !outcome.native_closed {
            ("uncertain", Some("native round remains open".to_string()))
        } else {
            match check {
                Ok(true) => ("verified", None),
                Ok(false) => (
                    "validation_failed",
                    Some("verification checks failed".into()),
                ),
                Err(e) => ("validation_failed", Some(format!("invalid outcome: {e}"))),
            }
        };
        tx.execute(
            "UPDATE rounds SET status=?1,reason=?2,outcome=?3,updated=?4 WHERE id=?5",
            params![status, reason, json(&outcome)?, now_ms() as i64, id],
        )?;
        if status == "validation_failed" {
            tx.execute("INSERT INTO provider_holds(provider,reason,created) VALUES (?1,?2,?3) ON CONFLICT(provider) DO UPDATE SET reason=excluded.reason,created=excluded.created",params![canonical_provider(&record.spec.provider),format!("round {id} failed native/wallet validation"),now_ms() as i64])?;
        }
        let r = read_round(&tx, id)?;
        tx.commit()?;
        Ok(r)
    }
    pub fn round(&self, id: &str) -> Result<RoundRecord> {
        read_round(&self.conn()?, id)
    }
    pub fn rounds(&self) -> Result<Vec<RoundRecord>> {
        let c = self.conn()?;
        let mut q = c.prepare("SELECT id FROM rounds ORDER BY created,id")?;
        let ids = q
            .query_map([], |r| r.get::<_, String>(0))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        ids.iter().map(|id| read_round(&c, id)).collect()
    }
    pub fn exchanges(&self, id: &str) -> Result<Vec<ExchangeRecord>> {
        let c = self.conn()?;
        let mut q=c.prepare("SELECT ordinal,request,response,error,request_hash,response_hash FROM exchanges WHERE round_id=?1 ORDER BY ordinal")?;
        let rows = q
            .query_map([id], |r| {
                Ok((
                    r.get::<_, i64>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, Option<String>>(2)?,
                    r.get::<_, Option<String>>(3)?,
                    r.get::<_, String>(4)?,
                    r.get::<_, Option<String>>(5)?,
                ))
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        rows.into_iter()
            .map(
                |(ordinal, request, response, error, request_sha256, response_sha256)| {
                    Ok(ExchangeRecord {
                        ordinal: ordinal as u64,
                        request: decode(request)?,
                        response: response.map(decode).transpose()?,
                        error,
                        request_sha256,
                        response_sha256,
                        frames: read_frames(&c, id, ordinal as u64)?,
                    })
                },
            )
            .collect()
    }
    pub fn pending_provider(&self, provider: &str) -> Result<Option<RoundRecord>> {
        let c = self.conn()?;
        let id:Option<String>=c.query_row("SELECT id FROM rounds WHERE provider=?1 AND status IN ('prepared','in_flight','open','uncertain')",[canonical_provider(provider)],|r|r.get(0)).optional()?;
        id.map(|id| read_round(&c, &id)).transpose()
    }
}

pub(crate) fn read_bootstrap_attempts(conn: &Connection, id: &str) -> Result<Vec<Value>> {
    let mut query = conn.prepare(
        "SELECT rejected_ordinal,owner,recorded FROM bootstrap_retries WHERE round_id=?1",
    )?;
    let rows = query
        .query_map([id], |row| {
            Ok((
                row.get::<_, i64>(0)?,
                row.get::<_, Option<String>>(1)?,
                row.get::<_, i64>(2)?,
            ))
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    rows.into_iter()
        .map(|(ordinal, owner, recorded)| {
            let ordinal = u64::try_from(ordinal)?;
            let recorded = u64::try_from(recorded)?;
            let owner: Option<Value> = owner
                .map(|value| serde_json::from_str(&value))
                .transpose()?;
            Ok(serde_json::json!({"rejected_ordinal":ordinal,"owner":owner,"recorded":recorded}))
        })
        .collect()
}
fn read_round(c: &Connection, id: &str) -> Result<RoundRecord> {
    let row: (String, String, i64, i64, Option<String>, Option<String>) = c.query_row(
        "SELECT spec,status,created,updated,reason,outcome FROM rounds WHERE id=?1",
        [id],
        |r| {
            Ok((
                r.get(0)?,
                r.get(1)?,
                r.get(2)?,
                r.get(3)?,
                r.get(4)?,
                r.get(5)?,
            ))
        },
    )?;
    let status = match row.1.as_str() {
        "prepared" => RoundStatus::Prepared,
        "in_flight" => RoundStatus::InFlight,
        "open" => RoundStatus::Open,
        "verified" => RoundStatus::Verified,
        "validation_failed" => RoundStatus::ValidationFailed,
        "uncertain" => RoundStatus::Uncertain,
        "blocked" => RoundStatus::Blocked,
        _ => bail!("invalid round status"),
    };
    Ok(RoundRecord {
        id: id.into(),
        spec: decode(row.0)?,
        status,
        created_at: row.2 as u64,
        updated_at: row.3 as u64,
        reason: row.4,
        outcome: row.5.map(decode).transpose()?,
    })
}

// Shared with the snapshot exporter so frames stay in the same read transaction.
pub(crate) fn read_frames(conn: &Connection, id: &str, ordinal: u64) -> Result<Vec<WireFrame>> {
    let mut query=conn.prepare("SELECT sequence,kind,body,recorded FROM received_frames WHERE round_id=?1 AND ordinal=?2 ORDER BY sequence")?;
    Ok(query
        .query_map(params![id, ordinal as i64], |r| {
            Ok(WireFrame {
                sequence: r.get::<_, i64>(0)? as u64,
                kind: r.get(1)?,
                body: r.get(2)?,
                recorded_at: r.get::<_, i64>(3)? as u64,
            })
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    #[test]
    fn standalone_inventory_preserves_the_explicit_import() {
        let (_dir, store, _) = setup();
        let imported = store.inventory(None).unwrap();
        let mut standalone = imported.clone();
        standalone.id = "standalone".into();

        store.cache_inventory(&standalone).unwrap();
        assert_eq!(store.inventory(None).unwrap().id, imported.id);
        assert_eq!(
            store.inventory(Some("standalone")).unwrap().id,
            standalone.id
        );
        store.install_inventory(&standalone).unwrap();
        assert_eq!(store.inventory(None).unwrap().id, standalone.id);
        store.install_inventory(&imported).unwrap();
        assert_eq!(store.inventory(None).unwrap().id, imported.id);
    }

    fn setup() -> (tempfile::TempDir, Store, RoundSpec) {
        let dir = tempfile::tempdir().unwrap();
        let store = Store::open(dir.path()).unwrap();
        let snapshot = InventorySnapshot {
            id: "inventory".into(),
            sources: vec![],
            providers: vec![ProviderInventory {
                id: "pragmatic".into(),
                name: "P".into(),
                ready: true,
                campaign_eligible: true,
                protocol: Value::Null,
                games: vec![Game {
                    id: "g".into(),
                    name: "G".into(),
                    ready: true,
                    block_reason: String::new(),
                    modes: vec![Mode {
                        key: "normal".into(),
                        kind: ModeKind::Normal,
                        label: "Normal".into(),
                        ready: true,
                        requires_prerequisites: Value::Null,
                        execution_source: None,
                    }],
                }],
            }],
        };
        store.install_inventory(&snapshot).unwrap();
        let plan = CampaignPlan {
            schema_version: 1,
            id: "campaign".into(),
            inventory_id: "inventory".into(),
            coverage: None,
            jobs: vec![Job {
                provider: "pragmatic".into(),
                game: "g".into(),
                mode: "normal".into(),
                samples: 2,
                settings: Value::Null,
            }],
        };
        store.create_campaign(&plan).unwrap();
        let spec = RoundSpec {
            campaign_id: plan.id,
            inventory_id: plan.inventory_id,
            job_index: 0,
            sample_index: 0,
            provider: "pragmatic".into(),
            game: "g".into(),
            mode: "normal".into(),
            kind: ModeKind::Normal,
            settings: Value::Null,
        };
        (dir, store, spec)
    }
    fn request(financial: bool) -> WireRequest {
        WireRequest {
            label: "spin".into(),
            transport: "http".into(),
            method: "POST".into(),
            url: "https://example.test".into(),
            headers: BTreeMap::new(),
            body: "{}".into(),
            financial,
        }
    }
    #[test]
    fn provider_schedule_is_shared_by_alias_and_survives_restart() {
        let (dir, store, _) = setup();
        assert_eq!(
            store.reserve_provider_start("pragmatic", 40).unwrap(),
            Duration::ZERO
        );
        let reopened = Store::open(dir.path()).unwrap();
        let delay = reopened.reserve_provider_start("reelkingdom", 40).unwrap();
        assert!(delay >= Duration::from_secs(39) && delay <= Duration::from_secs(40));
        assert!(
            reopened
                .reserve_provider_start("hacksaw", 1)
                .unwrap()
                .is_zero()
        );
    }
    #[test]
    fn financial_requires_owner_and_failure_survives_restart() {
        let (dir, store, spec) = setup();
        let round = store.create_round(&spec).unwrap();
        assert!(store.start_exchange(&round.id, &request(true)).is_err());
        store
            .save_session(&round.id, &serde_json::json!({"session":"one"}))
            .unwrap();
        assert!(
            store
                .save_session(&round.id, &serde_json::json!({"session":"two"}))
                .is_err()
        );
        let ord = store.start_exchange(&round.id, &request(true)).unwrap();
        store.fail_exchange(&round.id, ord, "timeout").unwrap();
        drop(store);
        let reopened = Store::open(dir.path()).unwrap();
        assert_eq!(
            reopened.round(&round.id).unwrap().status,
            RoundStatus::Uncertain
        );
        assert_eq!(reopened.create_round(&spec).unwrap().id, round.id);
        let mut next = spec.clone();
        next.sample_index = 1;
        assert!(reopened.create_round(&next).is_err());
        assert!(reopened.start_exchange(&round.id, &request(true)).is_err());
    }
    #[test]
    fn response_is_append_only_and_holds_survive() {
        let (dir, store, spec) = setup();
        let r = store.create_round(&spec).unwrap();
        let ord = store.start_exchange(&r.id, &request(false)).unwrap();
        let response = WireResponse {
            status: 200,
            headers: BTreeMap::new(),
            body: "first".into(),
            set_cookies: Vec::new(),
        };
        store.finish_exchange(&r.id, ord, &response).unwrap();
        let mut other = response.clone();
        other.body = "replacement".into();
        assert!(store.finish_exchange(&r.id, ord, &other).is_err());
        assert_eq!(
            store.exchanges(&r.id).unwrap()[0]
                .response
                .as_ref()
                .unwrap()
                .body,
            "first"
        );
        store.hold_provider("pragmatic", "HTTP 403").unwrap();
        assert!(store.start_exchange(&r.id, &request(false)).is_err());
        let reopened = Store::open(dir.path()).unwrap();
        assert_eq!(
            reopened.provider_hold("reelkingdom").unwrap().as_deref(),
            Some("HTTP 403")
        );
        assert!(
            reopened
                .release_provider_hold("pragmatic", "reviewed")
                .is_err()
        );
        reopened.mark_error(&r.id, "blocked before stake").unwrap();
        reopened
            .release_provider_hold("pragmatic", "reviewed offline")
            .unwrap();
        assert!(reopened.provider_hold("pragmatic").unwrap().is_none());
    }
    #[test]
    fn locks_exclude_aliases_and_handles() {
        let (dir, store, _) = setup();
        let other = Store::open(dir.path()).unwrap();
        let guard = store.acquire_provider("pragmatic").unwrap();
        assert!(other.acquire_provider("reelkingdom").is_err());
        drop(guard);
        assert!(other.acquire_provider("reelkingdom").is_ok());
    }
    #[test]
    fn process_lock_child() {
        if let Some(path) = std::env::var_os("RUNNER_LOCK_TEST_PATH") {
            let store = Store::open(path).unwrap();
            assert!(store.acquire_provider("reelkingdom").is_err());
        }
    }
    #[test]
    fn provider_lock_excludes_another_process() {
        let (dir, store, _) = setup();
        let _guard = store.acquire_provider("pragmatic").unwrap();
        let result = std::process::Command::new(std::env::current_exe().unwrap())
            .arg("--exact")
            .arg("store::tests::process_lock_child")
            .arg("--nocapture")
            .env("RUNNER_LOCK_TEST_PATH", dir.path())
            .status()
            .unwrap();
        assert!(result.success());
    }
    #[test]
    fn audited_recovery_preserves_crashed_nonfinancial_history_and_owner() {
        let (dir, store, spec) = setup();
        let round = store.create_round(&spec).unwrap();
        let owner = serde_json::json!({"id":"bootstrap-owner"});
        store.save_session(&round.id, &owner).unwrap();
        let ordinal = store.start_exchange(&round.id, &request(false)).unwrap();
        store
            .append_frame(&round.id, ordinal, "http_body_base64", "cGFydGlhbA==")
            .unwrap();
        drop(store);
        let reopened = Store::open(dir.path()).unwrap();
        assert!(reopened.recover_nonfinancial_round(&round.id, "").is_err());
        let recovered = reopened
            .recover_nonfinancial_round(&round.id, "reviewed crash before financial dispatch")
            .unwrap();
        assert_eq!(recovered.status, RoundStatus::Blocked);
        assert!(reopened.pending_provider("pragmatic").unwrap().is_none());
        assert_eq!(reopened.session(&round.id).unwrap(), Some(owner));
        let records = reopened.exchanges(&round.id).unwrap();
        assert_eq!(records.len(), 1);
        assert_eq!(records[0].frames[0].body, "cGFydGlhbA==");
        assert!(
            records[0]
                .error
                .as_ref()
                .unwrap()
                .contains("reviewed crash")
        );
        assert!(reopened.start_exchange(&round.id, &request(false)).is_err());
        let actions: i64 = reopened
            .conn()
            .unwrap()
            .query_row(
                "SELECT COUNT(*) FROM operator_actions WHERE action='recover_nonfinancial_round'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(actions, 1);
        assert!(
            reopened
                .recover_nonfinancial_round(&round.id, "repeat")
                .is_err()
        );
        let mut next = spec;
        next.sample_index = 1;
        assert!(reopened.create_round(&next).is_ok());
    }
    #[test]
    fn recovery_rejects_every_financial_intent_and_active_provider_lock() {
        for completed_response in [false, true] {
            let (_dir, store, spec) = setup();
            let round = store.create_round(&spec).unwrap();
            store
                .save_session(&round.id, &serde_json::json!({"id":"original"}))
                .unwrap();
            let ordinal = store.start_exchange(&round.id, &request(true)).unwrap();
            if completed_response {
                store
                    .finish_exchange(
                        &round.id,
                        ordinal,
                        &WireResponse {
                            status: 403,
                            headers: BTreeMap::new(),
                            body: "denied".into(),
                            set_cookies: vec![],
                        },
                    )
                    .unwrap();
            }
            assert!(
                store
                    .recover_nonfinancial_round(&round.id, "reviewed")
                    .is_err()
            );
            assert_eq!(
                store.session(&round.id).unwrap(),
                Some(serde_json::json!({"id":"original"}))
            );
            assert!(store.pending_provider("pragmatic").unwrap().is_some());
        }
        let (_dir, store, spec) = setup();
        let round = store.create_round(&spec).unwrap();
        let _guard = store.acquire_provider("reelkingdom").unwrap();
        assert!(
            store
                .recover_nonfinancial_round(&round.id, "reviewed")
                .is_err()
        );
        assert_eq!(
            store.round(&round.id).unwrap().status,
            RoundStatus::Prepared
        );
    }
    #[test]
    fn crash_after_dispatch_does_not_allow_resend() {
        let (dir, store, spec) = setup();
        let round = store.create_round(&spec).unwrap();
        store
            .save_session(&round.id, &serde_json::json!({"id":"original"}))
            .unwrap();
        store.start_exchange(&round.id, &request(true)).unwrap();
        drop(store);
        let reopened = Store::open(dir.path()).unwrap();
        assert_eq!(
            reopened.round(&round.id).unwrap().status,
            RoundStatus::InFlight
        );
        assert!(reopened.start_exchange(&round.id, &request(true)).is_err());
        let mut other = spec;
        other.sample_index = 1;
        assert!(reopened.create_round(&other).is_err());
    }
}
