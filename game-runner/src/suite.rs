//! Reviewed local bridge to the existing suite. Process receipts are explicitly
//! labelled `process`; no synthetic provider HTTP response is created.
use crate::{context::RunContext, model::*};
use anyhow::{Context, Result, bail, ensure};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    fs::{self, OpenOptions},
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    process::Stdio,
    sync::{
        Arc, Mutex, OnceLock,
        atomic::{AtomicBool, Ordering},
    },
    time::{Duration, Instant},
};
use tokio::{
    io::{AsyncRead, AsyncReadExt},
    process::Command,
    time::timeout,
};

const BRIDGE: &str = include_str!("../suite_worker.py");
struct Capabilities {
    entries: BTreeMap<String, Value>,
    provider_gaps: Value,
}
static CAPABILITIES: OnceLock<Mutex<BTreeMap<String, Arc<Capabilities>>>> = OnceLock::new();
fn mode_key(provider: &str, game: &str, mode: &str) -> String {
    serde_json::to_string(&[provider, game, mode]).expect("string tuple serializes")
}

pub fn supports(provider: &str, _game: &Game, _mode: &Mode) -> bool {
    matches!(
        provider,
        "nolimit"
            | "elk"
            | "pragmatic"
            | "reelkingdom"
            | "endorphina"
            | "hacksaw"
            | "threeoaks"
            | "habanero"
            | "playngo"
            | "ela-games"
            | "amigogaming"
            | "peterandsons"
            | "thunderspin"
            | "bgaming"
            | "netent"
            | "playson"
            | "rubyplay"
            | "1spin4win"
            | "egt-digital"
            | "irondog"
            | "smartsoft"
            | "spinomenal"
            | "betsoft"
            | "playtech"
            | "evoplay"
            | "mascot"
            | "yggdrasil"
            | "kagaming"
            | "belatra"
            | "redtiger"
            | "amusnet"
    )
}

/// Exact collection_catalog.EXTRAS precedence and published MIN_INTERVALS.
pub fn min_interval_seconds(provider: &str) -> u64 {
    match provider {
        "kendoo" => 120,
        "bgaming" => 60,
        "kagaming" | "peterandsons" => 40,
        "netent" => 20,
        "evoplay" => 15,
        "amigogaming" | "thunderspin" | "belatra" => 10,
        "yggdrasil" => 4,
        "microgaming" | "hardfire-kalamba" => 3,
        "1spin4win" | "betsoft" | "egt-digital" | "habanero" | "irondog" | "mascot" | "playson"
        | "redtiger" | "rubyplay" | "smartsoft" | "spinomenal" => 1,
        _ => 0,
    }
}

static RELAY_PREFLIGHT: OnceLock<bool> = OnceLock::new();
fn relay_available() -> bool {
    let relay: SocketAddr = "127.0.0.1:8793".parse().expect("fixed loopback address");
    TcpStream::connect_timeout(&relay, Duration::from_millis(250)).is_ok()
}
fn isolated_command(program: &str) -> Command {
    #[cfg(unix)]
    {
        let mut command = Command::new(program);
        command.process_group(0);
        command
    }
    #[cfg(not(unix))]
    {
        Command::new(program)
    }
}
struct ProcessTree {
    pid: u32,
    armed: bool,
}
impl ProcessTree {
    fn terminate(&mut self) -> Result<()> {
        if !self.armed {
            return Ok(());
        }
        #[cfg(unix)]
        {
            unsafe extern "C" {
                fn kill(pid: i32, signal: i32) -> i32;
            }
            // The child creates its own process group before exec. A negative
            // pid addresses all descendants that inherit that reviewed group.
            let result = unsafe { kill(-(self.pid as i32), 9) };
            if result != 0 {
                let error = std::io::Error::last_os_error();
                // ESRCH means the complete process group has already exited.
                if error.raw_os_error() != Some(3) {
                    return Err(error.into());
                }
            }
        }
        #[cfg(windows)]
        {
            let status = std::process::Command::new("taskkill")
                .args(["/PID", &self.pid.to_string(), "/T", "/F"])
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .status()
                .context("suite process-tree termination unavailable")?;
            // 128: the process has already exited. Other failures retain the
            // guard and the uncertain native attempt for explicit owner review.
            ensure!(
                status.success() || status.code() == Some(128),
                "suite process-tree termination failed"
            );
        }
        self.armed = false;
        Ok(())
    }
}
impl Drop for ProcessTree {
    fn drop(&mut self) {
        let _ = self.terminate();
    }
}

