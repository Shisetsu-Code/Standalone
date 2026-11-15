use crate::{
    model::{ExchangeRecord, ModeKind, RoundRecord, RoundStatus},
    store::Store,
};
use anyhow::{Context, Result, ensure};
use serde::Serialize;
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    fs::{DirBuilder, OpenOptions},
    io::{BufWriter, Write},
    path::{Path, PathBuf},
};

pub struct ExportOptions {
    pub output: PathBuf,
    pub provider: Option<String>,
    pub game: Option<String>,
    pub kind: Option<ModeKind>,
    pub include_unverified: bool,
    pub include_wire: bool,
}
#[derive(Debug, Serialize)]
pub struct ExportGroup {
    pub inventory_id: String,
    pub provider: String,
    pub game: String,
    pub kind: String,
    pub mode: String,
    pub path: String,
    pub count: usize,
}
#[derive(Debug, Serialize)]
pub struct ExportSummary {
    pub schema_version: u32,
    pub count: usize,
    pub include_unverified: bool,
    pub include_wire: bool,
    pub groups: Vec<ExportGroup>,
}

/// Public, deliberately allowlisted representation; never serializes settings, errors or raw payloads.
pub fn public_round(r: &RoundRecord) -> Value {
    let outcome = r.outcome.as_ref().map(|o| {
        json!({
            "native_round_id":o.native_round_id, "currency":o.currency,
            "monetary_unit":o.monetary_unit,"currency_source":o.currency_source,
            "balance_before":o.balance_before,"balance_after":o.balance_after,
            "cost":o.cost,"payout":o.payout,"native_closed":o.native_closed,"checks":o.checks
        })
    });
    json!({"round_id":r.id,"inventory_id":r.spec.inventory_id,"campaign_id":r.spec.campaign_id,
        "job_index":r.spec.job_index,"sample_index":r.spec.sample_index,
        "provider":r.spec.provider,"game":r.spec.game,"mode":r.spec.mode,"type":r.spec.kind.as_str(),
        "operation":r.spec.kind.operation(),
        "status":r.status.as_str(),"created_at":r.created_at,"updated_at":r.updated_at,"outcome":outcome})
}

pub fn public_receipt(store: &Store, round: &RoundRecord) -> Value {
    use crate::adapters::irondog::{
        MISSING_CLOSING_BALANCE, WALLET_DISCREPANCY, audit_saved_round,
    };
    let mut value = public_round(round);
    if round.spec.provider == "irondog"
        && round.status == RoundStatus::Uncertain
        && matches!(
            round.reason.as_deref(),
            Some(
                MISSING_CLOSING_BALANCE
                    | WALLET_DISCREPANCY
                    | "Iron Dog native wallet did not reconcile"
            )
        )
    {
        match audit_saved_round(store, &round.id) {
            Ok(native) => value["native_receipt"] = json!(native),
            Err(_) => value["native_receipt_error"] = json!("saved exchange could not be verified"),
        }
    }
    value
}
pub fn private_steps(exchanges: &[ExchangeRecord]) -> Value {
    Value::Array(
        exchanges
            .iter()
            .map(|exchange| {
                let request = &exchange.request;
                json!({
                    "ordinal":exchange.ordinal,
                    "stage":request.label,
                    "transport":request.transport,
                    "method":request.method,
                    "endpoint":request.url,
                    "payload":request.body,
                    "financial_intent":request.financial,
                    "http_status":exchange.response.as_ref().map(|response| response.status),
                    "request_sha256":exchange.request_sha256,
                    "response_sha256":exchange.response_sha256,
                })
            })
            .collect(),
    )
}

