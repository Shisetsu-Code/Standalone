//! A bounded, reviewed live check: one normal sample per supported inventory ID.
//! Planning and reporting are local operations and never contact a provider.
use crate::{adapters, bindings, engine::Executor, export, model::*, store::Store};
use anyhow::{Result, ensure};
use serde_json::{Value, json};
use std::path::Path;

const INVENTORY_ID: &str = "3158af3b9f88acab5278e6addd5e34ca94fcbf5fa5e2229323cef7e056ca90c4";

#[derive(Debug, Clone)]
pub struct Prepared {
    pub plan: CampaignPlan,
    providers: Vec<Selection>,
}

#[derive(Debug, Clone)]
struct Selection {
    provider: String,
    name: String,
    game: Option<String>,
    mode: Option<String>,
    preflight: &'static str,
}

fn target(provider: &str) -> Option<(&'static str, &'static str)> {
    // Reviewed slots in the pinned inventory. Do not substitute another game
    // after a rejection, nor extrapolate these choices to a later inventory.
    match provider {
        "pragmatic" => Some(("vs20wildparty", "normal")),
        "endorphina" => Some(("525", "normal")),
        "hacksaw" => Some(("2405", "normal")),
        "peterandsons" => Some(("royal-hunt", "main")),
        "playson" => Some(("lucky-pots-x1000", "Spin")),
        "reelkingdom" => Some(("vs10gdchalleng", "normal")),
        _ => None,
    }
}

fn independent(mode: &Mode) -> bool {
    let prerequisites = &mode.requires_prerequisites;
    mode.kind == ModeKind::Normal
        && mode.ready
        && mode.execution_source.as_deref() != Some("local_model")
        && (prerequisites.is_null()
            || prerequisites.as_bool() == Some(false)
            || prerequisites.as_array().is_some_and(|a| a.is_empty())
            || prerequisites.as_object().is_some_and(|a| a.is_empty()))
}

pub fn prepare(inventory: &InventorySnapshot, repo: &Path, campaign_id: &str) -> Result<Prepared> {
    ensure!(
        inventory.id == INVENTORY_ID,
        "live smoke requires the reviewed inventory snapshot"
    );
    ensure!(
        inventory.providers.len() == 35,
        "live smoke requires all 35 inventory providers"
    );
    ensure!(
        !campaign_id.trim().is_empty() && campaign_id.len() <= 128,
        "invalid smoke campaign id"
    );
    let mut jobs = Vec::new();
    let mut providers = Vec::new();
    for provider in &inventory.providers {
        let chosen = target(&provider.id);
        let implemented = matches!(
            canonical_provider(&provider.id),
            "hacksaw" | "endorphina" | "peterandsons" | "playson" | "pragmatic"
        );
        let mut selection = Selection {
            provider: provider.id.clone(),
            name: provider.name.clone(),
            game: chosen.map(|(game, _)| game.into()),
            mode: chosen.map(|(_, mode)| mode.into()),
            preflight: "no_reviewed_target",
        };
        selection.preflight = if provider.id == "kendoo" {
            "paused"
        } else if !provider.ready || !provider.campaign_eligible {
            "ineligible"
        } else if !implemented {
            "unsupported_adapter"
        } else if let Some((game_id, mode_key)) = chosen {
            if let Some(game) = provider.games.iter().find(|g| g.id == game_id && g.ready) {
                if let Some(mode) = game.modes.iter().find(|m| {
                    m.key == mode_key && independent(m) && adapters::supports(&provider.id, game, m)
                }) {
                    match bindings::from_repo(repo, &provider.id, game) {
                        Ok(settings)
                            if adapters::NativeExecutor
                                .validate(&provider.id, game, mode, &settings)
                                .is_ok() =>
                        {
                            jobs.push(Job {
                                provider: provider.id.clone(),
                                game: game.id.clone(),
                                mode: mode.key.clone(),
                                samples: 1,
                                settings,
                            });
                            "ready"
                        }
                        _ => "missing_binding",
                    }
                } else {
                    "no_reviewed_target"
                }
            } else {
                "no_reviewed_target"
            }
        } else {
            "no_reviewed_target"
        };
        providers.push(selection);
    }
    Ok(Prepared {
        plan: CampaignPlan {
            schema_version: 1,
            id: campaign_id.into(),
            inventory_id: inventory.id.clone(),
            coverage: None,
            jobs,
        },
        providers,
    })
}

