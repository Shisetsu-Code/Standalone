//! Complete inventory planning. Omitted modes remain explicit coverage gaps.
//! Planning never launches games or sends provider requests.
use crate::{adapters, bindings, engine::Executor, model::*, store::Store, suite};
use anyhow::{Context, Result, ensure};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet, HashSet},
    path::{Path, PathBuf},
};

pub struct PlanOptions {
    pub providers: Vec<String>,
    pub games: Vec<String>,
    pub samples: u32,
    /// Public settings: {provider: {game_id: {...}, "*": {...}}}.
    pub settings: Value,
    pub suite_root: Option<PathBuf>,
    pub python: String,
    pub max_prerequisite_rounds: u32,
}
impl Default for PlanOptions {
    fn default() -> Self {
        Self {
            providers: vec![],
            games: vec![],
            samples: 1,
            settings: json!({}),
            suite_root: None,
            python: if cfg!(windows) { "python" } else { "python3" }.into(),
            max_prerequisite_rounds: 0,
        }
    }
}

fn has_prerequisites(mode: &Mode) -> bool {
    let p = &mode.requires_prerequisites;
    !(p.is_null()
        || p == false
        || p.as_array().is_some_and(Vec::is_empty)
        || p.as_object().is_some_and(serde_json::Map::is_empty))
}

fn merge(target: &mut Value, value: &Value) -> Result<()> {
    ensure!(value.is_object(), "public settings entries must be objects");
    let target = target
        .as_object_mut()
        .context("public settings must be an object")?;
    for (key, value) in value.as_object().unwrap() {
        target.insert(key.clone(), value.clone());
    }
    Ok(())
}

fn overrides(options: &PlanOptions, provider: &str, game: &str) -> Result<Value> {
    let mut result = json!({});
    if let Some(provider) = options.settings.get(provider) {
        ensure!(
            provider.is_object(),
            "provider settings must map game ids to objects"
        );
        if let Some(value) = provider.get("*") {
            merge(&mut result, value)?;
        }
        if let Some(value) = provider.get(game) {
            merge(&mut result, value)?;
        }
    }
    Ok(result)
}