// Lowercase portable identifiers stay readable; all others are encoded injectively.
fn component(value: &str) -> Result<String> {
    let safe = !value.is_empty()
        && value
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-' || b == b'_');
    let result = if safe {
        format!("s-{value}")
    } else {
        let mut out = String::from("x-");
        for b in value.as_bytes() {
            use std::fmt::Write as _;
            write!(&mut out, "{b:02x}")?;
        }
        out
    };
    ensure!(
        result.len() <= 240,
        "identifier is too long for a safe export path"
    );
    Ok(result)
}
fn mkdir(path: &Path) -> Result<()> {
    let builder = DirBuilder::new();
    #[cfg(unix)]
    let builder = {
        use std::os::unix::fs::DirBuilderExt;
        let mut b = builder;
        b.mode(0o700);
        b
    };
    builder
        .create(path)
        .with_context(|| format!("create export directory {}", path.display()))?;
    Ok(())
}
fn create_file(path: &Path) -> Result<std::fs::File> {
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    options
        .open(path)
        .with_context(|| format!("create export file {}", path.display()))
}
fn select(r: &RoundRecord, o: &ExportOptions) -> bool {
    (o.include_unverified || r.status == RoundStatus::Verified)
        && o.provider.as_ref().is_none_or(|v| v == &r.spec.provider)
        && o.game.as_ref().is_none_or(|v| v == &r.spec.game)
        && o.kind.is_none_or(|v| v == r.spec.kind)
}
// A single SQLite read transaction gives a consistent snapshot even while collectors run.
type SnapshotRow = (
    RoundRecord,
    Option<Value>,
    Vec<crate::model::ExchangeRecord>,
    Vec<Value>,
);
fn snapshot(store: &Store, options: &ExportOptions) -> Result<Vec<SnapshotRow>> {
    use rusqlite::{Connection, OpenFlags};
    let mut db = Connection::open_with_flags(
        store.root().join("runner.sqlite3"),
        OpenFlags::SQLITE_OPEN_READ_ONLY,
    )?;
    db.busy_timeout(std::time::Duration::from_secs(10))?;
    let tx = db.transaction()?;
    let rows = {
        let mut q=tx.prepare("SELECT id,spec,status,created,updated,reason,outcome,owner FROM rounds ORDER BY created,id")?;
        q.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, i64>(3)?,
                r.get::<_, i64>(4)?,
                r.get::<_, Option<String>>(5)?,
                r.get::<_, Option<String>>(6)?,
                r.get::<_, Option<String>>(7)?,
            ))
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?
    };
    let mut result = Vec::new();
    for (id, spec, status, created_at, updated_at, reason, outcome, owner) in rows {
        let r = RoundRecord {
            id: id.clone(),
            spec: serde_json::from_str(&spec)?,
            status: serde_json::from_value(Value::String(status))?,
            created_at: u64::try_from(created_at)?,
            updated_at: u64::try_from(updated_at)?,
            reason,
            outcome: outcome.map(|s| serde_json::from_str(&s)).transpose()?,
        };
        if !select(&r, options) {
            continue;
        }
        let mut exchanges = Vec::new();
        if options.include_wire {
            let mut q=tx.prepare("SELECT ordinal,request,response,error,request_hash,response_hash FROM exchanges WHERE round_id=?1 ORDER BY ordinal")?;
            let rows = q
                .query_map([&id], |r| {
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
            for (ordinal, request, response, error, request_sha256, response_sha256) in rows {
                exchanges.push(crate::model::ExchangeRecord {
                    ordinal: u64::try_from(ordinal)?,
                    request: serde_json::from_str(&request)?,
                    response: response.map(|s| serde_json::from_str(&s)).transpose()?,
                    error,
                    request_sha256,
                    response_sha256,
                    frames: crate::store::read_frames(&tx, &id, u64::try_from(ordinal)?)?,
                });
            }
        }
        let owner = if options.include_wire {
            owner.map(|s| serde_json::from_str(&s)).transpose()?
        } else {
            None
        };
        let bootstrap_attempts = if options.include_wire {
            crate::store::read_bootstrap_attempts(&tx, &id)?
        } else {
            vec![]
        };
        result.push((r, owner, exchanges, bootstrap_attempts));
    }
    tx.commit()?;
    Ok(result)
}
pub fn export(store: &Store, options: &ExportOptions) -> Result<ExportSummary> {
    // Capture each selected round once; group sorting and Store ordering give stable JSONL order.
    let mut groups: BTreeMap<(String, String, String, String, String), Vec<Value>> =
        BTreeMap::new();
    for (r, owner, exchanges, bootstrap_attempts) in snapshot(store, options)? {
        let key = (
            r.spec.inventory_id.clone(),
            r.spec.provider.clone(),
            r.spec.game.clone(),
            r.spec.kind.as_str().to_string(),
            r.spec.mode.clone(),
        );
        let mut value = public_receipt(store, &r);
        if options.include_wire {
            value["steps"] = private_steps(&exchanges);
            value["private"] = json!({"owner":owner,"bootstrap_attempts":bootstrap_attempts,"exchanges":exchanges,"native_data":r.outcome.as_ref().map(|o|&o.native_data)});
        }
        groups.entry(key).or_default().push(value);
    }
    // Validate all components before creating the destination.
    for key in groups.keys() {
        for item in [&key.0, &key.1, &key.2, &key.3, &key.4] {
            component(item)?;
        }
    }
    mkdir(&options.output)?;
    let mut summary = ExportSummary {
        schema_version: 1,
        count: 0,
        include_unverified: options.include_unverified,
        include_wire: options.include_wire,
        groups: Vec::new(),
    };
    for ((inventory_id, provider, game, kind, mode), values) in groups {
        let parts = [
            component(&inventory_id)?,
            component(&provider)?,
            component(&game)?,
            component(&kind)?,
            component(&mode)?,
        ];
        let mut dir = options.output.clone();
        for part in &parts {
            dir.push(part);
            if !dir.exists() {
                mkdir(&dir)?;
            }
        }
        let mut writer = BufWriter::new(create_file(&dir.join("tiradas.jsonl"))?);
        for v in &values {
            serde_json::to_writer(&mut writer, v)?;
            writer.write_all(b"\n")?;
        }
        writer.flush()?;
        let count = values.len();
        summary.count += count;
        let path = format!("{}/tiradas.jsonl", parts.join("/"));
        summary.groups.push(ExportGroup {
            inventory_id,
            provider,
            game,
            kind,
            mode,
            path,
            count,
        });
    }
    ensure!(
        summary.count == summary.groups.iter().map(|g| g.count).sum::<usize>(),
        "export count mismatch"
    );
    let mut manifest = BufWriter::new(create_file(&options.output.join("manifest.json"))?);
    serde_json::to_writer_pretty(&mut manifest, &summary)?;
    manifest.write_all(b"\n")?;
    manifest.flush()?;
    Ok(summary)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::*;
    use std::{collections::BTreeMap, fs};
    fn fixture() -> (tempfile::TempDir, Store, RoundRecord) {
        let d = tempfile::tempdir().unwrap();
        let store = Store::open(d.path().join("data")).unwrap();
        let snapshot = InventorySnapshot {
            id: "inv".into(),
            sources: vec![],
            providers: vec![ProviderInventory {
                id: "provider".into(),
                name: "Provider".into(),
                ready: true,
                campaign_eligible: true,
                protocol: Value::Null,
                games: vec![Game {
                    id: "../../outside".into(),
                    name: "Game".into(),
                    ready: true,
                    block_reason: String::new(),
                    modes: vec![Mode {
                        key: "normal".into(),
                        kind: ModeKind::Normal,
                        label: "normal".into(),
                        ready: true,
                        requires_prerequisites: Value::Null,
                        execution_source: None,
                    }],
                }],
            }],
        };
        store.install_inventory(&snapshot).unwrap();
        let settings = json!({"password":"settings-secret"});
        let plan = CampaignPlan {
            schema_version: 1,
            id: "campaign".into(),
            inventory_id: "inv".into(),
            coverage: None,
            jobs: vec![Job {
                provider: "provider".into(),
                game: "../../outside".into(),
                mode: "normal".into(),
                samples: 2,
                settings: settings.clone(),
            }],
        };
        store.create_campaign(&plan).unwrap();
        let spec = RoundSpec {
            campaign_id: "campaign".into(),
            inventory_id: "inv".into(),
            job_index: 0,
            sample_index: 0,
            provider: "provider".into(),
            game: "../../outside".into(),
            mode: "normal".into(),
            kind: ModeKind::Normal,
            settings,
        };
        let r = store.create_round(&spec).unwrap();
        (d, store, r)
    }
    fn options(p: PathBuf) -> ExportOptions {
        ExportOptions {
            output: p,
            provider: None,
            game: None,
            kind: None,
            include_unverified: false,
            include_wire: false,
        }
    }
    #[test]
    fn paths_are_safe_injective_and_portable() {
        let cases = [
            "../../outside",
            "",
            "abc",
            "ABC",
            "s-abc",
            "ñ",
            ".",
            "x-2e",
            "CON",
        ];
        let paths: std::collections::HashSet<_> =
            cases.iter().map(|s| component(s).unwrap()).collect();
        assert_eq!(paths.len(), cases.len());
        assert!(
            paths
                .iter()
                .all(|p| !p.contains('/') && !p.contains('\\') && p != "." && p != "..")
        );
    }
    #[test]
    fn exports_verified_public_data_only_and_refuses_overwrite() {
        let (dir, store, r) = fixture();
        let empty = options(dir.path().join("empty"));
        assert_eq!(export(&store, &empty).unwrap().count, 0);
        // An earlier nonfinancial bootstrap owner is confidential history even
        // when the same root later completes with a fresh public demo session.
        rusqlite::Connection::open(store.root().join("runner.sqlite3")).unwrap()
            .execute("INSERT INTO bootstrap_retries(round_id,rejected_ordinal,owner,recorded) VALUES (?1,1,?2,1)",
                rusqlite::params![r.id, r#"{"session":"bootstrap-owner-secret"}"#]).unwrap();
        store
            .save_session(&r.id, &json!({"id":"owner-secret"}))
            .unwrap();
        let request = WireRequest {
            label: "spin".into(),
            transport: "http".into(),
            method: "POST".into(),
            url: "https://example.test".into(),
            headers: BTreeMap::new(),
            body: "wire-secret".into(),
            financial: true,
        };
        let ordinal = store.start_exchange(&r.id, &request).unwrap();
        store
            .finish_exchange(
                &r.id,
                ordinal,
                &WireResponse {
                    status: 200,
                    headers: BTreeMap::new(),
                    body: "wire-response-secret".into(),
                    set_cookies: vec!["private-cookie=wire-cookie-secret; Secure".into()],
                },
            )
            .unwrap();
        let outcome = RoundOutcome {
            native_round_id: Some("native-id".into()),
            currency: "EUR".into(),
            monetary_unit: "native".into(),
            currency_source: "native_response".into(),
            balance_before: "10".into(),
            balance_after: "9".into(),
            cost: "1".into(),
            payout: "0".into(),
            native_closed: true,
            checks: BTreeMap::new(),
            native_data: json!({"secret":"native-secret"}),
        };
        assert_eq!(
            store.complete(&r.id, &outcome).unwrap().status,
            RoundStatus::Verified
        );
        let opts = options(dir.path().join("export"));
        let summary = export(&store, &opts).unwrap();
        assert_eq!(summary.count, 1);
        assert_eq!(summary.groups.len(), 1);
        let line = fs::read_to_string(opts.output.join(&summary.groups[0].path)).unwrap();
        assert!(!line.contains("secret"));
        let value: Value = serde_json::from_str(line.trim()).unwrap();
        assert!(value.get("steps").is_none());
        assert_eq!(value["game"], "../../outside");
        assert_eq!(value["outcome"]["native_round_id"], "native-id");
        assert_eq!(value["outcome"]["monetary_unit"], "native");
        assert_eq!(value["outcome"]["currency_source"], "native_response");
        assert!(export(&store, &opts).is_err());
        assert!(!dir.path().join("outside").exists());
        let private = ExportOptions {
            include_wire: true,
            ..options(dir.path().join("private"))
        };
        let sum = export(&store, &private).unwrap();
        let line = fs::read_to_string(private.output.join(&sum.groups[0].path)).unwrap();
        assert!(
            line.contains("owner-secret")
                && line.contains("bootstrap-owner-secret")
                && line.contains("wire-secret")
                && line.contains("native-secret")
                && line.contains("wire-cookie-secret")
        );
        assert!(!line.contains("settings-secret"));
        let value: Value = serde_json::from_str(line.trim()).unwrap();
        let step = &value["steps"][0];
        let exchange = &value["private"]["exchanges"][0];
        assert_eq!(step["endpoint"], exchange["request"]["url"]);
        assert_eq!(step["payload"], exchange["request"]["body"]);
        assert_eq!(step["request_sha256"], exchange["request_sha256"]);
        assert_eq!(step["http_status"], exchange["response"]["status"]);
        assert!(!step["endpoint"].is_null());
        let filtered = ExportOptions {
            provider: Some("other".into()),
            ..options(dir.path().join("filtered"))
        };
        assert_eq!(export(&store, &filtered).unwrap().count, 0);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                fs::metadata(&private.output).unwrap().permissions().mode() & 0o777,
                0o700
            );
            assert_eq!(
                fs::metadata(private.output.join(&sum.groups[0].path))
                    .unwrap()
                    .permissions()
                    .mode()
                    & 0o777,
                0o600
            );
        }
    }
    #[test]
    fn unverified_is_explicit_and_public_show_is_sanitized() {
        let (dir, store, r) = fixture();
        let public = public_round(&r).to_string();
        assert!(!public.contains("settings-secret"));
        let opts = ExportOptions {
            include_unverified: true,
            ..options(dir.path().join("export"))
        };
        assert_eq!(export(&store, &opts).unwrap().count, 1);
    }
}
