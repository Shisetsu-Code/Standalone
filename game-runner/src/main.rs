use anyhow::{Context, Result, bail, ensure};
use clap::{Parser, Subcommand};
use game_runner::{
    adapters, bindings, campaign,
    engine::{self, RunOptions},
    export::{self, ExportOptions},
    inventory,
    model::{CampaignPlan, Job, ModeKind},
    smoke,
    store::Store,
};
use serde::Serialize;
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    fs::{self, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
};
use tokio::sync::mpsc;
use uuid::Uuid;

#[derive(Parser)]
#[command(
    name = "game-runner",
    version,
    about = "Recolector durable de demos públicas; resultados experimentales"
)]
struct Cli {
    #[arg(
        long,
        global = true,
        env = "EVIDENCIA_RUNNER_DATA",
        default_value = "data"
    )]
    data: PathBuf,
    #[command(subcommand)]
    command: Command,
}
#[derive(Subcommand)]
enum Command {
    Import {
        #[arg(long, default_value = "../docs/recolector/inventario.json")]
        manifest: PathBuf,
    },
    Inventory {
        #[arg(long)]
        provider: Option<String>,
        #[arg(long)]
        game: Option<String>,
    },
    Capabilities,
    /// Audit each inventory mode against the standalone Rust planner without sending requests.
    StandaloneCoverage,
    /// Report every inventory provider; --execute permits one reviewed normal sample each.
    SmokeAll {
        #[arg(long)]
        campaign: String,
        #[arg(long)]
        output: PathBuf,
        #[arg(long, default_value = "..")]
        repo: PathBuf,
        #[arg(long)]
        execute: bool,
        /// Also require providers without executable bindings to be verified.
        #[arg(long)]
        require_all_providers: bool,
        #[arg(long, default_value_t = 4)]
        parallel_providers: usize,
        #[arg(long, default_value_t = 30)]
        timeout_seconds: u64,
        #[arg(long, default_value_t = 1000)]
        max_steps: usize,
    },
    Plan {
        #[arg(long)]
        provider: String,
        #[arg(long)]
        game: String,
        #[arg(long, required = true)]
        mode: Vec<String>,
        #[arg(long, default_value_t = 1)]
        samples: u32,
        #[arg(long)]
        output: PathBuf,
        #[arg(long, default_value = "..")]
        repo: PathBuf,
        #[arg(long)]
        settings: Option<PathBuf>,
        #[arg(long)]
        id: Option<String>,
    },
    /// Plan every declared mode and retain explicit gaps; never sends requests.
    PlanAll {
        #[arg(long)]
        provider: Vec<String>,
        #[arg(long)]
        game: Vec<String>,
        #[arg(long, default_value_t = 1)]
        samples: u32,
        #[arg(long)]
        output: PathBuf,
        #[arg(long, default_value = "..")]
        repo: PathBuf,
        /// Public settings keyed by provider, then game id (or *).
        #[arg(long)]
        settings: Option<PathBuf>,
        #[arg(long)]
        suite_root: Option<PathBuf>,
        #[arg(long)]
        python: Option<String>,
        #[arg(long, default_value_t = 0)]
        max_prerequisite_rounds: u32,
        #[arg(long)]
        id: Option<String>,
    },
    Coverage {
        #[arg(
            long,
            conflicts_with = "campaign",
            required_unless_present = "campaign"
        )]
        plan: Option<PathBuf>,
        #[arg(long)]
        campaign: Option<String>,
    },
    /// Retire a crashed bootstrap only when no financial intent exists.
    RecoverNonfinancial {
        round_id: String,
        #[arg(long)]
        reason: String,
    },
    Check {
        #[arg(long)]
        plan: PathBuf,
    },
    Run {
        #[arg(long)]
        plan: PathBuf,
        #[arg(long, default_value_t = 4)]
        parallel_providers: usize,
        #[arg(long, default_value_t = 45)]
        timeout_seconds: u64,
        #[arg(long, default_value_t = 3000)]
        max_steps: usize,
        #[arg(long)]
        relay: Option<String>,
    },
    Status {
        #[arg(long)]
        provider: Option<String>,
        #[arg(long)]
        game: Option<String>,
        #[arg(long)]
        campaign: Option<String>,
    },
    Show {
        round_id: String,
        #[arg(long)]
        private: bool,
        #[arg(long, requires = "private")]
        output: Option<PathBuf>,
    },
    Export {
        #[arg(long)]
        output: PathBuf,
        #[arg(long)]
        provider: Option<String>,
        #[arg(long)]
        game: Option<String>,
        #[arg(long)]
        kind: Option<String>,
        #[arg(long)]
        include_unverified: bool,
        #[arg(long)]
        include_wire: bool,
    },
    ReleaseHold {
        #[arg(long)]
        provider: String,
        #[arg(long)]
        reason: String,
    },
}
fn print_json<T: Serialize>(value: &T) -> Result<()> {
    println!("{}", serde_json::to_string_pretty(value)?);
    Ok(())
}
fn read_plan(path: &Path) -> Result<CampaignPlan> {
    serde_json::from_slice(&fs::read(path).context("cannot read plan")?)
        .context("invalid plan JSON")
}
fn new_output(path: &Path) -> Result<fs::File> {
    let mut o = OpenOptions::new();
    o.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        o.mode(0o600);
    }
    o.open(path)
        .context("cannot create new output; check destination and permissions")
}
fn finish_output(mut f: fs::File, value: &impl Serialize) -> Result<()> {
    serde_json::to_writer_pretty(&mut f, value)?;
    f.write_all(b"\n")?;
    f.sync_all()?;
    Ok(())
}
fn write_new(path: &Path, value: &impl Serialize) -> Result<()> {
    finish_output(new_output(path)?, value)
}
fn parse_kind(s: &str) -> Result<ModeKind> {
    match s {
        "normal" => Ok(ModeKind::Normal),
        "purchase" => Ok(ModeKind::Purchase),
        "antebet" => Ok(ModeKind::AnteBet),
        "booster" => Ok(ModeKind::Booster),
        "variant" => Ok(ModeKind::Variant),
        "special" => Ok(ModeKind::Special),
        _ => bail!("unknown mode type; use normal, purchase, antebet, booster, variant or special"),
    }
}
fn validate(store: &Store, plan: &CampaignPlan, options: &RunOptions) -> Result<()> {
    let inventory = store
        .inventory(Some(&plan.inventory_id))
        .context("pinned inventory has not been imported")?;
    engine::validate_plan(plan, &inventory, &adapters::NativeExecutor, options)
}