fn public_stage(label: &str) -> &'static str {
    match label {
        "version" => "version",
        "partnerSettings" => "partnerSettings",
        "authenticate" => "authenticate",
        "bet" => "bet",
        "official_play" => "official_play",
        "demo_launcher" => "demo_launcher",
        "launch" => "launch",
        "game_feature_config" => "game_feature_config",
        "websocket_handshake" => "websocket_handshake",
        "GET_PAYTABLE_INFO" => "GET_PAYTABLE_INFO",
        "GET_BALANCE" => "GET_BALANCE",
        "GET_LAST_GAME" => "GET_LAST_GAME",
        "GET_DYNAMIC_HELP_INFO" => "GET_DYNAMIC_HELP_INFO",
        "START_GAME" => "START_GAME",
        "START_FEATURE" => "START_FEATURE",
        "STEP_FEATURE" => "STEP_FEATURE",
        "END_FEATURE" => "END_FEATURE",
        "END_GAME" => "END_GAME",
        "pragmatic_launch" => "pragmatic_launch",
        "public_bootstrap" => "public_bootstrap",
        "doInit" => "doInit",
        "doSpin" => "doSpin",
        "doCollect" => "doCollect",
        "doBonus" => "doBonus",
        "doFSOption" => "doFSOption",
        "doMysteryScatter" => "doMysteryScatter",
        "doCollectBonus" => "doCollectBonus",
        "configuration" => "configuration",
        "authentication" => "authentication",
        "recovery" => "recovery",
        "information" => "information",
        "play" => "play",
        "conditional_offer" => "conditional_offer",
        "take_round" => "take_round",
        "complete" => "complete",
        "official_launch" => "official_launch",
        "native_source" => "native_source",
        "connect" => "connect",
        "reconnect" => "reconnect",
        "sync" => "sync",
        "bonus" => "bonus",
        "next" => "next",
        "game" => "game",
        _ => "unknown_stage",
    }
}

fn is_http(exchange: &ExchangeRecord) -> bool {
    exchange.request.transport == "http"
        || (exchange.request.transport == "websocket" && exchange.request.method == "CONNECT")
}

fn declared_challenge(exchanges: &[ExchangeRecord]) -> bool {
    exchanges.iter().filter(|e| is_http(e)).any(|e| {
        e.response.as_ref().is_some_and(|response| {
            response.status == 403
                && response.headers.iter().any(|(key, value)| {
                    key.eq_ignore_ascii_case("cf-mitigated")
                        && value.eq_ignore_ascii_case("challenge")
                })
        })
    })
}

fn reason(round: &RoundRecord, exchanges: &[ExchangeRecord], challenge: bool) -> &'static str {
    match round.status {
        RoundStatus::Verified => "native_round_verified",
        RoundStatus::ValidationFailed => "native_validation_failed",
        RoundStatus::Uncertain => "financial_outcome_uncertain",
        RoundStatus::Prepared | RoundStatus::InFlight | RoundStatus::Open => "round_pending",
        RoundStatus::Blocked if challenge => "declared_http_challenge",
        RoundStatus::Blocked => {
            if exchanges
                .iter()
                .filter(|e| is_http(e))
                .any(|e| e.response.as_ref().is_some_and(|r| r.status >= 400))
            {
                "http_rejected"
            } else if exchanges.iter().any(|e| e.error.is_some()) {
                "transport_failure"
            } else if exchanges.is_empty() {
                "pre_request_failure"
            } else {
                "native_protocol_failure"
            }
        }
    }
}

