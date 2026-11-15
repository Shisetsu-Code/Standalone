use crate::{
    context::RunContext,
    model::{
        Game, Mode, ModeKind, RoundOutcome, decimal, exact_add, exact_mul, sha256, wallet_matches,
    },
};
use anyhow::{Context, Result, bail, ensure};
use rust_decimal::Decimal;
use serde::Deserialize;
use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::OnceLock, time::Duration};
use uuid::Uuid;

const API: &str = "https://gs-test.insvr.com/pf?client=1.1.24603.707";

#[derive(Deserialize)]
struct Binding {
    brand: String,
    legacy: bool,
    lines: u64,
    coins: u64,
    modes: BTreeMap<String, String>,
    #[serde(default)]
    sources: BTreeMap<String, PublicSource>,
}

#[derive(Deserialize)]
struct PublicSource {
    url: String,
    sha256: String,
}

fn source_game(id: &str) -> &str {
    match id {
        "SGTabernaDeLosMuertosUltra" => "SGTabernaDeLosMuertos",
        "SGJellyfishFlowUltra" => "SGJellyfishFlow",
        _ => id,
    }
}

fn cake_choice(game: &str, mode: &str) -> Option<u8> {
    if game != "SGCakeValley" {
        return None;
    }
    match mode {
        "normal-1" => Some(1),
        "normal-2" => Some(2),
        "normal-3" => Some(3),
        _ => None,
    }
}

fn binding(game: &Game, mode: &Mode) -> Option<(&'static Binding, &'static str)> {
    static GAMES: OnceLock<BTreeMap<String, Binding>> = OnceLock::new();
    if !matches!(
        (mode.key.as_str(), mode.kind),
        ("normal", ModeKind::Normal)
            | ("superbet", ModeKind::Booster)
            | ("buy", ModeKind::Purchase)
    ) && !(mode.kind == ModeKind::Normal && cake_choice(&game.id, &mode.key).is_some())
    {
        return None;
    }
    let row = GAMES
        .get_or_init(|| {
            serde_json::from_slice(include_bytes!("../../bindings/habanero.json"))
                .expect("valid embedded Habanero bindings")
        })
        .get(&game.id)?;
    Some((row, row.modes.get(&mode.key)?.as_str()))
}

pub fn supports(game: &Game, mode: &Mode) -> bool {
    binding(game, mode).is_some()
}

pub(crate) fn missing_binding_detail(game: &Game, mode: &Mode) -> Option<&'static str> {
    if mode.kind == ModeKind::Booster
        && mode.key == "superbet"
        && matches!(game.id.as_str(), "SGLaughingBuddha" | "SGZeusDeluxe")
    {
        return Some(
            "Habanero public client does not send the Super Bet selector for this game; the historical superBet=1 request was charged as a base spin",
        );
    }
    None
}

fn amount(value: &Value) -> Result<Decimal> {
    match value {
        Value::String(s) => decimal(s),
        Value::Number(n) => decimal(&n.to_string()),
        _ => bail!("Habanero amount missing"),
    }
}

fn text<'a>(value: &'a Value, name: &str) -> Result<&'a str> {
    value[name]
        .as_str()
        .filter(|s| !s.is_empty())
        .with_context(|| format!("Habanero field {name} missing"))
}

fn balance(reply: &Value) -> Result<Decimal> {
    amount(&reply["header"]["player"]["displaybalance"])
}

fn stake(init: &Value) -> Result<Decimal> {
    if let Some(menu) = init["stakeincrement"].as_str().filter(|s| !s.is_empty()) {
        return menu
            .split('|')
            .filter(|s| !s.is_empty())
            .map(decimal)
            .collect::<Result<Vec<_>>>()?
            .into_iter()
            .filter(|d| *d > Decimal::ZERO)
            .min()
            .context("Habanero minimum stake missing");
    }
    let default = amount(&init["defaultstake"])?;
    ensure!(
        default > Decimal::ZERO,
        "Habanero default stake is nonpositive"
    );
    Ok(default)
}

