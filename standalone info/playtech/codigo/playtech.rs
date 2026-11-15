use crate::{
    context::{DecodedFrame, NativeSocket, RunContext, SocketPayload},
    model::{Game, Mode, ModeKind, RoundOutcome, now_ms},
};
use anyhow::{Context, Result, ensure};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use uuid::Uuid;

pub(super) const ROOT: &str = "https://gpas-games.playtechone.com";
const CODE: &str = "gpas_blitz10_pop";
const OFFER: &str = "d743f173-2233-463f-909d-a4e95f68a07a";
const COMMAND: &str = "com.pt.casino.platform.game.GameCommand";
const BALANCE: &str = "com.pt.casino.platform.balance.BalanceNotification";

pub fn supports(game: &Game, mode: &Mode) -> bool {
    game.id == format!("gpas:{CODE}") && mode.kind == ModeKind::Normal && mode.key == OFFER
}

fn field<'a>(value: &'a Value, name: &str) -> Result<&'a str> {
    value[name]
        .as_str()
        .filter(|v| !v.is_empty())
        .with_context(|| format!("GPAS {name} missing"))
}

async fn get(ctx: &RunContext, label: &str, url: &str) -> Result<String> {
    let reply = ctx.get(label, url).await?;
    ensure!(reply.status == 200, "GPAS {label} HTTP {}", reply.status);
    Ok(reply.body)
}

fn amount(value: &Value) -> Result<u64> {
    value
        .as_u64()
        .context("GPAS native amount missing or invalid")
}

async fn exchange(
    ctx: &RunContext,
    socket: &mut NativeSocket,
    label: &str,
    data: Value,
    financial: bool,
    expected: &str,
    balance: &mut Option<u64>,
) -> Result<Value> {
    let id = format!("tester-{}", Uuid::new_v4().simple());
    let body = format!("3:::{}", json!({"data":data,"correlationId":id}));
    let mut command = None;
    ctx.ws_codec_controlled(
        socket,
        label,
        SocketPayload::Text(body),
        financial,
        Some(&id),
        |frame| {
            let SocketPayload::Text(frame) = frame else {
                anyhow::bail!("unexpected GPAS frame")
            };
            let mut result = DecodedFrame {
                values: vec![],
                replies: vec![],
            };
            if frame == "2::" {
                result.replies.push(SocketPayload::Text("2::".into()));
                return Ok(result);
            }
            let packet: Value = serde_json::from_str(
                frame
                    .strip_prefix("3:::")
                    .context("unexpected GPAS frame prefix")?,
            )?;
            let payload = &packet["data"];
            let ty = field(payload, "_type")?;
            let current = packet["correlationId"] == id;
            if ty == BALANCE && (!financial || current) {
                let wallet = payload["balance"]
                    .as_array()
                    .context("GPAS wallet missing")?;
                let mut wallets = wallet.iter().filter(|row| {
                    row["_type"] == "com.pt.casino.platform.balance.MonetaryBalanceData"
                });
                let item = wallets.next().context("GPAS monetary wallet missing")?;
                ensure!(wallets.next().is_none(), "GPAS monetary wallet ambiguous");
                *balance = Some(amount(&item["amount"])?);
            }
            if current && ty == expected {
                command = Some(payload.clone());
            }
            if (!financial || balance.is_some())
                && let Some(payload) = command.take()
            {
                result
                    .values
                    .push(json!({"requestId":id,"payload":payload}));
            }
            Ok(result)
        },
    )
    .await
    .map(|v| v["payload"].clone())
}

