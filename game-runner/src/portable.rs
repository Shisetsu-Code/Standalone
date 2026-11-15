use crate::{adapters, bindings, engine, export, model::*, store::Store};
use anyhow::{Context, Result, ensure};
use clap::{Parser, Subcommand};
use serde_json::{Value, json};
use std::{
    path::PathBuf,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
};
use uuid::Uuid;

#[derive(Parser)]
struct Cli {
    #[arg(long, global = true)]
    data: Option<PathBuf>,
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Show the embedded games and their declared modes.
    Games,
    /// Check a game and mode locally.
    Check {
        game: String,
        mode: String,
        #[arg(long, default_value_t = 0, value_parser = clap::value_parser!(u32).range(0..=100))]
        max_prerequisite_rounds: u32,
    },
    /// Check the official public demo launch without opening a round.
    ProbeLaunch {
        game: String,
        /// Use the alternate public Playin demo issuer for NetEnt Starburst.
        #[arg(long)]
        playin: bool,
    },
    /// Audit a saved GECO initialization and terminal response without connecting to NetEnt.
    #[command(hide = true)]
    AuditGeco {
        initial: PathBuf,
        terminal: PathBuf,
        currency: String,
    },
    /// Audit the native closure of a recorded Iron Dog Morphic round offline.
    AuditIronDog { round_id: String },
    /// Show saved rounds and HTTP status codes, without session data.
    Status,
    /// Execute one public demo sample and record the native settlement.
    Run {
        game: String,
        mode: String,
        #[arg(long, default_value_t = 0, value_parser = clap::value_parser!(u32).range(0..=100))]
        max_prerequisite_rounds: u32,
    },
}

pub async fn entry(provider: &'static str, inventory: &'static [u8]) -> std::process::ExitCode {
    let cli = Cli::parse();
    match execute(provider, inventory, cli).await {
        Ok(true) => std::process::ExitCode::SUCCESS,
        Ok(false) => std::process::ExitCode::from(2),
        Err(err) => {
            eprintln!("Error: {err:#}");
            std::process::ExitCode::FAILURE
        }
    }
}

