//! Native capture connector derived from standalone info/1spin4win/codigo/onespin4win.rs.
//! Published source SHA-256: 46daec91aa1f7f733034e6f62783c56acdbe4e296ff64e052c6ed62d0043899b
//! Reference transport: game-runner/src/adapters/onespin4win.rs; no runtime dependency.
//! FREEPLAY frames and game-specific pricing and selectors from the audited capture bank.
use crate::{
    context::{DecodedFrame, NativeSocket, RunContext, SocketPayload},
    model::{Completion, Game, Mode, ModeKind},
};
use anyhow::{Context, Result, ensure};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::LazyLock, time::Duration};

const URL: &str = "wss://gs.1spin4win.com/games";
const ORIGIN: &str = "https://gs.1spin4win.com:10443";

#[derive(Deserialize)]
struct Pricing {
    lines: u64,
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
        return Err(crate::model::unknown_event(
            "unexpected binary 1spin4win frame".to_string(),
        ));
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
    round_action: bool,
) -> Result<Value> {
    let packet = format!("A/u2{}", json!({"key":"","type":kind,"data":data}));
    ctx.ws_codec_controlled(
        socket,
        label,
        SocketPayload::Text(packet),
        round_action,
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

pub async fn execute(
    ctx: &RunContext,
    game: &Game,
    mode: &Mode,
    _settings: &Value,
) -> Result<Completion> {
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
    ctx.save_session(
        &json!({"provider":"1spin4win","game":game.id,"mode":"FREEPLAY",
        "currency":"EUR","lines":lines,"index":index,"socket":URL,
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
        ensure!(frame["type"] == 3, "unexpected native response type");
        let state = amount(&frame, "st")
            .map_err(|_| crate::model::unknown_event("1spin4win native state missing"))?;
        if !terminal_state(state, step)? {
            continue;
        }
        return Ok(Completion {
            native_round_id: None,
            details: json!({"lines":lines,"coin":coin,"bet_index":index,"steps":step+1,
                "terminal_state":state,"entry_selector":pricing.entry,
                "continuation_selector":pricing.continuation,"pricing_source_sha256":pricing.source_sha256}),
        });
    }
    Err(crate::model::unknown_event(
        "1spin4win native round exceeded the continuation limit",
    ))
}

fn terminal_state(state: u64, step: usize) -> Result<bool> {
    match state {
        3 if step == 0 => Ok(true),
        12 => Ok(true),
        5 | 6 => Ok(false),
        _ => Err(crate::model::unknown_event(format!(
            "1spin4win unknown state {state}"
        ))),
    }
}

#[cfg(test)]
mod capture_tests {
    use super::*;

    #[test]
    fn terminal_without_wallet_and_unknown_state() {
        let frame = decode(&SocketPayload::Text(r#"{"type":3,"st":12}"#.into()))
            .unwrap()
            .values
            .remove(0);
        assert!(terminal_state(amount(&frame, "st").unwrap(), 1).unwrap());
        assert!(
            terminal_state(77, 0)
                .unwrap_err()
                .downcast_ref::<crate::model::UnknownEvent>()
                .is_some()
        );
    }
    #[test]
    fn native_hex_offer_uses_published_index() {
        assert_eq!(
            offer("2151112131415161718191a21421e22823223c2462502642962fa31f4").unwrap(),
            (0, 1)
        );
        assert!(offer("1211").is_err());
    }
}
