use crate::{context::RunContext, model::*, store::Store};
use anyhow::{Result, ensure};
use async_trait::async_trait;
use serde::Serialize;
use serde_json::Value;
use std::{
    collections::{BTreeMap, HashSet},
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
};
use tokio::sync::{Semaphore, mpsc};

#[async_trait]
pub trait Executor: Send + Sync {
    fn validate(&self, provider: &str, game: &Game, mode: &Mode, settings: &Value) -> Result<()>;
    async fn execute(
        &self,
        ctx: &RunContext,
        provider: &str,
        game: &Game,
        mode: &Mode,
        settings: &Value,
    ) -> Result<RoundOutcome>;
}

#[derive(Debug, Clone)]
pub struct RunOptions {
    pub parallel_providers: usize,
    pub timeout_seconds: u64,
    pub max_steps: usize,
    pub relay: Option<String>,
}
impl Default for RunOptions {
    fn default() -> Self {
        Self {
            parallel_providers: 4,
            timeout_seconds: 45,
            max_steps: 3_000,
            relay: None,
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct ProviderResult {
    pub provider: String,
    pub new_rounds: usize,
    pub skipped_samples: usize,
    pub stopped: bool,
    pub reason: Option<String>,
}
#[derive(Debug, Clone, Serialize)]
pub struct RunReport {
    pub campaign_id: String,
    pub requested_samples: u64,
    pub providers: Vec<ProviderResult>,
    pub status_counts: BTreeMap<String, usize>,
    pub runnable_completed: bool,
    pub completed: bool,
}
#[derive(Debug, Clone, Serialize)]
pub struct RoundEvent {
    pub round_id: String,
    pub provider: String,
    pub game: String,
    pub mode: String,
    pub status: RoundStatus,
    pub operation: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<RoundEventError>,
}

#[derive(Debug, Clone, Serialize, serde::Deserialize)]
pub struct RoundEventError {
    pub stage: Option<String>,
    pub http_status: Option<u16>,
    pub financial_intent: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub browser_challenge: bool,
}

fn demo_issuer_declined(label: &str, response: &WireResponse) -> bool {
    label == "netent_demo_issuer"
        && response.status == 200
        && serde_json::from_str::<Value>(&response.body).is_ok_and(|body| body["success"] == false)
}

pub fn validate_plan(
    plan: &CampaignPlan,
    inventory: &InventorySnapshot,
    executor: &dyn Executor,
    options: &RunOptions,
) -> Result<()> {
    ensure!(
        plan.schema_version == 1,
        "unsupported plan schema_version; expected 1"
    );
    ensure!(
        !plan.id.trim().is_empty() && plan.id.len() <= 128,
        "campaign id must be 1..128 bytes"
    );
    ensure!(
        plan.inventory_id == inventory.id,
        "plan inventory does not match the pinned snapshot"
    );
    ensure!(
        !plan.jobs.is_empty() && plan.jobs.len() <= 100_000,
        "campaign must contain 1..100000 jobs"
    );
    ensure!(
        (1..=35).contains(&options.parallel_providers),
        "parallel providers must be 1..35"
    );
    ensure!(
        (1..=300).contains(&options.timeout_seconds),
        "timeout must be 1..300 seconds"
    );
    ensure!(
        (1..=10_000).contains(&options.max_steps),
        "step limit must be 1..10000"
    );
    if let Some(relay) = &options.relay {
        crate::context::validate_relay(relay)?;
    }
    crate::campaign::validate_coverage(plan, inventory)?;
    let mut total = 0u64;
    for (index, job) in plan.jobs.iter().enumerate() {
        ensure!(
            (1..=1_000_000).contains(&job.samples),
            "job {index}: samples must be 1..1000000"
        );
        total = total
            .checked_add(u64::from(job.samples))
            .ok_or_else(|| anyhow::anyhow!("campaign sample count overflow"))?;
        ensure!(
            total <= 10_000_000,
            "campaign exceeds 10000000 finite samples"
        );
        let (provider, game, mode) = inventory.lookup(&job.provider, &job.game, &job.mode)?;
        ensure!(
            provider.id != "kendoo"
                || (plan.coverage.is_none()
                    && plan.jobs.len() == 1
                    && job.samples == 1
                    && job.settings.as_object().is_some_and(|v| v.is_empty())
                    && crate::adapters::kendoo::supports(game, mode)),
            "Kendoo is limited to a single reviewed standalone demo sample"
        );
        ensure!(
            provider.ready
                && (provider.campaign_eligible
                    || (plan.coverage.is_none()
                        && job.settings["executor"].is_null()
                        && matches!(provider.id.as_str(), "hardfire-kalamba" | "microgaming")
                        && crate::adapters::supports(&provider.id, game, mode))),
            "job {index}: provider is not campaign eligible"
        );
        ensure!(
            game.ready,
            "job {index}: game is not ready in pinned inventory"
        );
        ensure!(
            mode.ready,
            "job {index}: mode is not ready in pinned inventory"
        );
        ensure!(
            mode.execution_source.as_deref() != Some("local_model"),
            "job {index}: local model calculations are not remote demo rounds"
        );
        let prerequisites = &mode.requires_prerequisites;
        ensure!(
            prerequisites.is_null()
                || prerequisites == false
                || prerequisites.as_array().is_some_and(|x| x.is_empty())
                || prerequisites.as_object().is_some_and(|x| x.is_empty())
                || ((job.settings["executor"] == "suite"
                    || (job.provider == "netent"
                        && crate::adapters::netent_horizon::requires_progression(game, mode)))
                    && job.settings["max_prerequisite_rounds"]
                        .as_u64()
                        .is_some_and(|budget| (1..=100).contains(&budget))),
            "job {index}: prerequisite-dependent mode requires a reviewed executor and max_prerequisite_rounds in 1..100"
        );
        executor.validate(&job.provider, game, mode, &job.settings)?;
    }
    Ok(())
}

pub async fn run(
    store: Store,
    plan: CampaignPlan,
    options: RunOptions,
    executor: Arc<dyn Executor>,
    cancel: Arc<AtomicBool>,
    events: Option<mpsc::UnboundedSender<RoundEvent>>,
) -> Result<RunReport> {
    let inventory = store.inventory(Some(&plan.inventory_id))?;
    validate_plan(&plan, &inventory, executor.as_ref(), &options)?;
    store.create_campaign(&plan)?;
    let requested_samples = plan.jobs.iter().map(|j| u64::from(j.samples)).sum();
    let mut groups = BTreeMap::<String, Vec<(u32, Job)>>::new();
    for (index, job) in plan.jobs.iter().enumerate() {
        groups
            .entry(canonical_provider(&job.provider).into())
            .or_default()
            .push((index as u32, job.clone()));
    }
    let semaphore = Arc::new(Semaphore::new(options.parallel_providers));
    let inventory = Arc::new(inventory);
    let plan = Arc::new(plan);
    let mut workers = tokio::task::JoinSet::new();
    for (provider, jobs) in groups {
        let (store, options, executor, cancel, events, semaphore, inventory, plan) = (
            store.clone(),
            options.clone(),
            executor.clone(),
            cancel.clone(),
            events.clone(),
            semaphore.clone(),
            inventory.clone(),
            plan.clone(),
        );
        workers.spawn(async move {
            let _permit = semaphore.acquire_owned().await?;
            run_provider(
                store,
                &plan,
                &inventory,
                &provider,
                jobs,
                &options,
                executor.as_ref(),
                &cancel,
                events,
            )
            .await
        });
    }
    let mut providers = Vec::new();
    while let Some(worker) = workers.join_next().await {
        // Await all workers even if one panics: never abort another provider's accepted round.
        match worker {
            Ok(Ok(result)) => providers.push(result),
            Ok(Err(error)) => providers.push(ProviderResult {
                provider: "internal".into(),
                new_rounds: 0,
                skipped_samples: 0,
                stopped: true,
                reason: Some(format!("storage or scheduler failure: {error}")),
            }),
            Err(_) => providers.push(ProviderResult {
                provider: "internal".into(),
                new_rounds: 0,
                skipped_samples: 0,
                stopped: true,
                reason: Some(
                    "worker stopped unexpectedly; durable pending rounds require review".into(),
                ),
            }),
        }
    }
    providers.sort_by(|a, b| a.provider.cmp(&b.provider));
    let mut status_counts = BTreeMap::new();
    for round in store
        .rounds()?
        .iter()
        .filter(|r| r.spec.campaign_id == plan.id)
    {
        *status_counts
            .entry(round.status.as_str().to_owned())
            .or_default() += 1;
    }
    let runnable_completed = status_counts.get("verified").copied().unwrap_or_default() as u64
        == requested_samples
        && !providers.iter().any(|p| p.stopped);
    let completed = runnable_completed
        && plan
            .coverage
            .as_ref()
            .is_none_or(|coverage| coverage["inventory_complete"] == true);
    Ok(RunReport {
        campaign_id: plan.id.clone(),
        requested_samples,
        providers,
        status_counts,
        runnable_completed,
        completed,
    })
}

#[allow(clippy::too_many_arguments)]
async fn run_provider(
    store: Store,
    plan: &CampaignPlan,
    inventory: &InventorySnapshot,
    provider: &str,
    jobs: Vec<(u32, Job)>,
    options: &RunOptions,
    executor: &dyn Executor,
    cancel: &AtomicBool,
    events: Option<mpsc::UnboundedSender<RoundEvent>>,
) -> Result<ProviderResult> {
    let mut result = ProviderResult {
        provider: provider.into(),
        new_rounds: 0,
        skipped_samples: 0,
        stopped: false,
        reason: None,
    };
    let _guard = match store.acquire_provider(provider) {
        Ok(g) => g,
        Err(_) => {
            result.stopped = true;
            result.reason = Some("another process is already using this provider".into());
            return Ok(result);
        }
    };
    if store.provider_hold(provider)?.is_some() {
        result.stopped = true;
        result.reason = Some("provider has a persistent hold; inspect status".into());
        return Ok(result);
    }
    let collector_marker = store
        .root()
        .join("locks")
        .join(format!("collector-{provider}.pending.json"));
    if collector_marker.exists() || collector_marker.is_symlink() {
        result.stopped = true;
        result.reason = Some(
            "collector has a retained canonical-provider attempt; review its original owner".into(),
        );
        return Ok(result);
    }
    if let Some(round) = store.pending_provider(provider)? {
        result.stopped = true;
        result.reason = Some(format!(
            "pending round {} ({}) must be reviewed before a new owner",
            round.id,
            round.status.as_str()
        ));
        return Ok(result);
    }
    let records = store.rounds()?;
    let current: Vec<_> = records
        .iter()
        .filter(|r| {
            r.spec.campaign_id == plan.id && canonical_provider(&r.spec.provider) == provider
        })
        .collect();
    if let Some(failed) = current.iter().find(|r| r.status != RoundStatus::Verified) {
        result.stopped = true;
        result.reason = Some(format!(
            "campaign contains failed sample {}; use a separately reviewed new campaign after resolving the cause",
            failed.id
        ));
        return Ok(result);
    }
    let prior: HashSet<(u32, u32)> = current
        .iter()
        .map(|r| (r.spec.job_index, r.spec.sample_index))
        .collect();
    'jobs: for (job_index, job) in jobs {
        let (_, game, mode) = inventory.lookup(&job.provider, &job.game, &job.mode)?;
        for sample_index in 0..job.samples {
            if prior.contains(&(job_index, sample_index)) {
                result.skipped_samples += 1;
                continue;
            }
            if cancel.load(Ordering::Acquire) {
                result.stopped = true;
                result.reason = Some("stop requested; no new samples started".into());
                break 'jobs;
            }
            {
                let delay = store.reserve_provider_start(
                    provider,
                    crate::suite::min_interval_seconds(provider),
                )?;
                let deadline = tokio::time::Instant::now() + delay;
                while tokio::time::Instant::now() < deadline && !cancel.load(Ordering::Acquire) {
                    tokio::time::sleep_until(
                        deadline.min(
                            tokio::time::Instant::now() + std::time::Duration::from_millis(100),
                        ),
                    )
                    .await;
                }
                if cancel.load(Ordering::Acquire) {
                    result.stopped = true;
                    result.reason = Some("stop requested before scheduled provider start".into());
                    break 'jobs;
                }
            }
            let spec = RoundSpec {
                campaign_id: plan.id.clone(),
                inventory_id: plan.inventory_id.clone(),
                job_index,
                sample_index,
                provider: job.provider.clone(),
                game: job.game.clone(),
                mode: job.mode.clone(),
                kind: mode.kind,
                settings: job.settings.clone(),
            };
            let round = store.create_round(&spec)?;
            let mut outcome;
            loop {
                // Each permitted bootstrap attempt gets a new HTTP client and
                // cookie jar. Store verifies zero financial intent and a durable
                // single-refresh bound before the executor can run again.
                let ctx = RunContext::new(
                    store.clone(),
                    round.id.clone(),
                    &job.provider,
                    options.timeout_seconds,
                    options.max_steps,
                    options.relay.as_deref(),
                )?;
                outcome = executor
                    .execute(&ctx, &job.provider, game, mode, &job.settings)
                    .await;
                #[cfg(all(windows, feature = "redtiger-bundled-http"))]
                ctx.close_direct_http().await;
                if outcome.is_err()
                    && !cancel.load(Ordering::Acquire)
                    && !(cfg!(all(windows, feature = "spinomenal-bundled-http"))
                        && job.provider == "spinomenal")
                    && store.prepare_bootstrap_retry(&round.id)?
                {
                    continue;
                }
                break;
            }
            match outcome {
                Ok(outcome) => {
                    if let Err(error) = store.complete(&round.id, &outcome) {
                        let current = store.round(&round.id)?;
                        if !current.status.terminal() {
                            store.mark_error(
                                &round.id,
                                &format!("could not commit outcome: {error:#}"),
                            )?;
                        }
                    }
                }
                Err(error) => {
                    let current = store.round(&round.id)?;
                    if !current.status.terminal() {
                        store.mark_error(&round.id, &format!("{error:#}"))?;
                    }
                }
            }
            let record = store.round(&round.id)?;
            result.new_rounds += 1;
            if let Some(events) = &events {
                let error = if record.status == RoundStatus::Verified {
                    None
                } else {
                    let exchanges = store.exchanges(&record.id).unwrap_or_default();
                    let last = exchanges.last();
                    let suite_failure = last
                        .filter(|exchange| exchange.request.label == "suite_worker_dispatch")
                        .and_then(|exchange| {
                            exchange
                                .frames
                                .iter()
                                .rev()
                                .find(|frame| frame.kind == "suite_provider_failure")
                        })
                        .and_then(|frame| serde_json::from_str(&frame.body).ok());
                    suite_failure.or_else(|| {
                        let declined = last.is_some_and(|exchange| {
                            exchange.response.as_ref().is_some_and(|response| {
                                demo_issuer_declined(&exchange.request.label, response)
                            })
                        });
                        Some(RoundEventError {
                            stage: last.map(|exchange| exchange.request.label.clone()),
                            http_status: last
                                .and_then(|exchange| {
                                    exchange.response.as_ref().map(|response| response.status)
                                })
                                .filter(|status| *status >= 400 || declined),
                            financial_intent: last.map(|_| {
                                exchanges.iter().any(|exchange| exchange.request.financial)
                            }),
                            browser_challenge: last
                                .and_then(|exchange| exchange.response.as_ref())
                                .is_some_and(|response| {
                                    response.status == 403
                                        && response.headers.get("cf-mitigated").is_some_and(
                                            |value| value.eq_ignore_ascii_case("challenge"),
                                        )
                                }),
                            reason: if declined {
                                Some("demo_issuer_declined".into())
                            } else if record.spec.provider == "irondog"
                                && record.reason.as_deref()
                                    == Some(crate::adapters::irondog::MISSING_CLOSING_BALANCE)
                            {
                                Some("native_closing_balance_unavailable".into())
                            } else {
                                None
                            },
                        })
                    })
                };
                let _ = events.send(RoundEvent {
                    round_id: record.id.clone(),
                    provider: record.spec.provider.clone(),
                    game: record.spec.game.clone(),
                    mode: record.spec.mode.clone(),
                    status: record.status,
                    operation: record.spec.kind.operation(),
                    error,
                });
            }
            // Stop this provider on any failed sample; other providers finish independently.
            if record.status != RoundStatus::Verified {
                result.stopped = true;
                result.reason = Some(format!(
                    "round {} is {}; inspect its private record",
                    record.id,
                    record.status.as_str()
                ));
                break 'jobs;
            }
        }
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn netent_reports_issuer_decline_separately_from_http_rejection() {
        let mut response = WireResponse {
            status: 200,
            headers: BTreeMap::new(),
            body: r#"{"success":false,"payload":"private details"}"#.into(),
            set_cookies: Vec::new(),
        };
        assert!(demo_issuer_declined("netent_demo_issuer", &response));
        assert!(!demo_issuer_declined("unrelated", &response));
        response.status = 403;
        assert!(!demo_issuer_declined("netent_demo_issuer", &response));
    }
    use serde_json::json;
    use std::sync::Mutex;
    struct Fake {
        active: Mutex<HashSet<String>>,
        maximum: Mutex<usize>,
        seen: Mutex<usize>,
        fail: bool,
        entered: Mutex<HashSet<String>>,
        rendezvous: Option<tokio::sync::Barrier>,
    }
    #[async_trait]
    impl Executor for Fake {
        fn validate(&self, _: &str, _: &Game, _: &Mode, _: &Value) -> Result<()> {
            Ok(())
        }
        async fn execute(
            &self,
            ctx: &RunContext,
            provider: &str,
            _: &Game,
            _: &Mode,
            _: &Value,
        ) -> Result<RoundOutcome> {
            {
                let mut active = self.active.lock().unwrap();
                assert!(
                    active.insert(canonical_provider(provider).into()),
                    "same provider overlap"
                );
                let mut max = self.maximum.lock().unwrap();
                *max = (*max).max(active.len());
            }
            *self.seen.lock().unwrap() += 1;
            if let Some(barrier) = &self.rendezvous {
                let first = self
                    .entered
                    .lock()
                    .unwrap()
                    .insert(canonical_provider(provider).into());
                if first {
                    // Prove overlap without assuming a Windows filesystem can
                    // finish another provider's journal within a 40 ms sleep.
                    tokio::time::timeout(std::time::Duration::from_secs(30), barrier.wait())
                        .await?;
                }
            }
            ctx.save_session(&json!({"session":"test-only"}))?;
            let n = ctx.store.start_exchange(
                &ctx.round_id,
                &WireRequest {
                    label: "test".into(),
                    transport: "fixture".into(),
                    method: "POST".into(),
                    url: "fixture".into(),
                    headers: BTreeMap::new(),
                    body: String::new(),
                    financial: true,
                },
            )?;
            tokio::time::sleep(std::time::Duration::from_millis(40)).await;
            self.active
                .lock()
                .unwrap()
                .remove(canonical_provider(provider));
            if self.fail {
                ctx.store
                    .fail_exchange(&ctx.round_id, n, "test dropped response")?;
                anyhow::bail!("test dropped response")
            }
            ctx.store.finish_exchange(
                &ctx.round_id,
                n,
                &WireResponse {
                    status: 200,
                    headers: BTreeMap::new(),
                    body: "{}".into(),
                    set_cookies: Vec::new(),
                },
            )?;
            Ok(RoundOutcome {
                native_round_id: Some("fixture-round".into()),
                currency: "EUR".into(),
                monetary_unit: "major".into(),
                currency_source: "native_response".into(),
                balance_before: "10".into(),
                balance_after: "9".into(),
                cost: "1".into(),
                payout: "0".into(),
                native_closed: true,
                checks: BTreeMap::new(),
                native_data: Value::Null,
            })
        }
    }
    fn fake(fail: bool) -> Arc<Fake> {
        Arc::new(Fake {
            active: Mutex::new(HashSet::new()),
            maximum: Mutex::new(0),
            seen: Mutex::new(0),
            fail,
            entered: Mutex::new(HashSet::new()),
            rendezvous: None,
        })
    }
    fn fixture() -> (tempfile::TempDir, Store, CampaignPlan, InventorySnapshot) {
        let dir = tempfile::tempdir().unwrap();
        let store = Store::open(dir.path()).unwrap();
        let providers = ["pragmatic", "reelkingdom", "hacksaw"]
            .into_iter()
            .map(|id| ProviderInventory {
                id: id.into(),
                name: id.into(),
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
            })
            .collect();
        let inventory = InventorySnapshot {
            id: "fixture".into(),
            providers,
            sources: vec![],
        };
        store.install_inventory(&inventory).unwrap();
        let plan = CampaignPlan {
            schema_version: 1,
            id: "test-campaign".into(),
            inventory_id: inventory.id.clone(),
            coverage: None,
            jobs: ["pragmatic", "reelkingdom", "hacksaw"]
                .into_iter()
                .map(|p| Job {
                    provider: p.into(),
                    game: "g".into(),
                    mode: "normal".into(),
                    samples: 2,
                    settings: Value::Null,
                })
                .collect(),
        };
        (dir, store, plan, inventory)
    }
    struct BootstrapFixture {
        origin: String,
        executions: std::sync::atomic::AtomicUsize,
        financial_before_rejection: bool,
    }
    #[async_trait]
    impl Executor for BootstrapFixture {
        fn validate(&self, _: &str, _: &Game, _: &Mode, _: &Value) -> Result<()> {
            Ok(())
        }
        async fn execute(
            &self,
            context: &RunContext,
            _: &str,
            _: &Game,
            _: &Mode,
            _: &Value,
        ) -> Result<RoundOutcome> {
            let attempt = self.executions.fetch_add(1, Ordering::SeqCst);
            let mut ctx = context.clone();
            ctx.route_to_fixture(&self.origin)?;
            ctx.get(
                "preflight",
                "https://demogamesfree.pragmaticplay.net/preflight",
            )
            .await?;
            ctx.save_session(&json!({"owner": format!("bootstrap-{attempt}")}))?;
            let n = if self.financial_before_rejection {
                Some(ctx.store.start_exchange(
                    &ctx.round_id,
                    &WireRequest {
                        label: "paid".into(),
                        transport: "fixture".into(),
                        method: "POST".into(),
                        url: "fixture".into(),
                        headers: BTreeMap::new(),
                        body: String::new(),
                        financial: true,
                    },
                )?)
            } else {
                None
            };
            if let Some(n) = n {
                ctx.store.finish_exchange(
                    &ctx.round_id,
                    n,
                    &WireResponse {
                        status: 200,
                        headers: BTreeMap::new(),
                        body: "accepted".into(),
                        set_cookies: vec![],
                    },
                )?;
            }
            ctx.get(
                "bootstrap",
                "https://demogamesfree.pragmaticplay.net/bootstrap",
            )
            .await?;
            let n = ctx.store.start_exchange(
                &ctx.round_id,
                &WireRequest {
                    label: "paid".into(),
                    transport: "fixture".into(),
                    method: "POST".into(),
                    url: "fixture".into(),
                    headers: BTreeMap::new(),
                    body: String::new(),
                    financial: true,
                },
            )?;
            ctx.store.finish_exchange(
                &ctx.round_id,
                n,
                &WireResponse {
                    status: 200,
                    headers: BTreeMap::new(),
                    body: "accepted".into(),
                    set_cookies: vec![],
                },
            )?;
            Ok(RoundOutcome {
                native_round_id: Some("native".into()),
                currency: "EUR".into(),
                monetary_unit: "major".into(),
                currency_source: "native_response".into(),
                balance_before: "10".into(),
                balance_after: "9".into(),
                cost: "1".into(),
                payout: "0".into(),
                native_closed: true,
                checks: BTreeMap::new(),
                native_data: Value::Null,
            })
        }
    }
    async fn bootstrap_server(listener: tokio::net::TcpListener, challenge: bool, twice: bool) {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        for index in 0..if challenge { 2 } else { 4 } {
            let accepted =
                tokio::time::timeout(std::time::Duration::from_secs(3), listener.accept()).await;
            let Ok(Ok((mut stream, _))) = accepted else {
                return;
            };
            let mut bytes = Vec::new();
            while !bytes.ends_with(b"\r\n\r\n") {
                let mut byte = [0];
                stream.read_exact(&mut byte).await.unwrap();
                bytes.push(byte[0]);
            }
            let request = String::from_utf8(bytes).unwrap();
            if index == 0 || index == 2 {
                assert!(
                    !request.to_ascii_lowercase().contains("\r\ncookie:"),
                    "bootstrap retry reused cookies"
                );
            }
            let reject = index == 1 || (twice && index == 3);
            let status = if reject { "403 Forbidden" } else { "200 OK" };
            let challenge_header = if challenge && reject {
                "cf-mitigated: challenge\r\n"
            } else {
                ""
            };
            stream.write_all(format!("HTTP/1.1 {status}\r\nContent-Length: 2\r\nConnection: close\r\nSet-Cookie: sid=stale; Path=/; Secure\r\n{challenge_header}\r\nOK").as_bytes()).await.unwrap();
            stream.shutdown().await.unwrap();
        }
        assert!(
            tokio::time::timeout(std::time::Duration::from_millis(150), listener.accept())
                .await
                .is_err(),
            "bootstrap exceeded retry bound"
        );
    }
    #[tokio::test]
    async fn bootstrap_403_gets_one_fresh_context_before_financial_intent() {
        let (_d, store, mut plan, _) = fixture();
        plan.jobs.truncate(1);
        plan.jobs[0].samples = 1;
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let executor = Arc::new(BootstrapFixture {
            origin: format!("http://{}", listener.local_addr().unwrap()),
            executions: std::sync::atomic::AtomicUsize::new(0),
            financial_before_rejection: false,
        });
        let server = tokio::spawn(bootstrap_server(listener, false, false));
        let report = run(
            store.clone(),
            plan,
            RunOptions::default(),
            executor.clone(),
            Arc::new(AtomicBool::new(false)),
            None,
        )
        .await
        .unwrap();
        server.await.unwrap();
        assert!(report.completed, "{:?}", report.providers);
        assert_eq!(executor.executions.load(Ordering::SeqCst), 2);
        let rounds = store.rounds().unwrap();
        assert_eq!(rounds.len(), 1);
        let exchanges = store.exchanges(&rounds[0].id).unwrap();
        assert_eq!(exchanges.len(), 5);
        assert_eq!(exchanges[1].response.as_ref().unwrap().status, 403);
        assert_eq!(
            store.session(&rounds[0].id).unwrap(),
            Some(json!({"owner":"bootstrap-1"}))
        );
        let db = rusqlite::Connection::open(store.root().join("runner.sqlite3")).unwrap();
        let retained_owner: String = db
            .query_row(
                "SELECT owner FROM bootstrap_retries WHERE round_id=?1",
                [&rounds[0].id],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&retained_owner).unwrap(),
            json!({"owner":"bootstrap-0"})
        );
    }
    #[tokio::test]
    async fn bootstrap_challenge_and_financial_rejection_never_replace_owner() {
        for financial in [false, true] {
            let (_d, store, mut plan, _) = fixture();
            plan.jobs.truncate(1);
            plan.jobs[0].samples = 2;
            let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
            let executor = Arc::new(BootstrapFixture {
                origin: format!("http://{}", listener.local_addr().unwrap()),
                executions: std::sync::atomic::AtomicUsize::new(0),
                financial_before_rejection: financial,
            });
            let server = tokio::spawn(bootstrap_server(listener, !financial, false));
            let (events, mut received) = mpsc::unbounded_channel();
            let report = run(
                store.clone(),
                plan,
                RunOptions::default(),
                executor.clone(),
                Arc::new(AtomicBool::new(false)),
                Some(events),
            )
            .await
            .unwrap();
            server.await.unwrap();
            let error = received.try_recv().unwrap().error.unwrap();
            assert_eq!(error.http_status, Some(403));
            assert_eq!(error.browser_challenge, !financial);
            assert_eq!(error.financial_intent, Some(financial));
            assert!(!report.completed);
            assert_eq!(executor.executions.load(Ordering::SeqCst), 1);
            let rounds = store.rounds().unwrap();
            assert_eq!(rounds.len(), 1);
            assert_eq!(
                rounds[0].status,
                if financial {
                    RoundStatus::Uncertain
                } else {
                    RoundStatus::Blocked
                }
            );
            assert_eq!(
                store.session(&rounds[0].id).unwrap(),
                Some(json!({"owner":"bootstrap-0"}))
            );
        }
    }
    #[tokio::test]
    async fn repeated_bootstrap_403_stops_after_one_refresh() {
        let (_d, store, mut plan, _) = fixture();
        plan.jobs.truncate(1);
        plan.jobs[0].samples = 2;
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let executor = Arc::new(BootstrapFixture {
            origin: format!("http://{}", listener.local_addr().unwrap()),
            executions: std::sync::atomic::AtomicUsize::new(0),
            financial_before_rejection: false,
        });
        let server = tokio::spawn(bootstrap_server(listener, false, true));
        let report = run(
            store.clone(),
            plan,
            RunOptions::default(),
            executor.clone(),
            Arc::new(AtomicBool::new(false)),
            None,
        )
        .await
        .unwrap();
        server.await.unwrap();
        assert!(!report.completed);
        assert_eq!(executor.executions.load(Ordering::SeqCst), 2);
        assert_eq!(store.rounds().unwrap().len(), 1);
        assert!(store.provider_hold("pragmatic").unwrap().is_some());
    }
    #[test]
    fn rejects_unready_local_and_invalid_samples_before_campaign() {
        let (_d, _s, mut plan, mut inventory) = fixture();
        let executor = fake(false);
        plan.jobs[0].samples = 0;
        assert!(
            validate_plan(&plan, &inventory, executor.as_ref(), &RunOptions::default()).is_err()
        );
        plan.jobs[0].samples = 1;
        inventory.providers[0].games[0].ready = false;
        assert!(
            validate_plan(&plan, &inventory, executor.as_ref(), &RunOptions::default()).is_err()
        );
        inventory.providers[0].games[0].ready = true;
        inventory.providers[0].games[0].modes[0].execution_source = Some("local_model".into());
        assert!(
            validate_plan(&plan, &inventory, executor.as_ref(), &RunOptions::default()).is_err()
        );
    }
    #[test]
    fn prerequisite_modes_require_explicit_suite_and_bounded_budget() {
        let (_d, _store, mut plan, mut inventory) = fixture();
        plan.jobs.truncate(1);
        inventory.providers[0].games[0].modes[0].requires_prerequisites = json!(["offered bonus"]);
        let executor = fake(false);
        for settings in [
            Value::Null,
            json!({"executor":"suite"}),
            json!({"executor":"suite","max_prerequisite_rounds":0}),
            json!({"executor":"suite","max_prerequisite_rounds":101}),
            json!({"executor":"suite","max_prerequisite_rounds":1.5}),
            json!({"executor":"native","max_prerequisite_rounds":1}),
        ] {
            plan.jobs[0].settings = settings;
            assert!(
                validate_plan(&plan, &inventory, executor.as_ref(), &RunOptions::default())
                    .is_err()
            );
        }
        for budget in [1, 100] {
            plan.jobs[0].settings = json!({"executor":"suite","max_prerequisite_rounds":budget});
            assert!(
                validate_plan(&plan, &inventory, executor.as_ref(), &RunOptions::default()).is_ok()
            );
        }
    }
    #[test]
    fn full_inventory_sized_plans_preserve_finite_sample_limit() {
        let (_d, _store, mut plan, inventory) = fixture();
        let job = plan.jobs[0].clone();
        plan.jobs = vec![job; 20_063];
        let executor = fake(false);
        assert!(
            validate_plan(&plan, &inventory, executor.as_ref(), &RunOptions::default()).is_ok()
        );
        plan.jobs[0].samples = 1_000_000;
        for job in &mut plan.jobs[1..11] {
            job.samples = 1_000_000;
        }
        assert!(
            validate_plan(&plan, &inventory, executor.as_ref(), &RunOptions::default()).is_err()
        );
    }
    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn serializes_provider_aliases_but_parallelizes_different_providers_and_is_idempotent() {
        let (_d, store, plan, _) = fixture();
        let mut executor = fake(false);
        Arc::get_mut(&mut executor).unwrap().rendezvous = Some(tokio::sync::Barrier::new(2));
        let cancel = Arc::new(AtomicBool::new(false));
        let first = run(
            store.clone(),
            plan.clone(),
            RunOptions::default(),
            executor.clone(),
            cancel.clone(),
            None,
        )
        .await
        .unwrap();
        assert!(first.completed);
        assert_eq!(store.rounds().unwrap().len(), 6);
        assert!(*executor.maximum.lock().unwrap() >= 2);
        let second = run(
            store,
            plan,
            RunOptions::default(),
            executor.clone(),
            cancel,
            None,
        )
        .await
        .unwrap();
        assert!(second.completed);
        assert_eq!(*executor.seen.lock().unwrap(), 6);
    }
    #[tokio::test]
    async fn verified_runnable_samples_do_not_complete_omitted_inventory_modes() {
        let (_d, store, mut plan, _) = fixture();
        plan.coverage = Some(
            json!({"inventory_complete":false,"omitted_modes":[{"provider":"pragmatic","game":"g","mode":"purchase"}]}),
        );
        let report = run(
            store,
            plan,
            RunOptions::default(),
            fake(false),
            Arc::new(AtomicBool::new(false)),
            None,
        )
        .await
        .unwrap();
        assert!(report.runnable_completed);
        assert!(!report.completed);
        assert_eq!(report.status_counts.get("verified"), Some(&6));
    }
    #[tokio::test]
    async fn lost_response_survives_restart_and_never_replays() {
        let (_d, store, mut plan, _) = fixture();
        plan.jobs.truncate(1);
        let executor = fake(true);
        let cancel = Arc::new(AtomicBool::new(false));
        let report = run(
            store.clone(),
            plan.clone(),
            RunOptions::default(),
            executor.clone(),
            cancel.clone(),
            None,
        )
        .await
        .unwrap();
        assert!(!report.completed);
        assert_eq!(store.rounds().unwrap()[0].status, RoundStatus::Uncertain);
        let restarted = Store::open(store.root()).unwrap();
        let report = run(
            restarted,
            plan,
            RunOptions::default(),
            executor.clone(),
            cancel,
            None,
        )
        .await
        .unwrap();
        assert!(!report.completed);
        assert_eq!(*executor.seen.lock().unwrap(), 1);
    }
    #[tokio::test]
    async fn failed_validation_holds_provider_and_same_plan_never_skips_failure() {
        struct BadOutcome(Arc<Fake>);
        #[async_trait]
        impl Executor for BadOutcome {
            fn validate(&self, p: &str, g: &Game, m: &Mode, s: &Value) -> Result<()> {
                self.0.validate(p, g, m, s)
            }
            async fn execute(
                &self,
                c: &RunContext,
                p: &str,
                g: &Game,
                m: &Mode,
                s: &Value,
            ) -> Result<RoundOutcome> {
                let mut outcome = self.0.execute(c, p, g, m, s).await?;
                outcome.payout = "1".into(); // Native payout contradicts final wallet.
                Ok(outcome)
            }
        }
        let (_d, store, mut plan, _) = fixture();
        plan.jobs.truncate(1);
        let normal = fake(false);
        let bad = Arc::new(BadOutcome(normal.clone()));
        let cancel = Arc::new(AtomicBool::new(false));
        let first = run(
            store.clone(),
            plan.clone(),
            RunOptions::default(),
            bad,
            cancel.clone(),
            None,
        )
        .await
        .unwrap();
        assert!(!first.completed);
        assert_eq!(
            store.rounds().unwrap()[0].status,
            RoundStatus::ValidationFailed
        );
        assert!(store.provider_hold("pragmatic").unwrap().is_some());
        store
            .release_provider_hold("pragmatic", "operator reviewed closed-round discrepancy")
            .unwrap();
        let second = run(
            store.clone(),
            plan,
            RunOptions::default(),
            normal.clone(),
            cancel,
            None,
        )
        .await
        .unwrap();
        assert!(!second.completed);
        assert_eq!(*normal.seen.lock().unwrap(), 1);
        assert_eq!(store.rounds().unwrap().len(), 1);
        let db = rusqlite::Connection::open(store.root().join("runner.sqlite3")).unwrap();
        let actions: i64 = db
            .query_row(
                "SELECT COUNT(*) FROM operator_actions WHERE action='release_hold'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(actions, 1);
    }
}