pub fn plan_all(
    inventory: &InventorySnapshot,
    repo: &Path,
    id: &str,
    options: &PlanOptions,
) -> Result<CampaignPlan> {
    ensure!(
        !id.trim().is_empty() && id.len() <= 128,
        "invalid campaign id"
    );
    ensure!(
        (1..=1_000_000).contains(&options.samples),
        "samples must be 1..1000000"
    );
    ensure!(
        options.max_prerequisite_rounds <= 100,
        "prerequisite budget must be 0..100"
    );
    ensure!(
        options.settings.is_object(),
        "settings must map provider ids to game settings"
    );
    for provider in &options.providers {
        ensure!(
            inventory.providers.iter().any(|p| &p.id == provider),
            "unknown provider filter: {provider}"
        );
    }
    let selected: Vec<_> = inventory
        .providers
        .iter()
        .filter(|p| options.providers.is_empty() || options.providers.contains(&p.id))
        .collect();
    for game in &options.games {
        ensure!(
            selected
                .iter()
                .any(|p| p.games.iter().any(|g| &g.id == game)),
            "unknown game filter: {game}"
        );
    }
    let suite_root = options
        .suite_root
        .as_ref()
        .map(|path| path.canonicalize().context("suite directory unavailable"))
        .transpose()?;
    let mut jobs = Vec::new();
    let mut gaps = Vec::new();
    let mut omitted_games = Vec::new();
    let mut omitted_providers = Vec::new();
    let mut aliases = Vec::new();
    let mut canonical_jobs = BTreeMap::<(String, String, String), (usize, Value)>::new();
    let mut inventory_modes = 0usize;
    let mut inventory_games = 0usize;
    let mut kinds = BTreeMap::<String, usize>::new();
    for provider in selected {
        if provider.games.is_empty() {
            omitted_providers
                .push(json!({"provider":provider.id,"reason":"provider_without_inventory"}));
        }
        for game in provider
            .games
            .iter()
            .filter(|g| options.games.is_empty() || options.games.contains(&g.id))
        {
            inventory_games += 1;
            if game.modes.is_empty() {
                omitted_games.push(json!({"provider":provider.id,"game":game.id,
                    "reason":"game_without_declared_modes","details":game.block_reason}));
                continue;
            }
            let explicit = overrides(options, &provider.id, &game.id)?;
            // Resolve each game's binding once, even when it declares many modes.
            let native_binding = bindings::from_repo(repo, &provider.id, game);
            for mode in &game.modes {
                inventory_modes += 1;
                let native_progression = provider.id == "netent"
                    && adapters::netent_horizon::requires_progression(game, mode);
                let eligibility_gap = if provider.id == "kendoo" {
                    Some("provider_paused")
                } else if !provider.ready || !provider.campaign_eligible {
                    Some("provider_ineligible")
                } else if !game.ready {
                    Some("game_not_ready")
                } else if !mode.ready {
                    Some("mode_not_ready")
                } else if mode.execution_source.as_deref() == Some("local_model") {
                    Some("local_model_only")
                } else if (has_prerequisites(mode) || native_progression)
                    && options.max_prerequisite_rounds == 0
                    && explicit["max_prerequisite_rounds"].as_u64().unwrap_or(0) == 0
                {
                    Some("prerequisite_budget_required")
                } else {
                    None
                };
                let mut settings = None;
                let mut details = Vec::new();
                if eligibility_gap.is_none() {
                    let redtiger_direct = provider.id == "redtiger"
                        && explicit["suite_root"].as_str().map(std::path::Path::new)
                            .or(suite_root.as_deref()).is_some_and(|root| {
                            root.join("bet-collector/collection_redtiger_http.py").is_file()
                        });
                    if explicit["executor"] != "suite"
                        && !redtiger_direct
                        && (!has_prerequisites(mode) || native_progression)
                        && adapters::supports(&provider.id, game, mode)
                    {
                        let mut native = native_binding
                            .as_ref()
                            .cloned()
                            .unwrap_or_else(|_| json!({}));
                        if native_progression {
                            native["max_prerequisite_rounds"] =
                                json!(options.max_prerequisite_rounds);
                        }
                        merge(&mut native, &explicit)?;
                        match adapters::NativeExecutor.validate(&provider.id, game, mode, &native) {
                            Ok(()) => settings = Some(native),
                            Err(error) => details.push(format!("native: {error:#}")),
                        }
                    }
                    if settings.is_none()
                        && (suite_root.is_some() || explicit["executor"] == "suite")
                    {
                        let mut bridge = json!({"executor":"suite", "python":options.python,
                            "max_prerequisite_rounds":options.max_prerequisite_rounds});
                        if let Some(root) = &suite_root {
                            bridge["suite_root"] = json!(root);
                        }
                        merge(&mut bridge, &explicit)?;
                        bridge["executor"] = json!("suite");
                        match suite::preflight(&provider.id, game, mode, &bridge) {
                            Ok(()) => settings = Some(bridge),
                            Err(error) => details.push(format!("suite: {error:#}")),
                        }
                    }
                }
                if let Some(settings) = settings {
                    let key = (
                        canonical_provider(&provider.id).to_owned(),
                        game.id.clone(),
                        mode.key.clone(),
                    );
                    let identity = json!({"type":mode.kind.as_str(),"prerequisites":mode.requires_prerequisites,"execution_source":mode.execution_source,"settings":settings});
                    if let Some((job_index, original)) = canonical_jobs.get(&key) {
                        if original == &identity {
                            aliases.push(json!({"provider":provider.id,"game":game.id,"mode":mode.key,"job_index":job_index}));
                        } else {
                            gaps.push(json!({"provider":provider.id,"game":game.id,"mode":mode.key,
                                "type":mode.kind.as_str(),"reason":"canonical_mode_binding_conflict","details":["Canonical alias declares a different kind, prerequisite or public setting"]}));
                        }
                        continue;
                    }
                    canonical_jobs.insert(key, (jobs.len(), identity));
                    *kinds.entry(mode.kind.as_str().into()).or_default() += 1;
                    jobs.push(Job {
                        provider: provider.id.clone(),
                        game: game.id.clone(),
                        mode: mode.key.clone(),
                        samples: options.samples,
                        settings,
                    });
                } else {
                    if provider.id == "irondog" && eligibility_gap.is_none() {
                        details.insert(0, "No independently observed closing balance in the reviewed Iron Dog demo evidence".into());
                    }
                    if provider.id == "habanero"
                        && let Some(detail) = adapters::habanero::missing_binding_detail(game, mode)
                    {
                        details.insert(0, detail.into());
                    }
                    if details.is_empty() && eligibility_gap.is_none() {
                        details.push("No executable native binding; supply --suite-root for existing suite contracts or explicit public settings".into());
                    }
                    gaps.push(json!({"provider":provider.id,"game":game.id,"mode":mode.key,
                        "type":mode.kind.as_str(),"reason":eligibility_gap.unwrap_or("executor_or_binding_unavailable"),"details":details}));
                }
            }
        }
    }
    ensure!(
        jobs.len() <= 100_000 && jobs.len() as u64 * u64::from(options.samples) <= 10_000_000,
        "campaign exceeds finite sample limits"
    );
    let coverage = json!({"schema_version":1,"scope":"all_modes","selected_providers":options.providers,
        "selected_games":options.games,"inventory_game_count":inventory_games,"inventory_mode_count":inventory_modes,
        "planned_mode_count":jobs.len(),"planned_modes_by_type":kinds,"omitted_mode_count":gaps.len(),
        "omitted_game_count":omitted_games.len(),"omitted_games":omitted_games,"alias_mode_count":aliases.len(),"alias_modes":aliases,
        "omitted_provider_count":omitted_providers.len(),"omitted_providers":omitted_providers,
        "inventory_complete":inventory_modes > 0 && gaps.is_empty() && omitted_games.is_empty() && omitted_providers.is_empty(),"omitted_modes":gaps});
    Ok(CampaignPlan {
        schema_version: 1,
        id: id.into(),
        inventory_id: inventory.id.clone(),
        coverage: Some(coverage),
        jobs,
    })
}

