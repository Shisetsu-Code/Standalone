use crate::model::{Mode, ModeKind, decimal, exact_mul, wallet_matches};
use crate::{
    context::{DecodedFrame, NativeSocket, RunContext, SocketPayload},
    model::{Game, RoundOutcome},
};
use anyhow::{Context, Result, bail, ensure};
use rust_decimal::Decimal;
use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::OnceLock, time::Duration};
use url::Url;

fn binding(game: &Game, mode: &Mode) -> Option<(&'static str, &'static Value)> {
    static MAP: OnceLock<Value> = OnceLock::new();
    let map = MAP.get_or_init(|| {
        serde_json::from_str(include_str!("../../bindings/ela-games.json"))
            .expect("embedded ELA catalogue bindings")
    });
    let row = map.get(&game.id)?;
    let mode_row = row["modes"].get(&mode.key)?;
    (mode_row["kind"] == mode.kind.as_str())
        .then(|| (row["path"].as_str(), &mode_row["feature"]))
        .and_then(|(path, feature)| Some((path?, feature)))
}

pub fn supports(game: &Game, mode: &Mode) -> bool {
    binding(game, mode).is_some()
}

enum Packet {
    Open,
    Namespace,
    Event,
}

fn decode(packet: &Packet, frame: &SocketPayload) -> Result<DecodedFrame> {
    let SocketPayload::Text(text) = frame else {
        bail!("ELA unexpected binary frame");
    };
    let mut decoded = DecodedFrame {
        values: Vec::new(),
        replies: Vec::new(),
    };
    if let Some(ping) = text.strip_prefix('2') {
        decoded
            .replies
            .push(SocketPayload::Text(format!("3{ping}")));
        return Ok(decoded);
    }
    match packet {
        Packet::Open => {
            let payload = text
                .strip_prefix('0')
                .context("ELA Engine.IO greeting missing")?;
            let hello: Value = serde_json::from_str(payload)?;
            ensure!(
                hello["sid"].as_str().is_some_and(|sid| !sid.is_empty()),
                "ELA Engine.IO SID missing"
            );
            decoded.values.push(hello);
        }
        Packet::Namespace => {
            ensure!(
                text.starts_with("40"),
                "ELA Socket.IO namespace connection rejected"
            );
            decoded.values.push(json!(true));
        }
        Packet::Event => {
            if let Some(message) = text.strip_prefix("42") {
                if message.starts_with('[') {
                    let event: Value = serde_json::from_str(message)?;
                    if matches!(event[0].as_str(), Some("message" | "exception")) {
                        ensure!(event[1].is_object(), "ELA invalid application response");
                        decoded.values.push(event);
                    }
                }
            } else {
                ensure!(
                    !text.starts_with("41") && !text.starts_with("44"),
                    "ELA Socket.IO session interrupted"
                );
            }
        }
    }
    Ok(decoded)
}

async fn event(
    ctx: &RunContext,
    socket: &mut NativeSocket,
    name: &str,
    token: &str,
    request: Option<&Value>,
) -> Result<Value> {
    let mut data = json!({"session":token});
    if let Some(request) = request {
        data["request"] = request.clone();
    }
    let payload = SocketPayload::Text(format!("420{}", json!([name, data])));
    ctx.ws_codec_controlled(socket, name, payload, request.is_some(), None, |frame| {
        decode(&Packet::Event, frame)
    })
    .await
}