fn bounded_preflight(
    root: &Path,
    python: &str,
) -> Result<(std::process::ExitStatus, Vec<u8>, Vec<u8>)> {
    let mut child = std::process::Command::new(python)
        .args(["-B", "-c", BRIDGE, "--capabilities", "--suite-root"])
        .arg(root)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .context("suite Python preflight could not start")?;
    let too_large = Arc::new(AtomicBool::new(false));
    fn read_limited(
        reader: impl Read,
        limit: u64,
        flag: Arc<AtomicBool>,
    ) -> std::io::Result<Vec<u8>> {
        let mut bytes = Vec::new();
        reader.take(limit + 1).read_to_end(&mut bytes)?;
        if bytes.len() as u64 > limit {
            flag.store(true, Ordering::Release);
        }
        Ok(bytes)
    }
    let stdout = child
        .stdout
        .take()
        .context("suite preflight stdout missing")?;
    let stderr = child
        .stderr
        .take()
        .context("suite preflight stderr missing")?;
    let flag = too_large.clone();
    let out = std::thread::spawn(move || read_limited(stdout, 64 * 1024 * 1024, flag));
    let flag = too_large.clone();
    let err = std::thread::spawn(move || read_limited(stderr, 1024 * 1024, flag));
    let deadline = Instant::now() + Duration::from_secs(60);
    let mut interrupted = false;
    let status = loop {
        if let Some(status) = child.try_wait()? {
            break status;
        }
        if too_large.load(Ordering::Acquire) || Instant::now() >= deadline {
            interrupted = true;
            let _ = child.kill();
            break child.wait()?;
        }
        std::thread::sleep(Duration::from_millis(20));
    };
    let stdout = out
        .join()
        .map_err(|_| anyhow::anyhow!("suite preflight stdout reader failed"))??;
    let stderr = err
        .join()
        .map_err(|_| anyhow::anyhow!("suite preflight stderr reader failed"))??;
    ensure!(
        !interrupted && !too_large.load(Ordering::Acquire),
        "suite offline preflight timeout or output limit; no provider dispatch"
    );
    Ok((status, stdout, stderr))
}

