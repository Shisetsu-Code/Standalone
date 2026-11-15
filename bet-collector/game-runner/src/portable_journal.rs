use serde_json::Value;
use std::{
    env, fs,
    path::{Path, PathBuf},
};

pub fn run(
    provider: &str,
    run_case: impl FnOnce(&Path) -> Result<Value, String>,
) -> Result<(), String> {
    let root = PathBuf::from(env::var_os("LOCALAPPDATA").ok_or("LOCALAPPDATA no disponible")?)
        .join("Evidencia")
        .join("DemoRunners")
        .join(provider);
    fs::create_dir_all(&root).map_err(|e| e.to_string())?;
    let attempt = uuid::Uuid::new_v4().to_string();
    let journal = root.join(format!("{attempt}.jsonl"));
    let marker = root.join("pending-round");
    use std::io::Write;
    let mut hold = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&marker)
        .map_err(|e| format!("No se pudo reservar la ejecuciÃ³n; revisar el estado local: {e}"))?;
    writeln!(hold, "{attempt}")
        .and_then(|_| hold.sync_all())
        .map_err(|e| e.to_string())?;
    drop(hold);
    let result = run_case(&journal);
    // The adapter writes this event durably before each potentially paid command.
    let evidence = fs::read_to_string(&journal).map_err(|e| e.to_string())?;
    let rows = evidence
        .lines()
        .map(serde_json::from_str::<Value>)
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| e.to_string())?;
    let dispatched = rows.iter().any(|row| row["event"] == "sending");
    if !dispatched
        || (result
            .as_ref()
            .is_ok_and(|outcome| outcome["closed"] == true && outcome["wallet_check"] == "match")
            && rows.last().is_some_and(|row| row["event"] == "audit"))
    {
        fs::remove_file(marker).map_err(|e| e.to_string())?;
    }
    let outcome = result?;
    println!(
        "{}",
        serde_json::to_string_pretty(&outcome).map_err(|e| e.to_string())?
    );
    Ok(())
}