/// Coverage is checked against the pinned inventory, never trusted as a flag
/// supplied by an editable plan. Every selected identity has exactly one entry.
pub fn validate_coverage(plan: &CampaignPlan, inventory: &InventorySnapshot) -> Result<()> {
    let Some(coverage) = &plan.coverage else {
        return Ok(());
    };
    if coverage["scope"] != "all_modes" {
        ensure!(
            coverage["inventory_complete"] != true,
            "complete coverage requires an all_modes inventory partition"
        );
        return Ok(());
    }
    let providers: Vec<String> = serde_json::from_value(coverage["selected_providers"].clone())
        .context("coverage provider filters missing")?;
    let games: Vec<String> = serde_json::from_value(coverage["selected_games"].clone())
        .context("coverage game filters missing")?;
    let mut expected = BTreeSet::new();
    let mut empty_games = BTreeSet::new();
    let mut empty_providers = BTreeSet::new();
    let mut game_count = 0usize;
    for provider in inventory
        .providers
        .iter()
        .filter(|p| providers.is_empty() || providers.contains(&p.id))
    {
        if provider.games.is_empty() {
            empty_providers.insert(provider.id.clone());
        }
        for game in provider
            .games
            .iter()
            .filter(|g| games.is_empty() || games.contains(&g.id))
        {
            game_count += 1;
            if game.modes.is_empty() {
                empty_games.insert((provider.id.clone(), game.id.clone()));
            }
            for mode in &game.modes {
                expected.insert((provider.id.clone(), game.id.clone(), mode.key.clone()));
            }
        }
    }
    let mode_count = expected.len();
    let empty_game_count = empty_games.len();
    let empty_provider_count = empty_providers.len();
    let identity = |value: &Value| -> Result<(String, String, String)> {
        Ok((
            value["provider"]
                .as_str()
                .context("coverage provider missing")?
                .into(),
            value["game"]
                .as_str()
                .context("coverage game missing")?
                .into(),
            value["mode"]
                .as_str()
                .context("coverage mode missing")?
                .into(),
        ))
    };
    for job in &plan.jobs {
        ensure!(
            expected.remove(&(job.provider.clone(), job.game.clone(), job.mode.clone())),
            "duplicate or out-of-scope coverage job"
        );
    }
    let aliases = coverage["alias_modes"]
        .as_array()
        .context("coverage aliases missing")?;
    for alias in aliases {
        let key = identity(alias)?;
        ensure!(
            expected.remove(&key),
            "duplicate or out-of-scope coverage alias"
        );
        let index = usize::try_from(
            alias["job_index"]
                .as_u64()
                .context("alias job index missing")?,
        )?;
        let job = plan
            .jobs
            .get(index)
            .context("alias job index unavailable")?;
        ensure!(
            canonical_provider(&key.0) == canonical_provider(&job.provider)
                && key.1 == job.game
                && key.2 == job.mode,
            "alias does not identify the same canonical mode"
        );
        let (_, _, mode) = inventory.lookup(&key.0, &key.1, &key.2)?;
        let (_, _, original) = inventory.lookup(&job.provider, &job.game, &job.mode)?;
        ensure!(
            mode.kind == original.kind
                && mode.requires_prerequisites == original.requires_prerequisites
                && mode.execution_source == original.execution_source,
            "alias mode contract differs"
        );
    }
    let gaps = coverage["omitted_modes"]
        .as_array()
        .context("coverage mode gaps missing")?;
    for gap in gaps {
        ensure!(
            expected.remove(&identity(gap)?),
            "duplicate or out-of-scope coverage gap"
        );
    }
    let game_gaps = coverage["omitted_games"]
        .as_array()
        .context("coverage game gaps missing")?;
    for gap in game_gaps {
        let provider = gap["provider"]
            .as_str()
            .context("coverage game provider missing")?;
        let game = gap["game"].as_str().context("coverage game id missing")?;
        ensure!(
            empty_games.remove(&(provider.into(), game.into())),
            "duplicate or out-of-scope empty game gap"
        );
    }
    let provider_gaps = coverage["omitted_providers"]
        .as_array()
        .context("coverage provider gaps missing")?;
    for gap in provider_gaps {
        ensure!(
            empty_providers.remove(
                gap["provider"]
                    .as_str()
                    .context("coverage provider id missing")?
            ),
            "duplicate or out-of-scope empty provider gap"
        );
    }
    ensure!(
        expected.is_empty() && empty_games.is_empty() && empty_providers.is_empty(),
        "coverage omits selected inventory identities"
    );
    for (field, count) in [
        ("inventory_game_count", game_count),
        ("inventory_mode_count", mode_count),
        ("planned_mode_count", plan.jobs.len()),
        ("alias_mode_count", aliases.len()),
        ("omitted_mode_count", gaps.len()),
        ("omitted_game_count", empty_game_count),
        ("omitted_provider_count", empty_provider_count),
    ] {
        ensure!(
            coverage[field].as_u64() == Some(count as u64),
            "coverage count differs: {field}"
        );
    }
    let complete =
        mode_count > 0 && gaps.is_empty() && game_gaps.is_empty() && provider_gaps.is_empty();
    ensure!(
        coverage["inventory_complete"].as_bool() == Some(complete),
        "coverage completion differs from its inventory partition"
    );
    Ok(())
}

