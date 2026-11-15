#[path = "../portable_journal.rs"]
mod portable_journal;

use serde_json::{Value, json};
use std::{env, process::ExitCode};

const INVENTORY: &[u8] =
    include_bytes!("../../../../docs/recolector/inventario/smartsoft.json");

fn main() -> ExitCode {
    let args: Vec<_> = env::args().skip(1).collect();
    match execute(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("{error}");
            ExitCode::FAILURE
        }
    }
}

fn execute(args: &[String]) -> Result<(), String> {
    let catalog: Value = serde_json::from_slice(INVENTORY).map_err(|e| e.to_string())?;
    if args == ["games"] {
        println!("{catalog}");
        return Ok(());
    }
    let [command, game, mode] = args else {
        return Err("smartsoft games | check|run <juego> <modalidad>".into());
    };
    let known = catalog["games"]
        .as_array()
        .and_then(|games| {
            games
                .iter()
                .find(|g| g["id"] == *game && g["ready"] == true)
        })
        .and_then(|g| g["modes"].as_array())
        .is_some_and(|modes| {
            modes
                .iter()
                .any(|m| m["key"] == *mode && m["ready"] != false)
        });
    if !known {
        return Err("Juego o modalidad fuera del inventario revisado".into());
    }
    let (option, value) = match mode.split_once(':') {
        None if mode == "normal" => ("Start", None),
        Some((option @ ("RiskBet" | "PurchaseBonus"), value)) => {
            let value = if value == "None" && option == "RiskBet" {
                None
            } else {
                Some(
                    value
                        .parse::<u64>()
                        .map_err(|_| "Selector SmartSoft inválido")?,
                )
            };
            (option, value)
        }
        _ => return Err("Modalidad SmartSoft pendiente".into()),
    };
    let case = json!({"provider":"smartsoft","execution_source":"native_remote","game":{"code":game},
        "mode":{"key":mode,"spec":{"option":option,"value":value}}});
    match command.as_str() {
        "check" => {
            println!(
                "{}",
                json!({"provider":"smartsoft","game":game,"mode":mode,"network_requests":0})
            );
            Ok(())
        }
        "run" => portable_journal::run("smartsoft", |journal| {
            game_runner::smartsoft::run_case(&case, journal)
        }),
        _ => Err("Usá games, check o run".into()),
    }
}