fn setting<'a>(settings: &'a Value, key: &str) -> Result<&'a str> {
    settings
        .get(key)
        .and_then(Value::as_str)
        .filter(|v| !v.trim().is_empty())
        .with_context(|| format!("suite requires explicit {key} setting"))
}
fn configuration(settings: &Value) -> Result<(PathBuf, String)> {
    ensure!(
        settings["executor"] == "suite",
        "explicit executor=suite required"
    );
    let root = PathBuf::from(setting(settings, "suite_root")?);
    ensure!(
        root.is_absolute(),
        "suite_root must be an absolute local directory"
    );
    let root = root.canonicalize().context("suite_root unavailable")?;
    ensure!(
        root.join("bet-collector/collection_worker.py").is_file(),
        "suite collection_worker.py missing"
    );
    Ok((root, setting(settings, "python")?.to_owned()))
}
fn identity(mode: &Mode) -> Value {
    json!({"key":mode.key,"type":mode.kind.as_str(),
           "requires_prerequisites":mode.requires_prerequisites,"execution_source":mode.execution_source})
}
fn capabilities(root: &Path, python: &str) -> Result<Arc<Capabilities>> {
    let key = format!("{}\n{python}", root.display());
    let mut cache = CAPABILITIES
        .get_or_init(|| Mutex::new(BTreeMap::new()))
        .lock()
        .map_err(|_| anyhow::anyhow!("suite capability cache poisoned"))?;
    if let Some(value) = cache.get(&key) {
        return Ok(value.clone());
    }
    // This branch is offline: Python's audit hook rejects network and subprocess
    // dispatch while loading the existing catalog. One process for the entire
    // catalog, not one process per mode. Execution rechecks the exact binding.
    let (status, stdout, stderr) = bounded_preflight(root, python)?;
    ensure!(
        status.success(),
        "suite offline preflight failed: {}",
        String::from_utf8_lossy(&stderr)
    );
    let value: Value =
        serde_json::from_slice(&stdout).context("suite invalid capability manifest")?;
    ensure!(
        value["schema_version"] == 1,
        "suite capability schema mismatch"
    );
    let mut entries = BTreeMap::new();
    for entry in value["entries"]
        .as_array()
        .context("suite entries missing")?
    {
        let entry_key = mode_key(
            entry["provider"]
                .as_str()
                .context("suite provider missing")?,
            entry["game"].as_str().context("suite game missing")?,
            entry["mode"]["key"]
                .as_str()
                .context("suite mode missing")?,
        );
        entries
            .entry(entry_key)
            .and_modify(|existing: &mut Value| *existing = Value::Null)
            .or_insert_with(|| entry.clone());
    }
    let result = Arc::new(Capabilities {
        entries,
        provider_gaps: value["provider_gaps"].clone(),
    });
    cache.insert(key, result.clone());
    Ok(result)
}
fn entry(provider: &str, game: &Game, mode: &Mode, settings: &Value) -> Result<Value> {
    ensure!(
        supports(provider, game, mode),
        "suite provider contract unavailable"
    );
    let (root, python) = configuration(settings)?;
    let manifest = capabilities(&root, &python)?;
    if let Some(gaps) = manifest.provider_gaps.get(provider) {
        bail!("suite local prerequisites unavailable: {gaps}");
    }
    let selected = manifest
        .entries
        .get(&mode_key(provider, &game.id, &mode.key))
        .filter(|value| !value.is_null())
        .context("suite inventory mode missing or ambiguous")?;
    ensure!(
        selected["mode"] == identity(mode),
        "suite mode kind/prerequisites/execution_source differ from pinned inventory"
    );
    ensure!(
        selected["gaps"].as_array().is_some_and(Vec::is_empty),
        "suite mode prerequisites unavailable: {}",
        selected["gaps"]
    );
    Ok(selected.clone())
}

pub fn preflight(provider: &str, game: &Game, mode: &Mode, settings: &Value) -> Result<()> {
    let selected = entry(provider, game, mode, settings)?;
    let budget = settings
        .get("max_prerequisite_rounds")
        .map(|v| v.as_u64().context("invalid suite prerequisite budget"))
        .transpose()?
        .unwrap_or(0);
    ensure!(budget <= 100, "suite prerequisite limit exceeds 100");
    let prerequisites = &mode.requires_prerequisites;
    let required = !(prerequisites.is_null()
        || prerequisites == false
        || prerequisites.as_array().is_some_and(Vec::is_empty)
        || prerequisites
            .as_object()
            .is_some_and(|object| object.is_empty()));
    ensure!(
        !required || budget > 0,
        "suite prerequisite budget required"
    );
    let binding = &selected["monetary_binding"];
    ensure!(
        settings["currency"]
            .as_str()
            .is_some_and(|s| !s.trim().is_empty())
            || binding["currency"]
                .as_str()
                .is_some_and(|s| !s.trim().is_empty())
            || binding["native_currency"] == true,
        "suite native currency binding unavailable; explicit currency required"
    );
    let unit = settings["monetary_unit"]
        .as_str()
        .or(binding["monetary_unit"].as_str());
    ensure!(
        matches!(unit, Some("major" | "native")),
        "suite native monetary unit binding unavailable"
    );
    // Connect only to the explicitly reviewed local relay; no provider request.
    ensure!(
        provider == "redtiger" || *RELAY_PREFLIGHT.get_or_init(relay_available),
        "suite local transport prerequisite missing: HTTP relay 127.0.0.1:8793"
    );
    let seconds = settings
        .get("suite_timeout_seconds")
        .map(|v| v.as_u64().context("invalid suite timeout"))
        .transpose()?
        .unwrap_or(1200);
    ensure!(
        (1..=1200).contains(&seconds),
        "suite timeout must be 1..1200 seconds"
    );
    Ok(())
}