pub fn report(store: &Store, prepared: &Prepared) -> Result<Value> {
    let rounds: Vec<_> = store
        .rounds()?
        .into_iter()
        .filter(|r| r.spec.campaign_id == prepared.plan.id)
        .collect();
    for round in &rounds {
        let matching_job = prepared
            .plan
            .jobs
            .get(round.spec.job_index as usize)
            .is_some_and(|job| {
                job.provider == round.spec.provider
                    && job.game == round.spec.game
                    && job.mode == round.spec.mode
                    && job.samples == 1
                    && round.spec.sample_index == 0
                    && round.spec.kind == ModeKind::Normal
                    && round.spec.inventory_id == prepared.plan.inventory_id
            });
        ensure!(
            matching_job,
            "recorded round does not belong to the reviewed smoke plan"
        );
    }
    let mut providers = Vec::new();
    let mut attempted = 0usize;
    let mut verified = 0usize;
    for selected in &prepared.providers {
        let canonical = canonical_provider(&selected.provider);
        let own: Vec<_> = rounds
            .iter()
            .filter(|r| r.spec.provider == selected.provider)
            .collect();
        ensure!(
            own.len() <= 1,
            "more than one smoke sample recorded for a provider"
        );
        let round = own.first().copied();
        let exchanges = round
            .map(|r| store.exchanges(&r.id))
            .transpose()?
            .unwrap_or_default();
        let owner = round
            .map(|r| store.session(&r.id))
            .transpose()?
            .flatten()
            .is_some();
        let held = store.provider_hold(canonical)?.is_some();
        let challenge = declared_challenge(&exchanges);
        let has_attempt = !exchanges.is_empty();
        attempted += usize::from(has_attempt);
        verified += usize::from(round.is_some_and(|r| r.status == RoundStatus::Verified));
        let (execution, reason_code) = if let Some(round) = round {
            (round.status.as_str(), reason(round, &exchanges, challenge))
        } else if selected.preflight != "ready" {
            ("not_scheduled", selected.preflight)
        } else if held {
            ("not_started", "canonical_provider_held")
        } else if store.pending_provider(canonical)?.is_some() {
            ("not_started", "canonical_provider_pending")
        } else if rounds.iter().any(|r| {
            canonical_provider(&r.spec.provider) == canonical && r.status != RoundStatus::Verified
        }) {
            ("not_started", "canonical_provider_failed")
        } else {
            ("not_started", "not_attempted")
        };
        let http_events: Vec<_> = exchanges.iter().filter(|e| is_http(e)).map(|e| json!({
            "ordinal": e.ordinal,
            "transport": if e.request.transport == "http" { "http" } else { "websocket_handshake" },
            "stage": public_stage(&e.request.label),
            "status": e.response.as_ref().map(|r| r.status).filter(|status| (100..600).contains(status)),
        })).collect();
        providers.push(json!({
            "provider": selected.provider, "name": selected.name, "canonical_provider": canonical,
            "game": selected.game, "mode": selected.mode, "preflight": selected.preflight,
            "execution_status": execution, "reason_code": reason_code, "attempted": has_attempt,
            "round_id": round.map(|r| &r.id), "owner_persisted": owner,
            "exchange_count": exchanges.len(),
            "financial_intents": exchanges.iter().filter(|e| e.request.financial).count(),
            "financial_responses": exchanges.iter().filter(|e| e.request.financial && e.response.is_some()).count(),
            "http_events": http_events,
            "last_stage": exchanges.last().map(|e| public_stage(&e.request.label)),
            "declared_challenge": challenge, "canonical_provider_held": held,
            "round": round.map(export::public_round),
        }));
    }
    let ready = prepared
        .providers
        .iter()
        .filter(|p| p.preflight == "ready")
        .count();
    Ok(json!({
        "inventory_id": prepared.plan.inventory_id, "campaign_id": prepared.plan.id,
        "provider_count": providers.len(), "ready_provider_count": ready,
        "attempted_provider_count": attempted, "verified_provider_count": verified,
        "all_providers_verified": !providers.is_empty() && verified == providers.len(),
        "runnable_providers_verified": ready > 0 && verified == ready,
        "providers": providers,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{inventory, model::RoundOutcome};
    use serde_json::json;
    use std::collections::BTreeMap;

    fn repo() -> &'static Path {
        Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap()
    }

    fn published() -> InventorySnapshot {
        inventory::load_manifest(&repo().join("docs/recolector/inventario.json")).unwrap()
    }

    fn setup() -> (tempfile::TempDir, Store, Prepared) {
        let directory = tempfile::tempdir().unwrap();
        let store = Store::open(directory.path()).unwrap();
        let inventory = published();
        store.install_inventory(&inventory).unwrap();
        let prepared = prepare(&inventory, repo(), "synthetic-smoke").unwrap();
        store.create_campaign(&prepared.plan).unwrap();
        (directory, store, prepared)
    }

    fn round(store: &Store, prepared: &Prepared, provider: &str) -> RoundRecord {
        let (index, job) = prepared
            .plan
            .jobs
            .iter()
            .enumerate()
            .find(|(_, j)| j.provider == provider)
            .unwrap();
        store
            .create_round(&RoundSpec {
                campaign_id: prepared.plan.id.clone(),
                inventory_id: prepared.plan.inventory_id.clone(),
                job_index: index as u32,
                sample_index: 0,
                provider: provider.into(),
                game: job.game.clone(),
                mode: job.mode.clone(),
                kind: ModeKind::Normal,
                settings: job.settings.clone(),
            })
            .unwrap()
    }

    fn exchange(
        store: &Store,
        round: &RoundRecord,
        transport: &str,
        method: &str,
        label: &str,
        status: u16,
        financial: bool,
    ) {
        let ordinal = store
            .start_exchange(
                &round.id,
                &WireRequest {
                    label: label.into(),
                    transport: transport.into(),
                    method: method.into(),
                    url: "https://demo.example.invalid/?session=private-url-secret".into(),
                    headers: BTreeMap::from([(
                        "Authorization".into(),
                        "private-auth-secret".into(),
                    )]),
                    body: "private-request-secret".into(),
                    financial,
                },
            )
            .unwrap();
        let mut headers = BTreeMap::from([("x-private".into(), "private-header-secret".into())]);
        if status == 403 {
            headers.insert("Cf-Mitigated".into(), "challenge".into());
        }
        store
            .finish_exchange(
                &round.id,
                ordinal,
                &WireResponse {
                    status,
                    headers,
                    body: "private-response-secret".into(),
                    set_cookies: vec!["session=private-cookie-secret; Secure".into()],
                },
            )
            .unwrap();
    }

    fn provider<'a>(report: &'a Value, id: &str) -> &'a Value {
        report["providers"]
            .as_array()
            .unwrap()
            .iter()
            .find(|p| p["provider"] == id)
            .unwrap()
    }

    #[test]
    fn pinned_preflight_reports_all_35_and_schedules_only_reviewed_normal_samples() {
        let (_directory, store, prepared) = setup();
        assert_eq!(prepared.plan.jobs.len(), 5);
        assert_eq!(prepared.plan.inventory_id, INVENTORY_ID);
        let expected = [
            ("pragmatic", "vs20wildparty", "normal"),
            ("endorphina", "525", "normal"),
            ("hacksaw", "2405", "normal"),
            ("peterandsons", "royal-hunt", "main"),
            ("reelkingdom", "vs10gdchalleng", "normal"),
        ];
        for (job, expected) in prepared.plan.jobs.iter().zip(expected) {
            assert_eq!(
                (job.provider.as_str(), job.game.as_str(), job.mode.as_str()),
                expected
            );
            assert_eq!(job.samples, 1);
        }
        let report = report(&store, &prepared).unwrap();
        assert_eq!(report["provider_count"], 35);
        assert_eq!(report["ready_provider_count"], 5);
        assert_eq!(report["attempted_provider_count"], 0);
        assert_eq!(report["verified_provider_count"], 0);
        assert_eq!(report["all_providers_verified"], false);
        assert_eq!(report["runnable_providers_verified"], false);
        let mut counts = BTreeMap::<String, usize>::new();
        for entry in report["providers"].as_array().unwrap() {
            *counts
                .entry(entry["preflight"].as_str().unwrap().into())
                .or_default() += 1;
        }
        assert_eq!(
            counts,
            BTreeMap::from([
                ("ready".into(), 5),
                ("missing_binding".into(), 1),
                ("unsupported_adapter".into(), 25),
                ("paused".into(), 1),
                ("ineligible".into(), 3),
            ])
        );
        assert_eq!(
            provider(&report, "reelkingdom")["canonical_provider"],
            "pragmatic"
        );
        assert_eq!(provider(&report, "playson")["game"], "lucky-pots-x1000");
    }

    #[test]
    fn refuses_changed_inventory_or_unreviewed_substitution() {
        let mut inventory = published();
        inventory.id = "other-inventory".into();
        assert!(prepare(&inventory, repo(), "new-smoke").is_err());
        inventory.id = INVENTORY_ID.into();
        inventory
            .providers
            .iter_mut()
            .find(|p| p.id == "hacksaw")
            .unwrap()
            .games
            .iter_mut()
            .find(|g| g.id == "2405")
            .unwrap()
            .ready = false;
        let prepared = prepare(&inventory, repo(), "new-smoke").unwrap();
        assert!(!prepared.plan.jobs.iter().any(|j| j.provider == "hacksaw"));
        assert_eq!(
            prepared
                .providers
                .iter()
                .find(|p| p.provider == "hacksaw")
                .unwrap()
                .preflight,
            "no_reviewed_target"
        );
    }

    #[test]
    fn report_redacts_private_data_separates_http_from_ws_and_preserves_alias_stop() {
        let (_directory, store, prepared) = setup();
        let pragmatic = round(&store, &prepared, "pragmatic");
        store
            .save_session(&pragmatic.id, &json!({"session":"private-owner-secret"}))
            .unwrap();
        exchange(
            &store,
            &pragmatic,
            "http",
            "GET",
            "pragmatic_launch",
            200,
            false,
        );
        exchange(
            &store,
            &pragmatic,
            "websocket",
            "SEND",
            "GET_BALANCE",
            200,
            false,
        );
        exchange(
            &store,
            &pragmatic,
            "websocket",
            "CONNECT",
            "private-label-secret",
            403,
            false,
        );
        store
            .hold_provider("pragmatic", "private-hold-secret")
            .unwrap();
        store
            .mark_error(&pragmatic.id, "private-error-secret")
            .unwrap();

        let hacksaw = round(&store, &prepared, "hacksaw");
        store
            .save_session(
                &hacksaw.id,
                &json!({"session":"private-other-owner-secret"}),
            )
            .unwrap();
        exchange(&store, &hacksaw, "http", "POST", "bet", 200, true);
        store
            .complete(
                &hacksaw.id,
                &RoundOutcome {
                    native_round_id: Some("public-round-id".into()),
                    currency: "EUR".into(),
                    monetary_unit: "native".into(),
                    currency_source: "native_response".into(),
                    balance_before: "10".into(),
                    balance_after: "9".into(),
                    cost: "1".into(),
                    payout: "0".into(),
                    native_closed: true,
                    checks: BTreeMap::new(),
                    native_data: json!({"secret":"private-native-secret"}),
                },
            )
            .unwrap();
        let report = report(&store, &prepared).unwrap();
        let serialized = serde_json::to_string(&report).unwrap();
        assert!(!serialized.contains("private-"));
        assert!(!serialized.contains("https://"));
        assert_eq!(report["attempted_provider_count"], 2);
        assert_eq!(report["verified_provider_count"], 1);
        let p = provider(&report, "pragmatic");
        assert_eq!(p["execution_status"], "blocked");
        assert_eq!(p["exchange_count"], 3);
        assert_eq!(p["http_events"].as_array().unwrap().len(), 2);
        assert_eq!(p["http_events"][1]["status"], 403);
        assert_eq!(p["last_stage"], "unknown_stage");
        assert_eq!(p["declared_challenge"], true);
        assert_eq!(p["financial_intents"], 0);
        assert_eq!(p["owner_persisted"], true);
        let alias = provider(&report, "reelkingdom");
        assert_eq!(alias["execution_status"], "not_started");
        assert_eq!(alias["reason_code"], "canonical_provider_held");
        assert_eq!(alias["attempted"], false);
        assert_eq!(alias["exchange_count"], 0);
        assert!(alias["round_id"].is_null());
        let h = provider(&report, "hacksaw");
        assert_eq!(h["financial_intents"], 1);
        assert_eq!(h["financial_responses"], 1);
        assert_eq!(h["round"]["outcome"]["cost"], "1");
        assert_eq!(report["runnable_providers_verified"], false);
    }
}