pub fn report(store: &Store, plan: &CampaignPlan) -> Result<Value> {
    ensure!(
        plan.schema_version == 1
            && plan
                .jobs
                .iter()
                .all(|job| (1..=1_000_000).contains(&job.samples)),
        "invalid plan or zero-sample coverage"
    );
    match store.campaign(&plan.id) {
        Ok(stored) => ensure!(
            serde_json::to_value(&stored)? == serde_json::to_value(plan)?,
            "supplied plan differs from the immutable stored campaign"
        ),
        Err(error)
            if matches!(
                error.downcast_ref::<rusqlite::Error>(),
                Some(rusqlite::Error::QueryReturnedNoRows)
            ) => {}
        Err(error) => return Err(error.context("cannot inspect stored campaign")),
    }
    if plan
        .coverage
        .as_ref()
        .is_some_and(|c| c["scope"] == "all_modes")
    {
        validate_coverage(
            plan,
            &store
                .inventory(Some(&plan.inventory_id))
                .context("import the pinned inventory before reporting coverage")?,
        )?;
    }
    let rounds = store.rounds()?;
    let mut by_job = BTreeMap::<u32, Vec<&RoundRecord>>::new();
    for round in rounds.iter().filter(|r| r.spec.campaign_id == plan.id) {
        ensure!(
            (round.spec.job_index as usize) < plan.jobs.len(),
            "receipt references an absent campaign job"
        );
        by_job.entry(round.spec.job_index).or_default().push(round);
    }
    let mut rows = Vec::new();
    let mut total_verified = 0usize;
    let mut verified_modes = 0usize;
    for (index, job) in plan.jobs.iter().enumerate() {
        let samples = by_job
            .get(&(index as u32))
            .map(Vec::as_slice)
            .unwrap_or(&[]);
        let mut counts = BTreeMap::<String, usize>::new();
        let mut verified = HashSet::new();
        for round in samples {
            ensure!(
                round.spec.inventory_id == plan.inventory_id
                    && round.spec.provider == job.provider
                    && round.spec.game == job.game
                    && round.spec.mode == job.mode
                    && round.spec.settings == job.settings
                    && round.spec.sample_index < job.samples,
                "receipt does not match the requested campaign job"
            );
            *counts.entry(round.status.as_str().into()).or_default() += 1;
            if round.status == RoundStatus::Verified {
                verified.insert(round.spec.sample_index);
            }
        }
        let complete = verified.len() == job.samples as usize && samples.len() == verified.len();
        if complete {
            verified_modes += 1;
        }
        total_verified += verified.len();
        rows.push(
            json!({"provider":job.provider,"game":job.game,"mode":job.mode,"samples":job.samples,
            "verified_samples":verified.len(),"status_counts":counts,"completed":complete}),
        );
    }
    let runnable_completed = !plan.jobs.is_empty() && verified_modes == plan.jobs.len();
    let inventory_complete = plan
        .coverage
        .as_ref()
        .is_some_and(|c| c["inventory_complete"] == true);
    Ok(
        json!({"campaign_id":plan.id,"inventory_id":plan.inventory_id,"planned_modes":plan.jobs.len(),
        "verified_modes":verified_modes,"verified_samples":total_verified,"runnable_completed":runnable_completed,
        "all_inventory_modes_completed":runnable_completed && inventory_complete,
        "planning_coverage":plan.coverage,"modes":rows}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    fn inventory() -> InventorySnapshot {
        let modes = [
            ("normal", ModeKind::Normal),
            ("bonus", ModeKind::Purchase),
            ("boost", ModeKind::Booster),
            ("special", ModeKind::Special),
        ]
        .into_iter()
        .map(|(key, kind)| Mode {
            key: key.into(),
            kind,
            label: key.into(),
            ready: true,
            requires_prerequisites: Value::Null,
            execution_source: None,
        })
        .collect();
        InventorySnapshot {
            id: "fixture".into(),
            sources: vec![],
            providers: vec![ProviderInventory {
                id: "hacksaw".into(),
                name: "Hacksaw".into(),
                ready: true,
                campaign_eligible: true,
                protocol: Value::Null,
                games: vec![Game {
                    id: "2405".into(),
                    name: "Fixture".into(),
                    ready: true,
                    block_reason: String::new(),
                    modes,
                }],
            }],
        }
    }
    #[test]
    fn all_mode_plan_keeps_purchases_boosters_and_explicit_gaps() {
        let inv = inventory();
        let plan = plan_all(&inv, Path::new("."), "all", &PlanOptions::default()).unwrap();
        assert_eq!(
            plan.jobs
                .iter()
                .map(|j| j.mode.as_str())
                .collect::<Vec<_>>(),
            ["normal", "bonus", "boost"]
        );
        let coverage = plan.coverage.unwrap();
        assert_eq!(coverage["inventory_mode_count"], 4);
        assert_eq!(coverage["inventory_complete"], false);
        assert_eq!(coverage["omitted_modes"][0]["mode"], "special");
    }
    #[test]
    fn rejects_unknown_filters_and_preserves_conditional_gap() {
        let mut inv = inventory();
        inv.providers[0].games[0].modes[1].requires_prerequisites = json!(["free_spins"]);
        let plan = plan_all(&inv, Path::new("."), "conditional", &PlanOptions::default()).unwrap();
        assert!(
            plan.coverage.unwrap()["omitted_modes"]
                .as_array()
                .unwrap()
                .iter()
                .any(|g| g["mode"] == "bonus" && g["reason"] == "prerequisite_budget_required")
        );
        let options = PlanOptions {
            providers: vec!["typo".into()],
            ..Default::default()
        };
        assert!(plan_all(&inv, Path::new("."), "typo", &options).is_err());
    }
    #[test]
    fn unexecuted_coverage_is_not_a_completed_campaign() {
        let inv = inventory();
        let plan = plan_all(&inv, Path::new("."), "coverage", &PlanOptions::default()).unwrap();
        let dir = tempfile::tempdir().unwrap();
        let store = Store::open(dir.path()).unwrap();
        store.install_inventory(&inv).unwrap();
        let coverage = report(&store, &plan).unwrap();
        assert_eq!(coverage["runnable_completed"], false);
        assert_eq!(coverage["all_inventory_modes_completed"], false);
        assert_eq!(coverage["verified_samples"], 0);
    }
    #[test]
    fn games_without_modes_remain_explicit_gaps() {
        let mut inv = inventory();
        inv.providers[0].games[0].modes.pop();
        inv.providers[0].games.push(Game {
            id: "pending".into(),
            name: "Pending".into(),
            ready: false,
            block_reason: "missing contract".into(),
            modes: vec![],
        });
        let plan = plan_all(&inv, Path::new("."), "empty", &PlanOptions::default()).unwrap();
        let coverage = plan.coverage.unwrap();
        assert_eq!(coverage["omitted_mode_count"], 0);
        assert_eq!(coverage["omitted_game_count"], 1);
        assert_eq!(coverage["inventory_complete"], false);
    }
    #[test]
    fn coverage_rejects_a_modified_plan_with_the_same_id() {
        let inv = inventory();
        let mut plan =
            plan_all(&inv, Path::new("."), "immutable", &PlanOptions::default()).unwrap();
        let dir = tempfile::tempdir().unwrap();
        let store = Store::open(dir.path()).unwrap();
        store.install_inventory(&inv).unwrap();
        store.create_campaign(&plan).unwrap();
        plan.jobs[0].game = "different".into();
        assert!(
            report(&store, &plan)
                .unwrap_err()
                .to_string()
                .contains("immutable")
        );
    }
    #[test]
    fn canonical_aliases_link_to_one_paid_job() {
        let mut inv = inventory();
        let provider = &mut inv.providers[0];
        provider.id = "pragmatic".into();
        provider.games[0].modes.truncate(1);
        let mut alias = provider.clone();
        alias.id = "reelkingdom".into();
        inv.providers.push(alias);
        let plan = plan_all(&inv, Path::new("."), "aliases", &PlanOptions::default()).unwrap();
        validate_coverage(&plan, &inv).unwrap();
        assert_eq!(plan.jobs.len(), 1);
        let coverage = plan.coverage.unwrap();
        assert_eq!(coverage["inventory_mode_count"], 2);
        assert_eq!(coverage["alias_mode_count"], 1);
        assert_eq!(coverage["inventory_complete"], true);
    }
    #[test]
    fn edited_coverage_cannot_hide_jobs_or_certify_zero_samples() {
        let mut inv = inventory();
        inv.providers[0].games[0].modes.pop();
        let mut plan = plan_all(&inv, Path::new("."), "edited", &PlanOptions::default()).unwrap();
        validate_coverage(&plan, &inv).unwrap();
        plan.jobs.pop();
        assert!(validate_coverage(&plan, &inv).is_err());
        plan.jobs[0].samples = 0;
        let dir = tempfile::tempdir().unwrap();
        let store = Store::open(dir.path()).unwrap();
        assert!(report(&store, &plan).is_err());
    }
    #[test]
    fn a_selected_provider_without_inventory_remains_incomplete() {
        let mut inv = inventory();
        inv.providers[0].games[0].modes.pop();
        inv.providers.push(ProviderInventory {
            id: "missing".into(),
            name: "Missing".into(),
            ready: false,
            campaign_eligible: false,
            protocol: Value::Null,
            games: vec![],
        });
        let plan = plan_all(
            &inv,
            Path::new("."),
            "missing-inventory",
            &PlanOptions::default(),
        )
        .unwrap();
        validate_coverage(&plan, &inv).unwrap();
        assert_eq!(plan.coverage.as_ref().unwrap()["omitted_provider_count"], 1);
        assert_eq!(plan.coverage.as_ref().unwrap()["inventory_complete"], false);
    }
}
