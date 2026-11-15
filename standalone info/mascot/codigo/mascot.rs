use crate::{
    context::RunContext,
    model::{Game, Mode, ModeKind, RoundOutcome},
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
    cost: i64,
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

fn balance(reply: &Value, expected_game: &str) -> Result<i64> {
    ensure!(
        reply.is_object() && reply.get("error").is_none(),
        "Mascot rejected the action"
    );
    ensure!(
        reply.get("gameId").is_none_or(|id| id == expected_game)
            && reply.get("currency").is_none_or(|code| code == "NAN"),
        "Mascot title or demo currency changed"
    );
    reply["balance"]
        .as_i64()
        .filter(|value| *value >= 0)
        .context("Mascot balance absent")
}

fn validate_quote(init: &Value, binding: &Binding, entry: &Entry) -> Result<()> {
    ensure!(
        init["gameId"] == binding.native_id && init["currency"] == "NAN" && closes(init),
        "Mascot did not initialize an idle demo"
    );
    let bet = entry.entry["bet"]
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
    let multiplier = if let Some(expected) = &entry.purchase {
        let offers = init["buyin"]["regular"]
            .as_array()
            .context("Mascot purchase menu absent")?;
        let mut offers = offers
            .iter()
            .filter(|item| item["id"] == entry.entry["buyinType"]);
        let offer = offers.next().context("Mascot purchase unavailable")?;
        ensure!(
            offers.next().is_none()
                && ["type", "fs", "bet"]
                    .iter()
                    .all(|key| offer[*key] == expected[*key]),
            "Mascot purchase details changed"
        );
        offer["bet"]
            .as_i64()
            .context("Mascot purchase multiplier absent")?
    } else if entry.entry["boost"] == true {
        init["buyin"]["boost"]["bet_multiplier"]
            .as_i64()
            .context("Mascot antebet multiplier absent")?
    } else {
        1
    };
    ensure!(
        multiplier > 0
            && bet
                .checked_mul(binding.bet_coins)
                .and_then(|v| v.checked_mul(multiplier))
                == Some(entry.cost),
        "Mascot offer cost changed"
    );
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
        .context("Mascot continuation requires a reviewed control")?;
    if request.get("bet").is_some() {
        request["bet"] = bet.clone();
    }
    Ok(request)
}

fn award(before: i64, cost: i64, after: i64, responses: &[Value]) -> Result<i64> {
    let first = responses.first().context("Mascot entry missing")?;
    let last = responses.last().context("Mascot close missing")?;
    let mut candidates = BTreeSet::new();
    if let Some(total) = last["totalWin"].as_i64() {
        candidates.insert(total);
        if responses.len() > 1
            && let Some(combined) = first["totalWin"]
                .as_i64()
                .and_then(|n| n.checked_add(total))
        {
            candidates.insert(combined);
        }
    }
    if let Some(total) = responses
        .iter()
        .try_fold(0_i64, |sum, item| sum.checked_add(item["win"].as_i64()?))
    {
        candidates.insert(total);
    }
    candidates
        .into_iter()
        .find(|win| {
            *win >= 0 && before.checked_sub(cost).and_then(|n| n.checked_add(*win)) == Some(after)
        })
        .context("Mascot native awards do not reconcile")
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

pub async fn execute(ctx: &RunContext, game: &Game, mode: &Mode) -> Result<RoundOutcome> {
    let (binding, profile) =
        binding(game, mode).context("Mascot mode has no reconciled slot binding")?;
    let endpoint = launch(ctx, &binding.launcher).await?;
    let init = send(ctx, &endpoint, &json!({"action":"init"}), false).await?;
    validate_quote(&init, binding, profile)?;
    let before = balance(&init, &binding.native_id)?;
    let cost = profile.cost;
    ensure!(before >= cost, "insufficient Mascot demo funds");
    ctx.save_session(&json!({"game":game.id,"endpoint":endpoint.as_str(),"currency":"NAN"}))?;
    let first = send(ctx, &endpoint, &profile.entry, true).await?;
    let after_entry = balance(&first, &binding.native_id)?;
    ensure!(
        first["bet"]
            .as_i64()
            .is_some_and(|bet| profile.echo.contains(&bet)),
        "Mascot entry bet not confirmed"
    );
    let charged = before - after_entry;
    ensure!(
        charged == cost
            || charged.checked_add(first["totalWin"].as_i64().unwrap_or_default()) == Some(cost),
        "Mascot entry debit differs from native offer"
    );
    let mut responses = vec![first];
    for _ in 0..ctx.max_steps().min(300) {
        let last = responses.last().context("Mascot response missing")?;
        let after = balance(last, &binding.native_id)?;
        if closes(last) {
            let payout = award(before, cost, after, &responses)?;
            return Ok(RoundOutcome {
                native_round_id: None,
                currency: "NAN".into(),
                currency_source: "native_response".into(),
                monetary_unit: "native".into(),
                balance_before: before.to_string(),
                balance_after: after.to_string(),
                cost: cost.to_string(),
                payout: payout.to_string(),
                native_closed: true,
                checks: BTreeMap::from([
                    ("demo_mode".into(), true),
                    ("native_quote".into(), true),
                    ("native_award".into(), true),
                ]),
                native_data: json!({"steps":responses.len(),"mode":mode.key}),
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
