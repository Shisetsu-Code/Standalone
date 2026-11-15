//! Native capture protocol derived from standalone info/mascot/codigo and the evidence reference adapter.
use crate::{
    context::RunContext,
    model::{Completion, Game, Mode, ModeKind, unknown_event},
};
use anyhow::{Context, Result, bail, ensure};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::OnceLock,
    time::Duration,
};
use url::Url;

#[derive(Deserialize)]
struct Binding {
    launcher: String,
    native_id: String,
    bet_coins: i64,
    modes: BTreeMap<String, Entry>,
    continuations: Vec<Continuation>,
}

#[derive(Deserialize)]
struct Entry {
    entry: Value,
    echo: Vec<i64>,
    purchase: Option<Value>,
}

#[derive(Deserialize)]
struct Continuation {
    feature: String,
    action: String,
    requests: Vec<Value>,
}

fn binding(game: &Game, mode: &Mode) -> Option<(&'static Binding, &'static Entry)> {
    static BINDINGS: OnceLock<BTreeMap<String, Binding>> = OnceLock::new();
    let game = BINDINGS
        .get_or_init(|| {
            serde_json::from_slice(include_bytes!("../../bindings/mascot.json"))
                .expect("valid embedded Mascot bindings")
        })
        .get(&game.id)?;
    let entry = game.modes.get(&mode.key)?;
    match (
        mode.kind,
        entry.entry["action"].as_str(),
        entry.entry["boost"].as_bool(),
    ) {
        (ModeKind::Normal, Some("spin"), Some(false))
        | (ModeKind::AnteBet, Some("spin"), Some(true))
        | (ModeKind::Purchase, Some("buyin"), _) => Some((game, entry)),
        _ => None,
    }
}

pub fn supports(game: &Game, mode: &Mode) -> bool {
    binding(game, mode).is_some()
}

fn closes(reply: &Value) -> bool {
    reply["feature"] == "basic" && reply["nextAction"] == "spin"
}

fn validate_quote(init: &Value, binding: &Binding, entry: &Entry) -> Result<()> {
    ensure!(
        init["gameId"] == binding.native_id && closes(init),
        "Mascot did not initialize an idle demo"
    );
    entry.entry["bet"]
        .as_i64()
        .filter(|v| *v > 0)
        .context("invalid bound Mascot bet")?;
    ensure!(
        init["bets"]
            .as_array()
            .is_some_and(|bets| bets.contains(&entry.entry["bet"]))
            && init["betCoins"] == binding.bet_coins
            && binding.bet_coins > 0,
        "Mascot stake menu changed"
    );
    if let Some(expected) = &entry.purchase {
        let offers = init["buyin"]["regular"]
            .as_array()
            .context("Mascot purchase menu absent")?;
        let mut offers = offers
            .iter()
            .filter(|item| item["id"] == entry.entry["buyinType"]);
        let offer = offers.next().context("Mascot purchase unavailable")?;
        ensure!(
            offers.next().is_none()
                && ["type", "fs"]
                    .iter()
                    .all(|key| offer[*key] == expected[*key]),
            "Mascot purchase details changed"
        );
    }
    if entry.entry["boost"] == true {
        ensure!(
            init["buyin"]["boost"].is_object(),
            "Mascot antebet not offered"
        );
    }
    Ok(())
}

fn continuation(reply: &Value, binding: &Binding, bet: &Value) -> Result<Value> {
    let mut used = BTreeSet::new();
    if let Some(entries) = reply["bonus"]["items"].as_object() {
        used.extend(entries.keys().cloned());
    }
    if let Some(entries) = reply["bonus"]["lostItems"].as_array() {
        used.extend(
            entries
                .iter()
                .map(|v| v.as_str().map_or_else(|| v.to_string(), str::to_owned)),
        );
    }
    let mut request = binding
        .continuations
        .iter()
        .find(|next| reply["feature"] == next.feature && reply["nextAction"] == next.action)
        .and_then(|next| {
            next.requests.iter().find(|request| {
                request
                    .get("bonusItem")
                    .is_none_or(|id| !used.contains(&id.to_string()))
            })
        })
        .cloned()
        .ok_or_else(|| unknown_event("Mascot continuation requires a reviewed control"))?;
    if request.get("bet").is_some() {
        request["bet"] = bet.clone();
    }
    Ok(request)
}