async fn execute(cli: Cli) -> Result<i32> {
    let store = Store::open(&cli.data).context("cannot open data directory")?;
    match cli.command {
        Command::Import { manifest } => {
            let snapshot = inventory::load_manifest(&manifest)?;
            store.install_inventory(&snapshot)?;
            let games: usize = snapshot.providers.iter().map(|p| p.games.len()).sum();
            let modes: usize = snapshot
                .providers
                .iter()
                .flat_map(|p| &p.games)
                .map(|g| g.modes.len())
                .sum();
            print_json(
                &json!({"inventory_id":snapshot.id,"providers":snapshot.providers.len(),"games":games,"modes":modes}),
            )?;
        }
        Command::Inventory { provider, game } => {
            let snapshot = store.inventory(None).context("import an inventory first")?;
            let providers:Vec<_>=snapshot.providers.iter().filter(|p|provider.as_ref().is_none_or(|v|v==&p.id)).map(|p|json!({"id":p.id,"name":p.name,"ready":p.ready,"campaign_eligible":p.campaign_eligible,"games":p.games.iter().filter(|g|game.as_ref().is_none_or(|v|v==&g.id)).map(|g|json!({"id":g.id,"name":g.name,"ready":g.ready,"modes":g.modes.iter().map(|m|json!({"key":m.key,"type":m.kind.as_str(),"ready":m.ready})).collect::<Vec<_>>()})).collect::<Vec<_>>()})).collect();
            print_json(&json!({"inventory_id":snapshot.id,"providers":providers}))?;
        }
        Command::Capabilities => print_json(&adapters::capabilities(
            &store.inventory(None).context("import an inventory first")?,
        ))?,
        Command::StandaloneCoverage => {
            let mut snapshot = store.inventory(None).context("import an inventory first")?;
            // This executable embeds a reviewed overlay for two Games Global modes.
            if let Some(provider) = snapshot
                .providers
                .iter_mut()
                .find(|p| p.id == "gamesglobal")
            {
                let portable: game_runner::model::ProviderInventory = serde_json::from_slice(
                    include_bytes!("../bindings/gamesglobal-inventory.json"),
                )?;
                for game in &mut provider.games {
                    if let Some(entry) = portable.games.iter().find(|g| g.id == game.id) {
                        if game.modes.is_empty() && !entry.modes.is_empty() {
                            *game = entry.clone();
                        }
                    }
                }
                provider.ready = portable.ready;
                provider.campaign_eligible = portable.campaign_eligible;
            }
            let providers = snapshot.providers.iter().map(|provider| {
                let separate = matches!(provider.id.as_str(), "bgaming" | "smartsoft" | "threeoaks");
                let games = provider.games.iter().map(|game| {
                    let modes = game.modes.iter().map(|mode| {
                        let (status, reason) = if separate {
                            ("separate_executable", None)
                        } else {
                            match game_runner::portable::validated_plan(&snapshot, &provider.id, &game.id, &mode.key) {
                                Ok(_) => ("runnable", None),
                                Err(error) => ("blocked", Some(format!("{error:#}"))),
                            }
                        };
                        json!({"key":mode.key,"type":mode.kind.as_str(),"status":status,"reason":reason})
                    }).collect::<Vec<_>>();
                    json!({"game":game.id,"name":game.name,"modes":modes})
                }).collect::<Vec<_>>();
                json!({"provider":provider.id,"games":games})
            }).collect::<Vec<_>>();
            print_json(
                &json!({"inventory_id":snapshot.id,"network_requests":0,"providers":providers}),
            )?;
        }
        Command::SmokeAll {
            campaign,
            output,
            repo,
            execute: execute_live,
            require_all_providers,
            parallel_providers,
            timeout_seconds,
            max_steps,
        } => {
            let existing = match store.campaign(&campaign) {
                Ok(plan) => Some(plan),
                Err(error)
                    if matches!(
                        error.downcast_ref::<rusqlite::Error>(),
                        Some(rusqlite::Error::QueryReturnedNoRows)
                    ) =>
                {
                    None
                }
                Err(error) => return Err(error.context("cannot inspect stored smoke campaign")),
            };
            let inventory = store
                .inventory(existing.as_ref().map(|plan| plan.inventory_id.as_str()))
                .context("import an inventory first")?;
            let mut prepared = smoke::prepare(&inventory, &repo, &campaign)?;
            if let Some(plan) = existing {
                ensure!(
                    serde_json::to_value(&prepared.plan)? == serde_json::to_value(&plan)?,
                    "stored smoke plan differs from reviewed selection"
                );
                prepared.plan = plan;
            }
            // Reserve the output before any network operation; an unwritable or
            // already-used destination must not consume another demo sample.
            let report_file = new_output(&output)?;
            let mut orchestration_failed = false;
            if execute_live && !prepared.plan.jobs.is_empty() {
                let options = RunOptions {
                    parallel_providers,
                    timeout_seconds,
                    max_steps,
                    relay: None,
                };
                let cancel = Arc::new(AtomicBool::new(false));
                let flag = cancel.clone();
                let signal = tokio::spawn(async move {
                    if tokio::signal::ctrl_c().await.is_ok() {
                        flag.store(true, Ordering::Release);
                        eprintln!("Stop requested; no new samples will start.");
                    }
                });
                let result = engine::run(
                    store.clone(),
                    prepared.plan.clone(),
                    options,
                    Arc::new(adapters::NativeExecutor),
                    cancel,
                    None,
                )
                .await;
                signal.abort();
                if let Err(error) = result {
                    orchestration_failed = true;
                    // The error chain can include private request details. Keep it
                    // beside the private journal, never in Actions output.
                    write_new(
                        &cli.data
                            .join(format!("smoke-error-{}.json", Uuid::new_v4())),
                        &json!({"error":format!("{error:#}")}),
                    )?;
                }
            }
            let mut report = smoke::report(&store, &prepared)?;
            report["execution_requested"] = json!(execute_live);
            report["orchestration_failed"] = json!(orchestration_failed);
            finish_output(report_file, &report)?;
            print_json(&json!({
                "report": output,
                "provider_count": report["provider_count"],
                "ready_provider_count": report["ready_provider_count"],
                "attempted_provider_count": report["attempted_provider_count"],
                "verified_provider_count": report["verified_provider_count"],
                "all_providers_verified": report["all_providers_verified"],
                "runnable_providers_verified": report["runnable_providers_verified"],
                "orchestration_failed": orchestration_failed,
            }))?;
            let verified = if require_all_providers {
                &report["all_providers_verified"]
            } else {
                &report["runnable_providers_verified"]
            };
            if execute_live && (orchestration_failed || verified.as_bool() != Some(true)) {
                return Ok(2);
            }
        }
        Command::Plan {
            provider,
            game,
            mode,
            samples,
            output,
            repo,
            settings,
            id,
        } => {
            let snapshot = store.inventory(None).context("import an inventory first")?;
            let p = snapshot
                .providers
                .iter()
                .find(|p| p.id == provider)
                .context("provider absent from inventory")?;
            let g = p
                .games
                .iter()
                .find(|g| g.id == game)
                .context("game absent from inventory")?;
            let settings: Value = if let Some(path) = settings {
                serde_json::from_slice(&fs::read(path).context("cannot read settings")?)
                    .context("invalid settings JSON")?
            } else {
                bindings::from_repo(&repo, &provider, g)?
            };
            ensure!(settings.is_object(), "settings must be a JSON object");
            let jobs = mode
                .into_iter()
                .map(|mode| Job {
                    provider: provider.clone(),
                    game: game.clone(),
                    mode,
                    samples,
                    settings: settings.clone(),
                })
                .collect();
            let plan = CampaignPlan {
                schema_version: 1,
                id: id.unwrap_or_else(|| Uuid::new_v4().to_string()),
                inventory_id: snapshot.id,
                coverage: None,
                jobs,
            };
            validate(&store, &plan, &RunOptions::default())?;
            write_new(&output, &plan)?;
            print_json(
                &json!({"campaign_id":plan.id,"inventory_id":plan.inventory_id,"jobs":plan.jobs.len(),"output":output}),
            )?;
        }
        Command::PlanAll {
            provider,
            game,
            samples,
            output,
            repo,
            settings,
            suite_root,
            python,
            max_prerequisite_rounds,
            id,
        } => {
            let snapshot = store.inventory(None).context("import an inventory first")?;
            let mut options = campaign::PlanOptions {
                providers: provider,
                games: game,
                samples,
                suite_root,
                max_prerequisite_rounds,
                ..Default::default()
            };
            if let Some(python) = python {
                options.python = python;
            }
            if let Some(path) = settings {
                options.settings =
                    serde_json::from_slice(&fs::read(path).context("cannot read settings")?)
                        .context("invalid settings JSON")?;
            }
            let plan = campaign::plan_all(
                &snapshot,
                &repo,
                &id.unwrap_or_else(|| Uuid::new_v4().to_string()),
                &options,
            )?;
            if !plan.jobs.is_empty() {
                validate(&store, &plan, &RunOptions::default())?;
            }
            write_new(&output, &plan)?;
            let coverage = plan.coverage.as_ref().unwrap();
            print_json(
                &json!({"campaign_id":plan.id,"output":output,"jobs":plan.jobs.len(),
                "inventory_mode_count":coverage["inventory_mode_count"],"omitted_mode_count":coverage["omitted_mode_count"],
                "omitted_game_count":coverage["omitted_game_count"],"alias_mode_count":coverage["alias_mode_count"],
                "inventory_complete":coverage["inventory_complete"],"network_requests":0}),
            )?;
        }
        Command::Coverage { plan, campaign } => {
            let plan = if let Some(path) = plan {
                read_plan(&path)?
            } else {
                store.campaign(&campaign.context("campaign or plan required")?)?
            };
            print_json(&campaign::report(&store, &plan)?)?;
        }
        Command::RecoverNonfinancial { round_id, reason } => {
            let record = store.recover_nonfinancial_round(&round_id, &reason)?;
            print_json(
                &json!({"round_id":record.id,"status":record.status,"recovered":true,
                "next_step":"create a new campaign; release any retained provider hold only after reviewing its cause"}),
            )?;
        }
        Command::Check { plan } => {
            let plan = read_plan(&plan)?;
            validate(&store, &plan, &RunOptions::default())?;
            print_json(
                &json!({"valid":true,"campaign_id":plan.id,"jobs":plan.jobs.len(),"planning_coverage":plan.coverage,"network_requests":0}),
            )?;
        }
        Command::Run {
            plan,
            parallel_providers,
            timeout_seconds,
            max_steps,
            relay,
        } => {
            let plan = read_plan(&plan)?;
            let options = RunOptions {
                parallel_providers,
                timeout_seconds,
                max_steps,
                relay,
            };
            validate(&store, &plan, &options)?;
            let cancel = Arc::new(AtomicBool::new(false));
            let flag = cancel.clone();
            let signal = tokio::spawn(async move {
                if tokio::signal::ctrl_c().await.is_ok() {
                    flag.store(true, Ordering::Release);
                    eprintln!(
                        "Interrupción solicitada: las rondas actuales continúan; no se iniciarán nuevas muestras."
                    );
                }
            });
            let (tx, mut rx) = mpsc::unbounded_channel();
            let printer = tokio::spawn(async move {
                while let Some(event) = rx.recv().await {
                    if let Ok(value) = serde_json::to_string(&event) {
                        eprintln!("{value}");
                    }
                }
            });
            let report = engine::run(
                store,
                plan,
                options,
                Arc::new(adapters::NativeExecutor),
                cancel,
                Some(tx),
            )
            .await;
            signal.abort();
            let _ = printer.await;
            let report = report.context("campaign failed; inspect durable status")?;
            // Worker reasons may contain request details. Only emit the safe status and counts.
            let providers:Vec<_>=report.providers.iter().map(|p|json!({"provider":p.provider,"new_rounds":p.new_rounds,"skipped_samples":p.skipped_samples,"stopped":p.stopped})).collect();
            print_json(
                &json!({"campaign_id":report.campaign_id,"requested_samples":report.requested_samples,"status_counts":report.status_counts,"providers":providers,"runnable_completed":report.runnable_completed,"completed":report.completed}),
            )?;
            if !report.completed {
                return Ok(2);
            }
        }
        Command::Status {
            provider,
            game,
            campaign,
        } => {
            let rounds = store.rounds()?;
            let filtered: Vec<_> = rounds
                .iter()
                .filter(|r| {
                    provider.as_ref().is_none_or(|x| x == &r.spec.provider)
                        && game.as_ref().is_none_or(|x| x == &r.spec.game)
                        && campaign.as_ref().is_none_or(|x| x == &r.spec.campaign_id)
                })
                .collect();
            let mut counts = BTreeMap::<String, usize>::new();
            for r in &filtered {
                *counts.entry(r.status.as_str().into()).or_default() += 1;
            }
            let mut holds = Vec::new();
            if let Ok(inv) = store.inventory(None) {
                for p in inv
                    .providers
                    .iter()
                    .filter(|p| provider.as_ref().is_none_or(|x| x == &p.id))
                {
                    if store.provider_hold(&p.id)?.is_some() {
                        holds.push(json!({"provider":p.id,"held":true}));
                    }
                }
            } else if let Some(p) = provider
                && store.provider_hold(&p)?.is_some()
            {
                holds.push(json!({"provider":p,"held":true}));
            }
            let pending: Vec<_> = filtered
                .iter()
                .filter(|r| !r.status.terminal())
                .map(|r| export::public_receipt(&store, r))
                .collect();
            print_json(
                &json!({"counts":counts,"total":filtered.len(),"pending":pending,"holds":holds}),
            )?;
        }
        Command::Show {
            round_id,
            private,
            output,
        } => {
            let r = store.round(&round_id).context("round not found")?;
            let mut result = export::public_receipt(&store, &r);
            if private {
                let path =
                    output.context("--private requires --output to protect sensitive data")?;
                let exchanges = store.exchanges(&r.id)?;
                result["steps"] = export::private_steps(&exchanges);
                result["private"] = json!({"owner":store.session(&r.id)?,"bootstrap_attempts":store.bootstrap_attempts(&r.id)?,"exchanges":exchanges,"native_data":r.outcome.as_ref().map(|o|&o.native_data),"reason":r.reason});
                write_new(&path, &result)?;
                print_json(&json!({"round_id":r.id,"private_output":path}))?;
            } else {
                print_json(&result)?;
            }
        }
        Command::Export {
            output,
            provider,
            game,
            kind,
            include_unverified,
            include_wire,
        } => {
            let options = ExportOptions {
                output,
                provider,
                game,
                kind: kind.as_deref().map(parse_kind).transpose()?,
                include_unverified,
                include_wire,
            };
            print_json(&export::export(&store, &options)?)?;
        }
        Command::ReleaseHold { provider, reason } => {
            ensure!(!reason.trim().is_empty(), "release requires a reason");
            store.release_provider_hold(&provider, &reason)?;
            print_json(&json!({"provider":provider,"released":true}))?;
        }
    }
    Ok(0)
}
#[tokio::main]
async fn main() {
    let cli = Cli::parse();
    let is_run = matches!(&cli.command, Command::Run { .. } | Command::SmokeAll { .. });
    let code = match execute(cli).await {
        Ok(code) => code,
        Err(error) => {
            if is_run {
                eprintln!("No se pudo iniciar o finalizar la campaña; revise el estado durable.");
            } else {
                eprintln!("Error: {error:#}");
            }
            1
        }
    };
    if code != 0 {
        std::process::exit(code);
    }
}