async fn send(ctx: &RunContext, label: &str, body: &Value, financial: bool) -> Result<Value> {
    if financial {
        tokio::time::sleep(Duration::from_millis(700)).await;
    }
    let reply = ctx
        .json(
            label,
            API,
            body,
            BTreeMap::from([
                ("origin".into(), "https://app-test.insvr.com".into()),
                ("referer".into(), "https://app-test.insvr.com/".into()),
                ("accept".into(), "*/*".into()),
            ]),
            financial,
        )
        .await?;
    let error = &reply["error"]["code"];
    ensure!(
        error.is_null() || error == 0 || error == "",
        "Habanero native command rejected"
    );
    ensure!(
        reply["header"]["player"]["funmode"] != false,
        "Habanero response contradicted demo mode"
    );
    Ok(reply)
}

fn request(header: &Value, game: &Value, port: Option<&Value>) -> Value {
    let mut body = json!({"header":header,"game":game,"grid":Uuid::new_v4().to_string()});
    if let Some(port) = port {
        body["portmessage"] = json!(port.to_string());
    }
    body
}

fn validate_owner(reply: &Value, game: &Game, row: &Binding, sid: &str) -> Result<()> {
    let native = &reply["game"];
    ensure!(
        native.is_object()
            && native["sessionid"].as_str().is_none_or(|v| v == sid)
            && native["kn"].as_str().is_none_or(|v| v == game.id)
            && native["brandgameid"]
                .as_str()
                .is_none_or(|v| v == row.brand),
        "Habanero round owner or game changed"
    );
    Ok(())
}

fn continuation(game: &str, message: &Value, pssid: &str) -> Result<Value> {
    let mut next = json!({"gameMode":"free","pssid":pssid,"gssid":text(message, "gssid")?});
    match message["nextgamestate"].as_str() {
        Some("freegame_progress") => next["fgProgress"] = json!({"isComplete":true}),
        Some("freegame" | "main") => {}
        Some("respin") if game == "SGChristmasGiftRush" => {}
        _ => bail!("Habanero continuation requires a reviewed native control"),
    }
    Ok(next)
}