pub async fn execute(ctx: &RunContext, game: &Game, mode: &Mode) -> Result<RoundOutcome> {
    let (path, expected_feature) =
        binding(game, mode).context("ELA catalogue/mode binding missing")?;
    let entry_url = validate_public_launch(&format!("https://expo.elaapi.com{path}"))?;
    let origin = "https://preprod.elaapi.com";
    let first = ctx.get("public_demo_launch", entry_url.as_str()).await?;
    ensure!(
        matches!(first.status, 301 | 302 | 303 | 307 | 308),
        "ELA public launcher did not redirect"
    );
    let launcher = entry_url.join(
        first
            .headers
            .get("location")
            .context("ELA demo redirect missing")?,
    )?;
    ensure!(
        launcher.origin().ascii_serialization() == origin && launcher.path() == "/launcher/",
        "ELA demo redirect changed"
    );
    let token = launcher
        .query_pairs()
        .find_map(|(key, value)| {
            (key == "session" && !value.is_empty()).then(|| value.into_owned())
        })
        .context("ELA fresh demo session missing")?;
    ensure!(
        ctx.get("native_launcher", launcher.as_str()).await?.status == 200,
        "ELA native launcher unavailable"
    );
    let mut ws = Url::parse("wss://preprod.elaapi.com/gateway-game/socket.io/")?;
    ws.query_pairs_mut()
        .append_pair("session", &token)
        .append_pair("EIO", "4")
        .append_pair("transport", "websocket");
    let mut socket = ctx
        .websocket(ws.as_str(), origin, None, BTreeMap::new())
        .await?;
    ctx.ws_exchange(&mut socket, "engineio_open", None, false, None, |frame| {
        decode(&Packet::Open, frame)
    })
    .await?;
    ctx.ws_codec_controlled(
        &mut socket,
        "socketio_connect",
        SocketPayload::Text("40".into()),
        false,
        None,
        |frame| decode(&Packet::Namespace, frame),
    )
    .await?;
    let start = event(ctx, &mut socket, "start", &token, None).await?;
    let cfg = &start[1];
    ensure!(
        start[0] == "message" && cfg["sessionMode"] == "DEMO",
        "ELA native DEMO mode missing"
    );
    let native_id = cfg["gameId"]
        .as_str()
        .filter(|id| !id.is_empty())
        .context("ELA native game identity missing")?;
    ensure!(
        native_id == game.id || game.id.strip_prefix("ela_") == Some(native_id),
        "ELA native game identity differs from catalogue"
    );
    let quote = quote(cfg, mode)?;
    ensure!(
        quote.feature.as_ref().unwrap_or(&Value::Null) == expected_feature,
        "ELA purchase offer differs from the captured contract"
    );
    let currency = cfg
        .pointer("/wallet/currency")
        .and_then(Value::as_str)
        .or_else(|| cfg.pointer("/wallet/currencyCode").and_then(Value::as_str))
        .filter(|currency| !currency.is_empty())
        .map(str::to_owned);
    ctx.save_session(&json!({"provider":"ela-games","game":game.id,"native_game":native_id,"session":token,"native_demo":true,"cost":quote.cost}))?;
    let mut request = entry(&quote);
    let mut steps = Vec::new();
    for _ in 0..ctx.max_steps().min(500) {
        tokio::time::sleep(Duration::from_secs(1)).await;
        let reply = event(ctx, &mut socket, "play", &token, Some(&request)).await?;
        ensure!(reply[0] == "message", "ELA native play exception");
        let body = reply[1].clone();
        let next = continuation(&body, &quote.bet, None)?;
        steps.push(NativeStep {
            event: "message".into(),
            request,
            response: body,
        });
        if let Some(command) = next {
            request = command;
            continue;
        }
        let settled = audit(&quote, &steps)?;
        ensure!(
            settled.wallet_matches,
            "ELA native demo wallet did not reconcile"
        );
        let final_wallet = &steps.last().context("ELA terminal frame missing")?.response["wallet"];
        if let Some(final_currency) = final_wallet["currency"]
            .as_str()
            .or_else(|| final_wallet["currencyCode"].as_str())
        {
            ensure!(
                currency.as_deref() == Some(final_currency),
                "ELA native wallet currency changed"
            );
        }
        let (currency, source) = match currency {
            Some(code) => (code, "native_response"),
            None => ("DEMO".into(), "native_response"),
        };
        return Ok(RoundOutcome {
            native_round_id: None,
            currency,
            currency_source: source.into(),
            monetary_unit: "native".into(),
            balance_before: settled.before.to_string(),
            balance_after: settled.after.to_string(),
            cost: settled.cost.to_string(),
            payout: settled.payout.to_string(),
            native_closed: true,
            checks: BTreeMap::from([
                ("fresh_native_demo".into(), true),
                ("native_cost".into(), true),
            ]),
            native_data: json!({"steps":steps.len(),"currency_evidence":"wallet currency or native DEMO units"}),
        });
    }
    bail!("ELA continuation limit reached")
}

