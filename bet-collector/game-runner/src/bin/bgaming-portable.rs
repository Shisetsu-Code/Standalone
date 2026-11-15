#[path = "../portable_journal.rs"]
mod portable_journal;

use serde_json::json;
use std::{env, process::ExitCode};

const INVENTORY: &[u8] =
    include_bytes!("../../../../docs/recolector/inventario/bgaming.json");

fn main() -> ExitCode {
    match execute() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("{error}");
            ExitCode::FAILURE
        }
    }
}

fn execute() -> Result<(), String> {
    let args: Vec<_> = env::args().skip(1).collect();
    if args == ["games"] {
        let catalog: serde_json::Value =
            serde_json::from_slice(INVENTORY).map_err(|error| error.to_string())?;
        println!("{catalog}");
        return Ok(());
    }
    let [command, game, mode] = args.as_slice() else {
        return Err("bgaming games | check|run <juego> <modalidad>".into());
    };
    let case = json!({"provider":"bgaming","execution_source":"native_remote",
                      "game":{"game_id":game},"mode":{"key":mode}});
    if !game_runner::bgaming::supports_case(&case) {
        return Err("Juego o modalidad fuera del contrato revisado".into());
    }
    if command == "check" {
        println!(
            "{}",
            json!({"provider":"bgaming","game":game,"mode":mode,"network_requests":0})
        );
        return Ok(());
    }
    if command != "run" {
        return Err("UsÃ¡ check o run".into());
    }
    portable_journal::run("bgaming", |journal| {
        game_runner::bgaming::run_case(&case, journal)
    })
}