pub async fn execute(ctx: &RunContext, game: &Game, mode: &Mode) -> Result<RoundOutcome> {
    let (row, factor) =
        binding(game, mode).context("Habanero mode lacks verified price and launch parameters")?;
    if let Some(source) = row.sources.get(&mode.key) {
        let asset = url::Url::parse(&source.url)?;
        ensure!(
            asset.path().starts_with(&format!(
                "/gamecontent/{}-UNIVERSAL_v",
                source_game(&game.id)
            )),
            "Habanero public pricing source belongs to another game"
        );
        let reply = ctx.get("public_price_source", asset.as_str()).await?;
        ensure!(
            reply.status == 200 && sha256(reply.body.as_bytes()) == source.sha256,
            "Habanero public price source changed"
        );
    }
    let mut header = json!({
        "player":{"sfb":null,"dtld":639295006360530300_u64,"ssotoken":"","funmode":true,
                  "brandid":"a9d542ac-c9bb-e311-93f6-80c16e0883f4","lc":"en","mobile":false},
        "version":"1.1.24603.707"
    });
    let mut native = json!({"action":"init","sessionid":null,"brandgameid":row.brand,"kn":game.id});
    let opened = send(ctx, "init", &request(&header, &native, None), false).await?;
    let sid = text(&opened["game"], "sessionid")?;
    let token = text(&opened["header"]["player"], "ssotoken")?;
    validate_owner(&opened, game, row, sid)?;
    let before = balance(&opened)?;
    let coin = stake(&opened["game"]["init"])?;
    let cost = exact_mul(coin, decimal(factor)?)?;
    ensure!(
        cost > Decimal::ZERO && before >= cost,
        "insufficient Habanero demo balance"
    );
    ensure!(
        mode.key != "buy" || cost <= Decimal::from(210),
        "Habanero demo purchase cap exceeded"
    );
    let coin_json: Value = serde_json::from_str(&coin.to_string())?;
    native["sessionid"] = json!(sid);
    header["player"]["ssotoken"] = json!(token);
    ctx.save_session(&json!({"game":game.id,"sessionid":sid,"header":header,"service":API}))?;
    let (after, payout, steps, round) = if row.legacy {
        native["action"] = json!("spin");
        native["play"] = json!({"betstate":{"bet":[{"betlevel":1,"stake":coin_json,"numpaylines":row.lines,"coins":row.coins}]}});
        let reply = send(ctx, "spin", &request(&header, &native, None), true).await?;
        validate_owner(&reply, game, row, sid)?;
        let play = &reply["game"]["play"];
        ensure!(
            play["videoslotstate"]["gamemodename"] == "main",
            "Habanero legacy round remains open"
        );
        ensure!(
            amount(&play["totalstake"])? == cost,
            "Habanero native stake differs"
        );
        (
            balance(&reply)?,
            amount(&play["totalpayout"])?,
            1,
            reply["game"]["gameid"].as_str().map(str::to_owned),
        )
    } else {
        native["action"] = json!("game");
        let mut pssid = opened["portmessage"]["pssid"]
            .as_str()
            .unwrap_or_default()
            .to_owned();
        let mut port = json!({"coinValue":coin_json,"betLevel":1,"numLines":row.lines,"gameMode":"base","pssid":pssid});
        match mode.key.as_str() {
            "buy" => port["featureBuy"] = json!(1),
            "superbet" => port["superBet"] = json!(1),
            _ => {}
        }
        if let Some(choice) = cake_choice(&game.id, &mode.key) {
            port["CakeValley_selectedMode"] = json!(choice);
        }
        if game.id == "SGJellyfishFlowUltra" {
            port["betMode"] = json!("ultra");
        }
        let mut steps = 1;
        let mut reply = send(ctx, "entry", &request(&header, &native, Some(&port)), true).await?;
        let mut total_award = Decimal::ZERO;
        let mut root = None;
        loop {
            validate_owner(&reply, game, row, sid)?;
            let message = &reply["portmessage"];
            let done = message["isgamedone"]
                .as_bool()
                .context("Habanero native closure flag missing")?;
            if let Some(id) = reply["game"]["gameid"].as_str().filter(|s| !s.is_empty()) {
                ensure!(
                    root.as_ref().is_none_or(|r| r == id),
                    "Habanero native round changed"
                );
                root = Some(id.to_owned());
            }
            if let Some(part) = message.get("wincash").filter(|v| !v.is_null()) {
                let part = amount(part)?;
                ensure!(part >= Decimal::ZERO, "negative Habanero award");
                total_award = exact_add(total_award, part)?;
            }
            if done {
                let payout = message
                    .get("totalwincash")
                    .filter(|v| !v.is_null())
                    .map(amount)
                    .transpose()?
                    .unwrap_or(total_award);
                break (balance(&reply)?, payout, steps, root);
            }
            ensure!(
                steps < ctx.max_steps(),
                "Habanero continuation limit reached"
            );
            if let Some(next) = message["pssid"].as_str().filter(|s| !s.is_empty()) {
                pssid = next.into();
            }
            port = continuation(&game.id, message, &pssid)?;
            native["gameid"] = json!(
                root.as_deref()
                    .context("Habanero open round identity missing")?
            );
            reply = send(
                ctx,
                "continuation",
                &request(&header, &native, Some(&port)),
                true,
            )
            .await?;
            steps += 1;
        }
    };
    ensure!(
        payout >= Decimal::ZERO && wallet_matches(before, after, cost, payout),
        "Habanero native wallet does not reconcile"
    );
    let observed = opened["header"]["player"]["currency"]
        .as_str()
        .filter(|s| !s.is_empty());
    Ok(RoundOutcome {
        native_round_id: round,
        currency: observed.unwrap_or("DEMO_CREDITS").into(),
        currency_source: if observed.is_some() {
            "native_response".into()
        } else {
            "public_binding".into()
        },
        monetary_unit: "native".into(),
        balance_before: before.to_string(),
        balance_after: after.to_string(),
        cost: cost.to_string(),
        payout: payout.to_string(),
        native_closed: true,
        checks: BTreeMap::from([
            ("demo_session".into(), true),
            ("bound_stake".into(), true),
            ("native_payout".into(), true),
        ]),
        native_data: json!({"steps":steps,"mode":mode.key}),
    })
}
