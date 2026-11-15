#[path = "../portable_journal.rs"]
mod portable_journal;

use serde_json::{Value, json};
use std::{env, process::ExitCode};

const INVENTORY: &[u8] = include_bytes!(
    "../../../../docs/recolector/inventario/threeoaks.json"
);
const SERIALIZERS: &[u8] =
    include_bytes!("../../../../demo-dashboard/threeoaks/reference/serializer-bindings.json");
const CONTINUATIONS: &[u8] =
    include_bytes!("../../../../demo-dashboard/threeoaks/reference/continuation-bindings.json");
const LUCKY_PENNY: &[u8] =
    include_bytes!("../../../../demo-dashboard/threeoaks/reference/lucky_penny_2.client.js");

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
        return Err("threeoaks games | check|run <juego> <modalidad>".into());
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
            modes.iter().any(|m| {
                m["key"] == *mode
                    && m["ready"] != false
                    && matches!(
                        m["type"].as_str(),
                        Some("normal" | "purchase" | "booster" | "antebet")
                    )
            })
        });
    if !known {
        return Err("Juego o modalidad fuera del inventario revisado".into());
    }
    if command == "check" {
        println!(
            "{}",
            json!({"provider":"threeoaks","game":game,"mode":mode,"network_requests":0})
        );
        return Ok(());
    }
    if command != "run" {
        return Err("Usa games, check o run".into());
    }
    let serializers = serde_json::from_slice(SERIALIZERS).map_err(|e| e.to_string())?;
    let continuations = serde_json::from_slice(CONTINUATIONS).map_err(|e| e.to_string())?;
    let case = json!({"provider":"threeoaks","execution_source":"native_remote",
                      "game":{"id":game},"mode":{"spec":{"native_key":mode}}});
    portable_journal::run("threeoaks", |journal| {
        game_runner::threeoaks::run_with_bindings(
            &case,
            journal,
            &serializers,
            &continuations,
            |path| {
                if path == "threeoaks/reference/lucky_penny_2.client.js" {
                    Ok(LUCKY_PENNY.to_vec())
                } else {
                    Err("Referencia 3 Oaks ausente".into())
                }
            },
        )
    })
}