fn write_new(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}
fn log_receipt(path: &Path) -> Result<Value> {
    OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)?
        .sync_all()?;
    let bytes = fs::read(path)?;
    Ok(json!({"path":path,"sha256":sha256(&bytes),"bytes":bytes.len()}))
}
async fn capture_log(mut reader: impl AsyncRead + Unpin, path: &Path) -> Result<()> {
    const LIMIT: usize = 16 * 1024 * 1024;
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    let mut total = 0;
    let mut buffer = [0u8; 8192];
    loop {
        let count = reader.read(&mut buffer).await?;
        if count == 0 {
            file.sync_all()?;
            return Ok(());
        }
        let retained = count.min(LIMIT - total);
        file.write_all(&buffer[..retained])?;
        total += retained;
        if retained < count {
            file.sync_all()?;
            bail!("suite process log exceeds 16 MiB; retained prefix, acceptance uncertain");
        }
    }
}

fn provider_failure(result: &Value) -> Option<Value> {
    if result["blocked"] != true {
        return None;
    }
    let reason = result["reason"].as_str()?;
    let (stage, status, financial_intent) = if result["status"] == "not_sent"
        && result["phase"] == "bootstrap"
        && result["financial_intent"] == false
    {
        (
            "suite_demo_bootstrap",
            reason.strip_prefix("remote_demo_bootstrap_http_")?,
            Some(false),
        )
    } else {
        (
            "suite_provider_request",
            reason.strip_prefix("remote_http_")?,
            result["financial_intent"].as_bool().filter(|sent| *sent),
        )
    };
    let status = match status {
        "403" => 403,
        "429" => 429,
        "503" => 503,
        _ => return None,
    };
    let mut failure =
        json!({"stage":stage,"http_status":status,"financial_intent":financial_intent});
    if status == 403 && result["browser_challenge"] == true {
        failure["browser_challenge"] = json!(true);
    }
    Some(failure)
}