pub async fn execute(ctx: &RunContext, game: &Game, mode: &Mode) -> Result<RoundOutcome> {
    ensure!(supports(game, mode), "GPAS mode has no reviewed binding");
    let release: Value = serde_json::from_str(
        &get(ctx, "release", &format!("{ROOT}/gpasclientconf_live.php")).await?,
    )?;
    let release = field(&release, "id")?;
    ensure!(
        release
            .split('.')
            .all(|s| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit())),
        "invalid GPAS release"
    );
    let bundle: Value = serde_json::from_str(
        &get(
            ctx,
            "bundle",
            &format!("{ROOT}/{release}/logical_bundle.php"),
        )
        .await?,
    )?;
    let path = field(&bundle["games"], CODE)?;
    ensure!(
        path.starts_with(&format!("/gpasdistributed/igv/{CODE}/"))
            && path.trim_end_matches('/').rsplit('/').next().is_some_and(
                |v| !v.is_empty() && v.bytes().all(|b| b.is_ascii_digit() || b == b'.')
            ),
        "unexpected GPAS game path"
    );
    let manifest: Value = serde_json::from_str(
        &get(
            ctx,
            "manifest",
            &format!("{ROOT}{}/packs/manifest.json", path.trim_end_matches('/')),
        )
        .await?,
    )?;
    ensure!(manifest["gameCode"] == CODE, "GPAS game identity mismatch");
    let env: Value = serde_json::from_str(
        &get(
            ctx,
            "environment",
            &format!("{ROOT}/{release}/brands/playtechhorizon/1/json/env_config.json"),
        )
        .await?,
    )?;
    let host = field(&env["server"], "host")?;
    ensure!(
        matches!(
            host,
            "gpas-stg.playtechone.com" | "frontend.playtechhorizon.com"
        ) && (env["server"]["secure"] == true || env["server"]["secure"] == "true"),
        "invalid GPAS demo server"
    );
    let handshake = get(
        ctx,
        "socket_handshake",
        &format!("https://{host}/socket.io/1/?t={}", now_ms()),
    )
    .await?;
    let parts: Vec<_> = handshake.trim().split(':').collect();
    ensure!(
        parts.len() == 4
            && parts[3].split(',').any(|v| v == "websocket")
            && !parts[0].is_empty()
            && parts[0]
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_'),
        "invalid GPAS WSS handshake"
    );
    let mut socket = ctx
        .websocket(
            &format!("wss://{host}/socket.io/1/websocket/{}", parts[0]),
            ROOT,
            None,
            BTreeMap::new(),
        )
        .await?;
    ctx.ws_expect_text(&mut socket, "socket_ready", "1::")
        .await?;
    let identity = Uuid::new_v4().to_string();
    let mut features = vec!["freespinTotalBalance"];
    if manifest["setup"]["supportsFs2Bonus"] == true {
        features.push("freespin2");
    }
    let mut before = None;
    let session = exchange(ctx,&mut socket,"session",json!({"_type":"InitGameSession","casino":"playtechhorizon",
        "clientType":"casino","clientPlatform":"web","language":"EN","gameCode":CODE,"username":identity,
        "token":identity,"resume":false,"apiFeatures":features,"real":0}),false,"InitGameSessionResponse",&mut before).await?;
    ensure!(
        session["brokenGame"] == false,
        "GPAS rejected new demo session"
    );
    let currency = field(&session, "currency")?;
    let state = exchange(
        ctx,
        &mut socket,
        "state",
        json!({"_type":"GetClientState"}),
        false,
        "GetClientStateResponse",
        &mut before,
    )
    .await?;
    ensure!(
        state["gameCommand"].is_object() && state["gameCommand"]["gameRoundClosed"] != false,
        "GPAS demo has an open round"
    );
    let config = exchange(
        ctx,
        &mut socket,
        "configuration",
        json!({"_type":"com.pt.gpas.config.GetGameConfigurationRequest",
        "scoped":true,"disablePersonalizedBets":true}),
        false,
        "com.pt.gpas.config.GetGameConfigurationResponse",
        &mut before,
    )
    .await?;
    let before = before.context("GPAS opening balance missing")?;
    let scopes = config["data"].as_array().context("GPAS offer missing")?;
    let mut base = scopes
        .iter()
        .filter(|v| v["scope"].as_object().is_some_and(|o| o.is_empty()));
    let cfg = &base.next().context("GPAS base offer missing")?["content"]["game"];
    ensure!(
        base.next().is_none()
            && cfg["activeBetOptions"]
                .as_array()
                .is_some_and(|v| v.iter().any(|x| x == "default")),
        "GPAS base offer ambiguous or inactive"
    );
    let mut offers = cfg["costConfiguration"]
        .as_array()
        .context("GPAS wager menu missing")?
        .iter()
        .filter(|v| v["uuid"] == OFFER);
    let offer = offers.next().context("GPAS reviewed wager not offered")?;
    let cost = amount(&offer["cost"])?;
    ensure!(
        offers.next().is_none() && offer["name"] == "default" && cost == 10 && before >= cost,
        "GPAS reviewed wager changed or demo funds insufficient"
    );
    ctx.save_session(
        &json!({"game":CODE,"owner":identity,"token":field(&session,"token")?,"currency":currency}),
    )?;
    let mut after = None;
    let response = exchange(ctx,&mut socket,"normal",json!({"_type":COMMAND,"autoplay":false,
        "gameData":{"ID":40021,"_type":"com.pt.gpas.platform.game.OgwCorosinGameCommand",
            "parameters":[{"key":"extraBetSupported","value":"true"},{"key":"extraBetActive","value":"false"}]},
        "betCost":cost,"betType":"default","featureType":"default"}),true,COMMAND,&mut after).await?;
    let after = after.context("GPAS closing balance missing")?;
    let payout = amount(&response["winAmount"])?;
    ensure!(
        response["gameRoundClosed"] == true
            && response["gameData"]["nextRound"] == "BET_END_STATE_IDENTIFIER"
            && response["gameData"]["stakeCostUuid"] == OFFER
            && amount(&response["betCost"])? == cost
            && before.checked_sub(cost).and_then(|n| n.checked_add(payout)) == Some(after),
        "GPAS round did not close and reconcile"
    );
    Ok(RoundOutcome {
        native_round_id: None,
        currency: currency.into(),
        currency_source: "native_response".into(),
        monetary_unit: "native".into(),
        balance_before: before.to_string(),
        balance_after: after.to_string(),
        cost: cost.to_string(),
        payout: payout.to_string(),
        native_closed: true,
        checks: BTreeMap::from([("gpas_balance_notification".into(), true)]),
        native_data: json!({"game":CODE,"offer":OFFER}),
    })
}
