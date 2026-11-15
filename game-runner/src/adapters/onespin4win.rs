//! FREEPLAY frames and game-specific pricing and selectors from the audited capture bank.
use crate::{
    context::{DecodedFrame, NativeSocket, RunContext, SocketPayload},
    model::{Game, Mode, ModeKind, RoundOutcome, wallet_matches},
};
use anyhow::{Context, Result, bail, ensure};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::LazyLock, time::Duration};

const URL: &str = "wss://gs.1spin4win.com/games";
const ORIGIN: &str = "https://gs.1spin4win.com:10443";

#[derive(Deserialize)]
struct Pricing {
    lines: u64,
    factor: u64,
    entry: Option<u64>,
    continuation: Option<u64>,
    source_sha256: String,
}

static PRICING: LazyLock<BTreeMap<String, BTreeMap<String, Pricing>>> = LazyLock::new(|| {
    serde_json::from_str(include_str!("../../bindings/1spin4win.json"))
        .expect("embedded 1spin4win bindings must be valid")
});

fn pricing(game: &Game, mode: &Mode) -> Option<&'static Pricing> {
    let expected_kind = match mode.key.as_str() {
        "normal" => ModeKind::Normal,
        "compra" => ModeKind::Purchase,
        "antebet" => ModeKind::AnteBet,
        _ => return None,
    };
    if mode.kind != expected_kind {
        return None;
    }
    PRICING.get(&game.id)?.get(&mode.key)
}

pub fn supports(game: &Game, mode: &Mode) -> bool {
    pricing(game, mode).is_some()
}

fn play_data(pricing: &Pricing, index: usize, first: bool) -> String {
    let base = format!("{},{index},0", pricing.lines);
    match if first {
        pricing.entry
    } else {
        pricing.continuation
    } {
        Some(selector) => format!("{base},{selector}"),
        None => base,
    }
}

fn read_hex(encoded: &mut &[u8]) -> Result<u64> {
    let (&size, rest) = encoded.split_first().context("missing native hex length")?;
    let size = (size as char)
        .to_digit(16)
        .context("invalid native hex length")? as usize;
    ensure!(size > 0 && size <= rest.len(), "truncated native hex value");
    let (value, tail) = rest.split_at(size);
    *encoded = tail;
    Ok(u64::from_str_radix(std::str::from_utf8(value)?, 16)?)
}

fn offer(encoded: &str) -> Result<(usize, u64)> {
    let mut encoded = encoded.as_bytes();
    let count = read_hex(&mut encoded)?;
    ensure!(
        count > 0 && count <= encoded.len() as u64 / 2,
        "invalid native bet count"
    );
    let mut bets = Vec::new();
    for index in 0..count as usize {
        let coin = read_hex(&mut encoded)?;
        ensure!(coin > 0, "invalid native coin value");
        bets.push((index, coin));
    }
    ensure!(encoded.is_empty(), "trailing bytes in native bet table");
    bets.into_iter()
        .min_by_key(|&(_, coin)| coin)
        .context("no bet offered")
}

fn decode(frame: &SocketPayload) -> Result<DecodedFrame> {
    let SocketPayload::Text(text) = frame else {
        bail!("unexpected binary 1spin4win frame");
    };
    if text == "pns" {
        return Ok(DecodedFrame {
            values: vec![],
            replies: vec![SocketPayload::Text("A/pns".into())],
        });
    }
    Ok(DecodedFrame {
        values: vec![serde_json::from_str(text)?],
        replies: vec![],
    })
}

async fn command(
    ctx: &RunContext,
    socket: &mut NativeSocket,
    label: &str,
    kind: &str,
    data: &str,
    financial: bool,
) -> Result<Value> {
    let packet = format!("A/u2{}", json!({"key":"","type":kind,"data":data}));
    ctx.ws_codec_controlled(
        socket,
        label,
        SocketPayload::Text(packet),
        financial,
        None,
        decode,
    )
    .await
}

fn amount(frame: &Value, key: &str) -> Result<u64> {
    frame[key]
        .as_u64()
        .with_context(|| format!("invalid native {key}"))
}