pub async fn execute(
    ctx: &RunContext,
    provider: &str,
    game: &Game,
    mode: &Mode,
    settings: &Value,
) -> Result<RoundOutcome> {
    preflight(provider, game, mode, settings)?;
    ensure!(
        provider == "redtiger" || relay_available(),
        "suite local transport prerequisite missing: HTTP relay 127.0.0.1:8793"
    );
    if let Some(reason) = ctx.store.provider_hold(provider)? {
        bail!("provider has retained hold: {reason}");
    }
    let selected = entry(provider, game, mode, settings)?;
    let (root, python) = configuration(settings)?;
    let base = ctx.store.root().join("suite-attempts");
    fs::create_dir_all(&base)?;
    let folder = base.join(&ctx.round_id);
    fs::create_dir(&folder).context("suite attempt exists; replay forbidden")?;
    let bridge = folder.join("suite_worker.py");
    write_new(&bridge, BRIDGE.as_bytes())?;
    let mut request = json!({"provider":provider,"game":game.id,"mode":identity(mode),
        "binding_sha256":selected["binding_sha256"],
        "max_prerequisite_rounds":settings.get("max_prerequisite_rounds").cloned().unwrap_or(json!(0))});
    for key in ["currency", "currency_source", "monetary_unit"] {
        if let Some(value) = settings
            .get(key)
            .or_else(|| selected["monetary_binding"].get(key))
        {
            request[key] = value.clone();
        }
    }
    write_new(
        &folder.join("bridge-request.json"),
        &serde_json::to_vec(&request)?,
    )?;
    ctx.save_session(&json!({"transport":"suite_process","attempt_id":ctx.round_id,
        "owner_evidence_directory":folder,"native_owner_policy":"worker journal retains actual owner; never replaced",
        "binding_sha256":selected["binding_sha256"],"bridge_sha256":sha256(BRIDGE.as_bytes())}))?;
    let args = vec![
        "-B".to_owned(),
        bridge.to_string_lossy().into_owned(),
        "--suite-root".into(),
        root.to_string_lossy().into_owned(),
        "--attempt".into(),
        folder.to_string_lossy().into_owned(),
    ];
    let intent = WireRequest {
        label: "suite_worker_dispatch".into(),
        transport: "process".into(),
        method: "EXEC".into(),
        url: python.clone(),
        headers: BTreeMap::new(),
        body: serde_json::to_string(&json!({"argv":args,"cwd":folder}))?,
        financial: true,
    };
    // Conservative financial boundary precedes spawning any code that may send.
    let ordinal = ctx.store.start_exchange(&ctx.round_id, &intent)?;
    let stdout_path = folder.join("bridge.stdout.log");
    let stderr_path = folder.join("bridge.stderr.log");
    let operation: Result<_> = async {
        let mut child = isolated_command(&python)
            .args(&args)
            .current_dir(&folder)
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .env("EVIDENCIA_RUNNER_DATA", ctx.store.root())
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true)
            .spawn()
            .context("suite process spawn failed after durable intent")?;
        let mut tree = ProcessTree {
            pid: child.id().context("suite child process ID missing")?,
            armed: true,
        };
        let stdout = child.stdout.take().context("suite stdout missing")?;
        let stderr = child.stderr.take().context("suite stderr missing")?;
        let seconds = settings["suite_timeout_seconds"].as_u64().unwrap_or(1200);
        let completion = timeout(Duration::from_secs(seconds), async {
            tokio::try_join!(
                async { child.wait().await.context("suite child wait failed") },
                capture_log(stdout, &stdout_path),
                capture_log(stderr, &stderr_path)
            )
        })
        .await;
        match completion {
            Ok(Ok((status, (), ()))) => {
                tree.terminate()?;
                Ok((status, false))
            }
            Ok(Err(error)) => {
                tree.terminate()?;
                let _ = child.kill().await;
                let _ = child.wait().await;
                Err(error)
            }
            Err(_) => {
                tree.terminate()
                    .context("suite timed out; process-tree termination uncertain")?;
                let _ = child.kill().await;
                Ok((child.wait().await?, true))
            }
        }
    }
    .await;
    let result = match operation {
        Ok((status, timed_out)) => {
            let process = json!({"transport":"process","exit_code":status.code(),"success":status.success(),
                "timed_out":timed_out,"stdout":log_receipt(&stdout_path)?,"stderr":log_receipt(&stderr_path)?,
                "owner_evidence_directory":folder});
            // Received process completion is a process frame, never an HTTP 200.
            ctx.store.append_frame(
                &ctx.round_id,
                ordinal,
                "process_result",
                &serde_json::to_string(&process)?,
            )?;
            if timed_out || !status.success() {
                let failure = (!timed_out)
                    .then(|| fs::read(folder.join("result.json")).ok())
                    .flatten()
                    .and_then(|bytes| serde_json::from_slice(&bytes).ok())
                    .and_then(|value| provider_failure(&value));
                let reason = if let Some(failure) = failure {
                    ctx.store.append_frame(
                        &ctx.round_id,
                        ordinal,
                        "suite_provider_failure",
                        &failure.to_string(),
                    )?;
                    let stage = failure["stage"].as_str().unwrap();
                    let status = &failure["http_status"];
                    if failure["browser_challenge"] == true {
                        format!(
                            "HTTP {status} at {stage}: provider-declared browser challenge; operator review required"
                        )
                    } else {
                        format!("HTTP {status} at {stage}; operator review required")
                    }
                } else {
                    "suite process failed or timed out; financial acceptance uncertain; do not replay".into()
                };
                ctx.store.fail_exchange(&ctx.round_id, ordinal, &reason)?;
                ctx.store.hold_provider(provider, &reason)?;
                bail!("{reason}; native evidence retained in {}", folder.display());
            }
            // status is the OS exit code; the transport marker prevents it being
            // mistaken for an HTTP status. Full logs remain in immutable files.
            ctx.store.finish_exchange(
                &ctx.round_id,
                ordinal,
                &WireResponse {
                    status: 0,
                    headers: BTreeMap::from([("x-evidencia-transport".into(), "process".into())]),
                    body: serde_json::to_string(&process)?,
                    set_cookies: vec![],
                },
            )?;
            process
        }
        Err(error) => {
            let process = json!({"transport":"process","error":format!("{error:#}"),
                "stdout":log_receipt(&stdout_path).ok(),"stderr":log_receipt(&stderr_path).ok(),
                "owner_evidence_directory":folder});
            ctx.store.append_frame(
                &ctx.round_id,
                ordinal,
                "process_result",
                &serde_json::to_string(&process)?,
            )?;
            ctx.store
                .fail_exchange(&ctx.round_id, ordinal, &format!("{error:#}"))?;
            ctx.store.hold_provider(
                provider,
                "suite process interrupted; financial acceptance uncertain",
            )?;
            return Err(error);
        }
    };
    let bytes = fs::read(folder.join("bridge-outcome.json"))
        .context("suite native outcome missing; retained attempt requires review")?;
    let mut outcome: RoundOutcome =
        serde_json::from_slice(&bytes).context("suite native outcome invalid")?;
    outcome.native_data["process_receipt"] = result;
    // Engine runs the same verification again before changing terminal status.
    outcome.verify()?;
    Ok(outcome)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reports_native_http_rejection_without_reclassifying_unknown_intent() {
        let challenge = provider_failure(&json!({"status":"not_sent","blocked":true,
            "reason":"remote_demo_bootstrap_http_403","phase":"bootstrap","financial_intent":false,
            "browser_challenge":true}))
        .unwrap();
        let event: crate::engine::RoundEventError = serde_json::from_value(challenge).unwrap();
        assert!(event.browser_challenge);
        assert_eq!(event.http_status, Some(403));
        assert_eq!(event.financial_intent, Some(false));
        assert_eq!(
            provider_failure(&json!({"status":"not_sent","blocked":true,
            "reason":"remote_demo_bootstrap_http_403","phase":"bootstrap","financial_intent":false})),
            Some(
                json!({"stage":"suite_demo_bootstrap","http_status":403,"financial_intent":false})
            )
        );
        assert_eq!(
            provider_failure(
                &json!({"status":"needs_review","blocked":true,"reason":"remote_http_429"})
            ),
            Some(
                json!({"stage":"suite_provider_request","http_status":429,"financial_intent":null})
            )
        );
        assert!(
            provider_failure(&json!({"status":"not_sent","blocked":true,
            "reason":"remote_demo_bootstrap_http_403","phase":"bootstrap","financial_intent":true}))
            .is_none()
        );
        assert!(
            provider_failure(
                &json!({"status":"needs_review","blocked":true,"reason":"HTTP 403 at private URL"})
            )
            .is_none()
        );
    }

    #[tokio::test]
    async fn timeout_kills_descendant_before_it_can_write_marker() {
        let temporary = tempfile::tempdir().unwrap();
        let marker = temporary.path().join("descendant-marker");
        let ready = temporary.path().join("descendant-ready");
        let python = if cfg!(windows) { "python" } else { "python3" };
        let script = r#"import subprocess,sys,time
from pathlib import Path
subprocess.Popen([sys.executable,'-c','import sys,time;from pathlib import Path;time.sleep(2);Path(sys.argv[1]).write_text("unsafe")',sys.argv[1]])
Path(sys.argv[2]).write_text('ready')
time.sleep(30)
"#;
        let mut child = isolated_command(python)
            .args(["-B", "-c", script])
            .arg(&marker)
            .arg(&ready)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .kill_on_drop(true)
            .spawn()
            .unwrap();
        let mut guard = ProcessTree {
            pid: child.id().unwrap(),
            armed: true,
        };
        let start = Instant::now();
        while !ready.exists() && start.elapsed() < Duration::from_secs(5) {
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
        assert!(ready.exists(), "synthetic descendant did not start");
        assert!(
            timeout(Duration::from_millis(50), child.wait())
                .await
                .is_err()
        );
        guard.terminate().unwrap();
        let _ = child.wait().await;
        tokio::time::sleep(Duration::from_millis(2300)).await;
        assert!(!marker.exists(), "descendant survived worker termination");
    }
    #[test]
    fn provider_intervals_preserve_catalog_precedence() {
        assert_eq!(min_interval_seconds("kagaming"), 40);
        assert_eq!(min_interval_seconds("bgaming"), 60);
        assert_eq!(min_interval_seconds("evoplay"), 15);
        assert_eq!(
            min_interval_seconds("reelkingdom"),
            min_interval_seconds("pragmatic")
        );
    }
}