async fn execute(provider: &str, inventory: &[u8], cli: Cli) -> Result<bool> {
    let catalog: ProviderInventory = serde_json::from_slice(inventory)?;
    ensure!(
        catalog.id == provider,
        "embedded catalogue identity mismatch"
    );
    let (game, mode, run, budget) = match cli.command {
        Command::Games => {
            println!("{}", serde_json::to_string_pretty(&catalog)?);
            return Ok(true);
        }
        Command::Check {
            game,
            mode,
            max_prerequisite_rounds,
        } => (game, mode, false, max_prerequisite_rounds),
        Command::ProbeLaunch { game, playin } => {
            ensure!(
                catalog.games.iter().any(|entry| entry.id == game),
                "game absent from the embedded catalogue"
            );
            return match provider {
                "netent" if playin => adapters::netent_launch::probe_playin(&game).await,
                "netent" => adapters::netent_launch::probe(&game).await,
                "rubyplay" if !playin => adapters::rubyplay::probe(&game).await,
                _ => anyhow::bail!("launch probe unavailable for this provider"),
            };
        }
        Command::AuditGeco {
            initial,
            terminal,
            currency,
        } => {
            ensure!(provider == "netent", "GECO audit is available for NetEnt");
            let before = adapters::netent_geco::fields(&std::fs::read_to_string(initial)?)?;
            let after = adapters::netent_geco::fields(&std::fs::read_to_string(terminal)?)?;
            let outcome = adapters::netent_geco::reconcile(&before, &after, &currency)?;
            println!(
                "{}",
                json!({"currency": outcome.currency,"balance_before":outcome.balance_before,
                    "balance_after":outcome.balance_after,"cost":outcome.cost,"payout":outcome.payout,
                    "native_closed":outcome.native_closed,"native_data":outcome.native_data,"network_requests":0})
            );
            return Ok(true);
        }
        Command::AuditIronDog { round_id } => {
            ensure!(
                provider == "irondog",
                "Iron Dog audit is available for Iron Dog"
            );
            let data = data_path(cli.data)?;
            ensure!(
                data.join("runner.sqlite3").is_file(),
                "No recorded runs in {}",
                data.display()
            );
            let receipt = adapters::irondog::audit_saved_round(&Store::open(data)?, &round_id)?;
            println!("{}", json!({"receipt":receipt,"network_requests":0}));
            return Ok(receipt.wallet_matches == Some(true));
        }
        Command::Status => {
            let data = data_path(cli.data)?;
            ensure!(
                data.join("runner.sqlite3").is_file(),
                "No recorded runs in {}",
                data.display()
            );
            let store = Store::open(data)?;
            let mut rounds = Vec::new();
            for round in store
                .rounds()?
                .iter()
                .filter(|round| round.spec.provider == provider)
            {
                let exchanges = store.exchanges(&round.id)?;
                let stages: Vec<_> = exchanges
                    .iter()
                    .map(|exchange| {
                        json!({
                            "stage": exchange.request.label,
                            "transport": exchange.request.transport,
                            "status": exchange.response.as_ref().map(|response| response.status),
                            "financial": exchange.request.financial,
                        })
                    })
                    .collect();
                rounds
                    .push(json!({"receipt":export::public_receipt(&store, round),"stages":stages}));
            }
            println!(
                "{}",
                serde_json::to_string_pretty(&json!({"provider":provider,"rounds":rounds}))?
            );
            return Ok(true);
        }
        Command::Run {
            game,
            mode,
            max_prerequisite_rounds,
        } => (game, mode, true, max_prerequisite_rounds),
    };
    let snapshot = InventorySnapshot {
        id: sha256(inventory),
        providers: vec![catalog],
        sources: vec![InventorySource {
            provider: provider.to_owned(),
            path: format!("embedded/{provider}.json"),
            actual_sha256: sha256(inventory),
            declared_sha256: sha256(inventory),
            hash_representation: "exact".into(),
        }],
    };
    let options = engine::RunOptions::default();
    let plan = validated_plan_with_budget(&snapshot, provider, &game, &mode, budget)?;
    if !run {
        println!(
            "{}",
            json!({"provider":provider,"job":plan.jobs[0],"network_requests":0})
        );
        return Ok(true);
    }
    let data = data_path(cli.data)?;
    let store = Store::open(&data)?;
    store.cache_inventory(&snapshot)?;
    let cancel = Arc::new(AtomicBool::new(false));
    let flag = cancel.clone();
    let signal = tokio::spawn(async move {
        if tokio::signal::ctrl_c().await.is_ok() {
            flag.store(true, Ordering::Release);
        }
    });
    let report = engine::run(
        store.clone(),
        plan,
        options,
        Arc::new(adapters::NativeExecutor),
        cancel,
        None,
    )
    .await;
    signal.abort();
    let report = report.context("campaign failed; inspect the retained local journal")?;
    let receipts: Vec<Value> = store
        .rounds()?
        .iter()
        .filter(|round| round.spec.campaign_id == report.campaign_id)
        .map(|round| export::public_receipt(&store, round))
        .collect();
    println!(
        "{}",
        serde_json::to_string_pretty(&json!({
            "campaign": report.campaign_id, "completed": report.completed,
            "status_counts": report.status_counts, "rounds": receipts
        }))?
    );
    Ok(report.completed)
}

pub fn validated_plan(
    snapshot: &InventorySnapshot,
    provider: &str,
    game: &str,
    mode: &str,
) -> Result<CampaignPlan> {
    validated_plan_with_budget(snapshot, provider, game, mode, 0)
}

fn validated_plan_with_budget(
    snapshot: &InventorySnapshot,
    provider: &str,
    game: &str,
    mode: &str,
    budget: u32,
) -> Result<CampaignPlan> {
    let (_, selected, _) = snapshot.lookup(provider, game, mode)?;
    let mut settings = bindings::embedded(provider, selected)?;
    if budget != 0 {
        ensure!(
            provider == "netent",
            "this runner does not accept a preparation budget"
        );
        settings["max_prerequisite_rounds"] = json!(budget);
    }
    let plan = CampaignPlan {
        schema_version: 1,
        id: Uuid::new_v4().to_string(),
        inventory_id: snapshot.id.clone(),
        jobs: vec![Job {
            provider: provider.to_owned(),
            game: game.to_owned(),
            mode: mode.to_owned(),
            settings,
            samples: 1,
        }],
        coverage: None,
    };
    engine::validate_plan(
        &plan,
        snapshot,
        &adapters::NativeExecutor,
        &engine::RunOptions::default(),
    )?;
    Ok(plan)
}

fn data_path(path: Option<PathBuf>) -> Result<PathBuf> {
    match path {
        Some(path) => Ok(path),
        None => Ok(std::env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .context("Specify --data for durable session storage")?
            .join("Evidencia")
            .join("DemoRunners")),
    }
}