const CONTINUATIONS: &[&str] = &[
    "freeSpin",
    "superFreeSpin",
    "reSpin",
    "freeSpinReSpin",
    "superFreeSpinReSpin",
    "collect",
    "featureFreeSpin",
    "freeSpinIntro",
    "freeSpinEnd",
    "wheel",
    "bonusGame",
    "jackpotSpin",
    "jackpotReSpin",
    "freeGame",
    "featureFreeSpinReSpin",
];

#[derive(Clone, Debug)]
pub struct Quote {
    pub bet: Value,
    pub factor: Decimal,
    pub feature_count: Decimal,
    pub feature: Option<Value>,
    pub cost: Decimal,
    pub before: Decimal,
}

#[derive(Clone, Debug)]
pub struct NativeStep {
    pub event: String,
    pub request: Value,
    pub response: Value,
}

#[derive(Clone, Debug)]
pub struct FinancialAudit {
    pub before: Decimal,
    pub after: Decimal,
    pub cost: Decimal,
    pub payout: Decimal,
    pub wallet_matches: bool,
}

pub fn validate_public_launch(value: &str) -> Result<Url> {
    let url = Url::parse(value)?;
    ensure!(
        url.scheme() == "https"
            && url.host_str() == Some("expo.elaapi.com")
            && url.username().is_empty()
            && url.password().is_none()
            && url.port().is_none()
            && url.query().is_none()
            && url.fragment().is_none()
            && url
                .path()
                .strip_prefix("/demo/")
                .is_some_and(|game| !game.is_empty()
                    && !game.contains('/')
                    && game
                        .bytes()
                        .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'_' | b'-'))),
        "ELA public unauthenticated demo URL required"
    );
    Ok(url)
}

fn amount(value: &Value) -> Result<Decimal> {
    match value {
        Value::String(s) => decimal(s),
        Value::Number(n) => decimal(&n.to_string()),
        _ => bail!("ELA native amount missing"),
    }
}

/// This uses the observed provider default, not a fabricated minimum.
pub fn quote(config: &Value, mode: &Mode) -> Result<Quote> {
    let settings = &config["result"]["settings"];
    let bet = settings["bet"]["defaultBet"].clone();
    let base = amount(&bet)?;
    let factor = amount(&settings["info"]["totalBetFactor"])?;
    ensure!(
        base > Decimal::ZERO && factor > Decimal::ZERO,
        "ELA native default bet/factor invalid"
    );
    let feature = match mode.kind {
        ModeKind::Normal => {
            ensure!(mode.key == "normal", "ELA unreviewed normal selector");
            None
        }
        ModeKind::Purchase => {
            let features = config["buyFeatures"]
                .as_array()
                .context("ELA native purchase directory missing")?;
            let matches = features
                .iter()
                .filter(|f| f["type"] == mode.key)
                .collect::<Vec<_>>();
            ensure!(
                matches.len() == 1,
                "ELA native purchase is absent or ambiguous"
            );
            Some(matches[0].clone())
        }
        _ => bail!("ELA unsupported application-level mode"),
    };
    let count = if let Some(feature) = &feature {
        amount(&feature["betsCount"])?
    } else {
        Decimal::ONE
    };
    ensure!(count > Decimal::ZERO, "ELA native feature price missing");
    let cost = exact_mul(exact_mul(base, factor)?, count)?;
    let before = amount(&config["wallet"]["balance"])?;
    ensure!(before >= cost, "ELA insufficient fictional-demo balance");
    Ok(Quote {
        bet,
        factor,
        feature_count: count,
        feature,
        cost,
        before,
    })
}