async fn launch(ctx: &RunContext, launcher: &str) -> Result<Url> {
    let mut url = Url::parse("https://demo.mascot.games/")?;
    url.path_segments_mut()
        .map_err(|_| anyhow::anyhow!("invalid Mascot launcher"))?
        .extend(["run", launcher]);
    for _ in 0..5 {
        let answer = ctx.get("demo_launch", url.as_str()).await?;
        if answer.status == 200 {
            ensure!(
                url.host_str() != Some("demo.mascot.games"),
                "Mascot demo did not issue a game host"
            );
            return url
                .join("/mascotGaming/spin.php")
                .context("invalid Mascot game endpoint");
        }
        ensure!(
            matches!(answer.status, 301 | 302 | 303 | 307 | 308),
            "Mascot unexpected launch status {}",
            answer.status
        );
        url = url.join(
            answer
                .headers
                .get("location")
                .context("Mascot redirect missing destination")?,
        )?;
    }
    bail!("Mascot demo redirect limit")
}

async fn send(ctx: &RunContext, endpoint: &Url, request: &Value, financial: bool) -> Result<Value> {
    let origin = endpoint.origin().ascii_serialization();
    let action = request["action"].as_str().context("Mascot action absent")?;
    tokio::time::sleep(Duration::from_millis(if action == "collect" {
        2600
    } else {
        1000
    }))
    .await;
    ctx.json(
        action,
        endpoint.as_str(),
        request,
        BTreeMap::from([
            ("origin".into(), origin.clone()),
            ("referer".into(), format!("{origin}/")),
        ]),
        financial,
    )
    .await
}

pub async fn execute(
    ctx: &RunContext,
    game: &Game,
    mode: &Mode,
    _settings: &serde_json::Value,
) -> Result<Completion> {
    let (binding, profile) =
        binding(game, mode).context("Mascot mode has no native slot binding")?;
    let endpoint = launch(ctx, &binding.launcher).await?;
    let init = send(ctx, &endpoint, &json!({"action":"init"}), false).await?;
    validate_quote(&init, binding, profile)?;
    ctx.save_session(&json!({"game":game.id,"endpoint":endpoint.as_str(),"currency":"NAN"}))?;
    let first = send(ctx, &endpoint, &profile.entry, true).await?;

    ensure!(
        first["bet"]
            .as_i64()
            .is_some_and(|bet| profile.echo.contains(&bet)),
        "Mascot entry bet not confirmed"
    );
    let mut responses = vec![first];
    for _ in 0..ctx.max_steps().min(300) {
        let last = responses.last().context("Mascot response missing")?;
        ensure!(
            last.is_object() && last.get("error").is_none(),
            "Mascot rejected action"
        );
        ensure!(
            last.get("gameId").is_none_or(|v| v == &binding.native_id),
            "Mascot game changed"
        );

        if closes(last) {
            return Ok(Completion {
                native_round_id: None,
                details: json!({"steps":responses.len(),"mode":mode.key}),
            });
        }
        if responses.len() >= ctx.max_steps().min(300) {
            break;
        }
        let request = continuation(last, binding, &profile.entry["bet"])?;
        responses.push(send(ctx, &endpoint, &request, true).await?);
    }
    bail!("Mascot continuation limit reached")
}

#[cfg(test)]
mod capture_tests {
    use super::*;

    #[test]
    fn closure_without_wallet() {
        assert!(closes(&json!({"feature":"basic","nextAction":"spin"})));
    }
    #[test]
    fn unknown_feature_does_not_invent_action() {
        let binding: Binding = serde_json::from_value(
            json!({"launcher":"test","native_id":"t","bet_coins":1,"modes":{},"continuations":[]}),
        )
        .unwrap();
        let err = continuation(
            &json!({"feature":"new","nextAction":"invented"}),
            &binding,
            &json!(1),
        )
        .unwrap_err();
        assert!(err.downcast_ref::<crate::model::UnknownEvent>().is_some());
    }
}