pub async fn execute(ctx: &RunContext, game: &Game, mode: &Mode) -> Result<RoundOutcome> {
    let pricing =
        pricing(game, mode).context("missing reviewed 1spin4win game and mode pricing")?;
    let lines = pricing.lines;
    let mut socket = ctx.websocket(URL, ORIGIN, None, BTreeMap::new()).await?;
    let init = command(
        ctx,
        &mut socket,
        "freeplay_init",
        "0",
        &format!(",,freeplay,{},01,1,EUR,test", game.id),
        false,
    )
    .await?;
    ensure!(
        init["type"] == 1 && init["cp"] == "FREEPLAY" && init["l"] == lines && init["st"] == 0,
        "1spin4win did not confirm a fresh idle FREEPLAY session"
    );
    let (index, coin) = offer(init["bs"].as_str().context("native bet table missing")?)?;
    let cost = coin
        .checked_mul(pricing.factor)
        .context("native bet overflow")?;
    let before = amount(&init, "b")?;
    ensure!(before >= cost, "insufficient fictional demo funds");
    ctx.save_session(
        &json!({"provider":"1spin4win","game":game.id,"mode":"FREEPLAY",
        "currency":"EUR","lines":lines,"index":index,"cost":cost,"socket":URL,
        "mode_key":mode.key,"pricing_source_sha256":pricing.source_sha256}),
    )?;
    for step in 0..ctx.max_steps().min(400) {
        tokio::time::sleep(Duration::from_secs(1)).await;
        let label = if step == 0 {
            "round_entry"
        } else {
            "round_continuation"
        };
        let data = play_data(pricing, index, step == 0);
        let frame = command(ctx, &mut socket, label, "1", &data, true).await?;
        ensure!(
            frame["type"] == 3 && frame["l"] == lines && frame["b3"] == index,
            "unexpected native receipt identity or stake"
        );
        let state = amount(&frame, "st")?;
        let after = amount(&frame, "b")?;
        if step == 0 && state != 3 {
            ensure!(
                before.checked_sub(cost) == Some(after),
                "1spin4win entry debit changed"
            );
        }
        let payout = match state {
            3 if step == 0 => amount(&frame, "w")?,
            12 => amount(&frame, "b11")?,
            5 | 6 => continue,
            _ => bail!("unreviewed 1spin4win round state {state}"),
        };
        ensure!(
            wallet_matches(before.into(), after.into(), cost.into(), payout.into()),
            "1spin4win native wallet did not reconcile"
        );
        return Ok(RoundOutcome {
            native_round_id: None,
            currency: "EUR".into(),
            monetary_unit: "native".into(),
            currency_source: "launcher_parameter".into(),
            balance_before: before.to_string(),
            balance_after: after.to_string(),
            cost: cost.to_string(),
            payout: payout.to_string(),
            native_closed: true,
            checks: BTreeMap::from([
                ("fresh_freeplay".into(), true),
                ("independent_native_offer".into(), true),
            ]),
            native_data: json!({"lines":lines,"coin":coin,"bet_index":index,"steps":step+1,
                "terminal_state":state,"entry_selector":pricing.entry,
                "continuation_selector":pricing.continuation,"pricing_source_sha256":pricing.source_sha256}),
        });
    }
    bail!("1spin4win native round exceeded the continuation limit")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn purchased_and_ante_rounds_use_their_own_continuation_selectors() {
        let purchase = Pricing {
            lines: 25,
            factor: 47,
            entry: Some(3),
            continuation: None,
            source_sha256: String::new(),
        };
        let ante = Pricing {
            lines: 25,
            factor: 4,
            entry: Some(1),
            continuation: Some(1),
            source_sha256: String::new(),
        };
        assert_eq!(play_data(&purchase, 2, true), "25,2,0,3");
        assert_eq!(play_data(&purchase, 2, false), "25,2,0");
        assert_eq!(play_data(&ante, 2, true), "25,2,0,1");
        assert_eq!(play_data(&ante, 2, false), "25,2,0,1");
    }

    #[test]
    fn native_bet_table_matches_the_capture_and_rejects_trailing_or_truncated_data() {
        assert_eq!(
            offer("2151112131415161718191a21421e22823223c2462502642962fa31f4").unwrap(),
            (0, 1)
        );
        assert!(offer("1211").is_err());
        assert!(offer("11110").is_err());
    }
}