pub fn entry(quote: &Quote) -> Value {
    let mut command = json!({"action":"spin","bet":quote.bet});
    if let Some(feature) = &quote.feature {
        command["buyFeature"] = feature["type"].clone();
    }
    command
}

fn mode(result: &Value) -> Option<&str> {
    result["nextMode"]
        .as_str()
        .filter(|v| !v.is_empty())
        .or_else(|| result["state"]["mode"].as_str().filter(|v| !v.is_empty()))
        .or_else(|| result["mode"].as_str().filter(|v| !v.is_empty()))
}

pub fn closed(reply: &Value) -> bool {
    reply["result"]["ended"] == true && mode(&reply["result"]).is_none_or(|v| v == "base")
}

pub fn continuation(
    reply: &Value,
    bet: &Value,
    chosen_interactive: Option<&str>,
) -> Result<Option<Value>> {
    ensure!(
        reply["spin_uid"].as_str().is_some_and(|s| !s.is_empty())
            || reply["spin_uid"].as_u64().is_some(),
        "ELA native spin_uid missing"
    );
    if closed(reply) {
        return Ok(None);
    }
    let result = &reply["result"];
    if let Some(interactive) = result["interactive"].as_object().filter(|v| !v.is_empty()) {
        let choice = chosen_interactive
            .or_else(|| interactive.contains_key("collect").then_some("collect"))
            .context(
                "ELA native interactive choice requires an explicit currently offered selection",
            )?;
        ensure!(
            interactive.contains_key(choice),
            "ELA interactive choice is not offered by the server"
        );
        return Ok(Some(
            json!({"action":"pick","bet":bet,"userInput":{"interactive":choice}}),
        ));
    }
    ensure!(
        chosen_interactive.is_none(),
        "ELA interactive selection supplied outside an offered choice"
    );
    let next = mode(result).context("ELA native continuation mode missing")?;
    ensure!(
        CONTINUATIONS.contains(&next),
        "ELA native continuation mode is outside the published contract"
    );
    Ok(Some(json!({"action":next,"bet":bet})))
}

/// Uses the quoted cost, first native totalBet and terminal native prize. It
/// never substitutes spin_uid presence or a historical status for root proof.
pub fn audit(quote: &Quote, steps: &[NativeStep]) -> Result<FinancialAudit> {
    let first = steps.first().context("ELA native trace is empty")?;
    let last = steps.last().context("ELA native trace is empty")?;
    ensure!(
        first.request == entry(quote),
        "ELA entry differs from the native quoted option"
    );
    ensure!(
        exact_mul(
            amount(&first.response["result"]["totalBet"])?,
            quote.feature_count
        )? == quote.cost,
        "ELA independent native totalBet differs from pre-entry quote"
    );
    for (index, step) in steps.iter().enumerate() {
        ensure!(
            step.event == "message"
                && step
                    .response
                    .get("error")
                    .is_none_or(|v| v.is_null() || v == false),
            "ELA native event error"
        );
        ensure!(
            step.response["spin_uid"]
                .as_str()
                .is_some_and(|s| !s.is_empty())
                || step.response["spin_uid"].as_u64().is_some(),
            "ELA native spin_uid missing"
        );
        if index > 0 {
            let selected = step
                .request
                .pointer("/userInput/interactive")
                .and_then(Value::as_str);
            let expected = continuation(&steps[index - 1].response, &quote.bet, selected)?
                .context("ELA trace continued after native closure")?;
            ensure!(
                step.request == expected,
                "ELA continuation differs from the current native offer or repeats a purchase"
            );
        }
    }
    ensure!(closed(&last.response), "ELA native round remains open");
    let result = &last.response["result"];
    let payout = if let Some(real) = result.get("round_real_win") {
        amount(real)?
    } else {
        amount(&result["roundTotalWin"])?
    };
    let after = amount(&last.response["wallet"]["balance"])?;
    Ok(FinancialAudit {
        before: quote.before,
        after,
        cost: quote.cost,
        payout,
        wallet_matches: wallet_matches(quote.before, after, quote.cost, payout),
    })
}
