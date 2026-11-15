use crate::{
    context::RunContext,
    model::{
        Game, Mode, ModeKind, RoundOutcome, decimal, exact_add, exact_div100, exact_mul, exact_sub,
    },
};
use anyhow::{Context, Result, bail, ensure};
use rust_decimal::Decimal;
use serde_json::{Value, json};
use std::collections::BTreeMap;

fn anonymous_key_below(upper: u64, mut entropy: impl FnMut() -> u64) -> Result<String> {
    ensure!(upper > 0, "invalid anonymous launch key range");
    // Reject the short residue prefix so every value below upper is equally likely.
    let threshold = upper.wrapping_neg() % upper;
    loop {
        let candidate = entropy();
        if candidate >= threshold {
            return Ok((candidate % upper).to_string());
        }
    }
}

fn anonymous_key() -> Result<String> {
    anonymous_key_below(crate::model::now_ms(), || {
        let bytes = uuid::Uuid::new_v4().into_bytes();
        // These eight UUIDv4 bytes contain only random bits, excluding version/variant.
        u64::from_be_bytes([
            bytes[0], bytes[1], bytes[2], bytes[3], bytes[4], bytes[5], bytes[14], bytes[15],
        ])
    })
}

fn money(v: &Value) -> Result<Decimal> {
    let s = match v {
        Value::String(s) => s.clone(),
        Value::Number(n) => n.to_string(),
        _ => bail!("missing or invalid native amount"),
    };
    let n = decimal(&s)?;
    ensure!(n >= Decimal::ZERO, "negative native amount");
    Ok(n)
}
fn required<'a>(v: &'a Value, k: &str) -> Result<&'a str> {
    v.get(k)
        .and_then(Value::as_str)
        .filter(|x| !x.is_empty())
        .with_context(|| format!("missing {k}"))
}
fn native_price(info: &Value, action: &str, kind: ModeKind) -> Result<Decimal> {
    ensure!(
        action
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'_')
            && !action.is_empty(),
        "unsafe native action"
    );
    let compatible = match kind {
        ModeKind::Normal => action == "main",
        ModeKind::Purchase => action == "buy" || action.starts_with("buy_"),
        ModeKind::AnteBet | ModeKind::Special => action == "bet" || action.starts_with("bet_"),
        _ => false,
    };
    ensure!(compatible, "inventory mode does not match native action");
    if action == "buy" {
        ensure!(
            money(
                info.pointer("/config/buy_configuration/BUY")
                    .context("missing buy configuration")?
            )? > Decimal::ZERO,
            "buy configuration not offered"
        );
    }
    if action == "bet" {
        ensure!(
            money(
                info.pointer("/config/special_bets_configuration/BET")
                    .context("missing bet configuration")?
            )? > Decimal::ZERO,
            "bet configuration not offered"
        );
    }
    let values = info
        .pointer(&format!("/bets/{action}/available"))
        .and_then(Value::as_array)
        .context("native action not offered")?;
    let parsed = values.iter().map(money).collect::<Result<Vec<_>>>()?;
    let price = *parsed.iter().min().context("empty native offer")?;
    ensure!(price > Decimal::ZERO, "invalid price");
    Ok(price)
}
fn audit_packets(packets: &[Value], id: &str) -> Result<Decimal> {
    let mut win = Decimal::ZERO;
    for packet in packets {
        ensure!(
            required(packet, "roundId")? == id,
            "continuation owner changed"
        );
        let wager = packet.get("wager").context("wager missing")?;
        let steps = wager
            .get("data")
            .and_then(Value::as_array)
            .context("wager steps missing")?;
        let mut sum = Decimal::ZERO;
        for step in steps {
            sum = exact_add(sum, money(&step["action_winnings"])?)?;
            ensure!(
                sum == money(&step["round_winnings"])?,
                "cumulative winnings mismatch"
            );
        }
        let packet_win = money(&wager["win"])?;
        ensure!(
            sum == exact_mul(packet_win, Decimal::from(100))?,
            "native payout units mismatch"
        );
        win = exact_add(win, packet_win)?;
    }
    let last = packets.last().context("no packets")?;
    let wager = &last["wager"];
    ensure!(
        wager["next"].as_array().is_some_and(|a| a.is_empty()),
        "unreviewed pending action"
    );
    ensure!(
        wager["data"]
            .as_array()
            .and_then(|a| a.last())
            .and_then(|s| s["closes_game_round"].as_bool())
            == Some(true),
        "native round not closed"
    );
    Ok(win)
}
fn conditional_price(info: &Value, packet: &Value, game: &str, action: &str) -> Result<Decimal> {
    ensure!(
        game == "bloody-mary" && matches!(action, "extra_spin_fs" | "extra_spin_sfs"),
        "conditional action outside reviewed contract"
    );
    let state = if action == "extra_spin_fs" {
        "SESSION_FS"
    } else {
        "SESSION_SFS"
    };
    let step = packet
        .pointer("/wager/data")
        .and_then(Value::as_array)
        .and_then(|v| v.last())
        .context("conditional step missing")?;
    ensure!(step["state"] == state, "conditional state mismatch");
    let offered = step["pending_actions"]
        .as_array()
        .context("conditional offer missing")?
        .iter()
        .filter(|v| v["name"] == action && v["kind"] == "Buy")
        .collect::<Vec<_>>();
    let configured = info
        .pointer(&format!("/config/per_state/{state}/continuation_offers"))
        .and_then(Value::as_array)
        .context("conditional configuration missing")?
        .iter()
        .flat_map(|v| v["actions"].as_array().into_iter().flatten())
        .filter(|v| v["name"] == action && v["kind"] == "Buy")
        .collect::<Vec<_>>();
    ensure!(
        offered.len() == 1
            && configured.len() == 1
            && offered[0]["display"] == configured[0]["display"]
            && offered[0]["payload"] == configured[0]["payload"],
        "conditional offer configuration mismatch"
    );
    let display = &offered[0]["display"];
    let counter_name = required(display, "cost_counter")?;
    let counter = step["counters"]
        .get(counter_name)
        .context("conditional cost counter missing")?;
    let base = money(&step["bet_amount"])?;
    let base_key = match &step["bet_amount"] {
        Value::String(s) => s.clone(),
        v => v.to_string(),
    };
    let index = counter["value_per_bet"]
        .get(&base_key)
        .unwrap_or(&counter["default_value"])
        .as_u64()
        .context("conditional cost counter invalid")? as usize;
    let factor = display["cost_table"]
        .as_array()
        .and_then(|x| x.get(index))
        .context("conditional cost table missing")?;
    let cost = money(&offered[0]["cost"])?;
    ensure!(
        cost > Decimal::ZERO && cost == exact_mul(base, money(factor)?)? && cost.fract().is_zero(),
        "conditional native price mismatch"
    );
    exact_div100(cost)
}
fn same_currency(v: &Value, currency: &str) -> Result<()> {
    if let Some(x) = v.get("currency") {
        ensure!(x.as_str() == Some(currency), "native currency changed");
    }
    Ok(())
}

/// `wallet` is the nonsecret wallet identifier from the official public catalogue;
/// `currency` is the expected ISO currency from that launch configuration.
pub async fn execute(
    ctx: &RunContext,
    game: &Game,
    mode: &Mode,
    settings: &Value,
) -> Result<RoundOutcome> {
    let (parent, conditional) = match mode.key.split_once("::offer::") {
        Some((p, a)) => {
            ensure!(
                mode.kind == ModeKind::Purchase,
                "conditional classification mismatch"
            );
            (p, Some(a))
        }
        None => (mode.key.as_str(), None),
    };
    let wallet = required(settings, "wallet")
        .context("settings.wallet required from official public catalogue")?;
    let expected_currency = required(settings, "currency")
        .context("settings.currency required from reviewed demo launch")?;
    ensure!(
        expected_currency.len() >= 3
            && expected_currency.bytes().all(|x| x.is_ascii_alphanumeric()),
        "invalid expected currency"
    );
    let key = anonymous_key()?;
    let api = "https://demo.spinart.cloud";
    let mut headers = BTreeMap::new();
    headers.insert("Origin".into(), "https://cdn-demo.spinart.cloud".into());
    headers.insert("Referer".into(), "https://cdn-demo.spinart.cloud/".into());
    let cfg=ctx.json("configuration",&format!("{api}/cfg"),&json!({"server":api,"wallet":wallet,"operator":"demo","gameCode":game.id,"key":key,"language":"en"}),headers.clone(),false).await?;
    ensure!(
        cfg["adapter"] == "standard" && cfg["loadGame"] == true,
        "unsupported demo configuration"
    );
    let auth=ctx.json("authentication",&format!("{api}/authenticate"),&json!({"wallet":wallet,"operator":"demo","key":key,"provider":"peterandsons","game":game.id}),headers.clone(),false).await?;
    ensure!(
        auth["currencyDecimals"] == 2,
        "unreviewed currency precision"
    );
    let token = required(&auth, "token")?;
    let currency = expected_currency;
    let observed_currency = auth
        .get("currency")
        .filter(|v| !v.is_null())
        .map(|v| v.as_str().context("invalid native authentication currency"))
        .transpose()?;
    let currency_source = crate::model::currency_binding(observed_currency, currency)?;
    let before = money(&auth["balance"])?;
    headers.insert("Authorization".into(), format!("Bearer {token}"));
    let common = json!({"game":game.id,"provider":"peterandsons"});
    let recover = ctx
        .json(
            "recovery",
            &format!("{api}/game/recover"),
            &json!({"game":game.id,"provider":"peterandsons","complete":false}),
            headers.clone(),
            false,
        )
        .await?;
    ensure!(
        recover["rounds"].as_array().is_some_and(|v| v.is_empty()),
        "fresh demo has pending rounds"
    );
    same_currency(&recover, currency)?;
    let info = ctx
        .json(
            "information",
            &format!("{api}/game/info"),
            &common,
            headers.clone(),
            false,
        )
        .await?;
    same_currency(&info, currency)?;
    let parent_kind = if parent == "main" {
        ModeKind::Normal
    } else if parent.starts_with("buy_") || parent == "buy" {
        ModeKind::Purchase
    } else {
        ModeKind::AnteBet
    };
    let price = native_price(
        &info,
        parent,
        if conditional.is_some() {
            parent_kind
        } else {
            mode.kind
        },
    )?;
    ensure!(before >= price, "insufficient demo balance");
    ctx.save_session(&json!({"provider":"peterandsons","game":game.id,"wallet":wallet,"key":key,"token":token,"currency":currency}))?;
    let bet: Value = serde_json::from_str(&price.to_string())?;
    let request = json!({"game":game.id,"provider":"peterandsons","action":parent,"complete":false,"asyncWin":false,"bet":bet});
    let first = ctx
        .json(
            "play",
            &format!("{api}/game/play"),
            &request,
            headers.clone(),
            true,
        )
        .await?;
    same_currency(&first, currency)?;
    let id = required(&first, "roundId")?.to_owned();
    ensure!(
        money(&first["balance"])? == exact_sub(before, price)?,
        "entry debit mismatch"
    );
    let mut packets = vec![first];
    let mut total_cost = price;
    let mut selected = false;
    for _ in 0..ctx.max_steps() {
        let current = packets.last().unwrap();
        let next = current
            .pointer("/wager/next")
            .and_then(Value::as_array)
            .context("missing next actions")?;
        if next.is_empty() {
            break;
        }
        if let Some(action) = conditional
            && !selected
            && next.iter().any(|x| x == action)
        {
            let extra = conditional_price(&info, current, &game.id, action)?;
            ensure!(
                before >= exact_add(total_cost, extra)?,
                "insufficient conditional funds"
            );
            let amount: Value = serde_json::from_str(&extra.to_string())?;
            let request = json!({"game":game.id,"provider":"peterandsons","action":action,"complete":false,"asyncWin":false,"bet":amount,"roundId":id});
            let reply = ctx
                .json(
                    "conditional_purchase",
                    &format!("{api}/game/play"),
                    &request,
                    headers.clone(),
                    true,
                )
                .await?;
            same_currency(&reply, currency)?;
            ensure!(
                required(&reply, "roundId")? == id,
                "conditional owner changed"
            );
            total_cost = exact_add(total_cost, extra)?;
            ensure!(
                money(&reply["balance"])? == exact_sub(before, total_cost)?,
                "conditional debit mismatch"
            );
            packets.push(reply);
            selected = true;
            continue;
        }
        ensure!(
            next.iter().any(|v| v == "take_round"),
            "unreviewed pending round or choice"
        );
        let continuation = json!({"game":game.id,"provider":"peterandsons","action":"take_round","complete":false,"asyncWin":false,"roundId":id});
        let reply = ctx
            .json(
                "take_round",
                &format!("{api}/game/play"),
                &continuation,
                headers.clone(),
                true,
            )
            .await?;
        same_currency(&reply, currency)?;
        ensure!(
            required(&reply, "roundId")? == id,
            "continuation owner changed"
        );
        if !reply["balance"].is_null() {
            ensure!(
                money(&reply["balance"])? == exact_sub(before, total_cost)?,
                "unexpected continuation wallet change"
            );
        }
        packets.push(reply);
    }
    let requested_offer_seen = conditional.is_none() || selected;
    let payout = audit_packets(&packets, &id)?;
    let completion = ctx
        .json(
            "complete",
            &format!("{api}/game/complete"),
            &json!({"game":game.id,"provider":"peterandsons","roundId":id,"asyncWin":false}),
            headers,
            true,
        )
        .await?;
    same_currency(&completion, currency)?;
    let after = money(&completion["balance"])?;
    ensure!(
        money(&completion["finalWin"])? == payout,
        "settlement payout mismatch"
    );
    let checks = BTreeMap::from([
        ("demo".into(), true),
        ("offer".into(), true),
        ("entry_debit".into(), true),
        ("native_payout".into(), true),
        ("requested_conditional_offer".into(), requested_offer_seen),
    ]);
    Ok(RoundOutcome {
        native_round_id: Some(id),
        currency: currency.into(),
        monetary_unit: "major".into(),
        currency_source: currency_source.into(),
        balance_before: before.to_string(),
        balance_after: after.to_string(),
        cost: total_cost.to_string(),
        payout: payout.to_string(),
        native_closed: true,
        checks,
        native_data: json!({"information":info,"play_request":request,"packets":packets,"completion":completion}),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn anonymous_key_rejects_the_biased_tail_and_uses_the_launcher_domain() {
        let mut samples = [0, 5, 19].into_iter();
        assert_eq!(
            anonymous_key_below(10, || samples.next().unwrap()).unwrap(),
            "9"
        );
        assert!(samples.next().is_none());
        assert_eq!(anonymous_key_below(10, || 10).unwrap(), "0");
        assert_eq!(anonymous_key_below(1, || u64::MAX).unwrap(), "0");
        assert!(anonymous_key_below(0, || panic!("invalid range consumed entropy")).is_err());
    }
    #[test]
    fn fresh_anonymous_keys_are_decimal_values_below_epoch_milliseconds() {
        for _ in 0..16 {
            let key = anonymous_key().unwrap();
            assert!(key.bytes().all(|c| c.is_ascii_digit()));
            assert!(key.parse::<u64>().unwrap() < crate::model::now_ms());
        }
    }
    #[test]
    fn native_offer_and_mode_family_are_checked() {
        let info = json!({"bets":{"main":{"available":[0.2,0.1]},"buy_FS":{"available":[10]},"bet_X":{"available":[0.3]}}});
        assert_eq!(
            native_price(&info, "main", ModeKind::Normal)
                .unwrap()
                .to_string(),
            "0.1"
        );
        assert!(native_price(&info, "buy_FS", ModeKind::Normal).is_err());
        assert!(native_price(&info, "unknown", ModeKind::Purchase).is_err());
    }
    #[test]
    fn conditional_offer_requires_matching_price_and_configuration() {
        let offer = json!({"name":"extra_spin_fs","kind":"Buy","display":{"cost_counter":"x","cost_table":[3]},"payload":{},"cost":300});
        let info = json!({"config":{"per_state":{"SESSION_FS":{"continuation_offers":[{"actions":[offer.clone()]}]}}}});
        let packet = json!({"wager":{"data":[{"state":"SESSION_FS","bet_amount":100,"counters":{"x":{"default_value":0,"value_per_bet":{}}},"pending_actions":[offer]}]}});
        assert_eq!(
            conditional_price(&info, &packet, "bloody-mary", "extra_spin_fs").unwrap(),
            Decimal::from(3)
        );
        assert!(conditional_price(&info, &packet, "other-game", "extra_spin_fs").is_err());
        let mut changed = packet;
        changed["wager"]["data"][0]["pending_actions"][0]["cost"] = json!(301);
        assert!(conditional_price(&info, &changed, "bloody-mary", "extra_spin_fs").is_err());
    }
    #[test]
    fn payout_is_independently_checked_and_closure_required() {
        let packet = json!({"roundId":"r","balance":9.9,"wager":{"next":[],"win":0.2,"data":[{"action_winnings":20,"round_winnings":20,"closes_game_round":true}]}});
        assert_eq!(
            audit_packets(std::slice::from_ref(&packet), "r")
                .unwrap()
                .to_string(),
            "0.2"
        );
        let mut bad = packet;
        bad["wager"]["data"][0]["round_winnings"] = json!(21);
        assert!(audit_packets(&[bad], "r").is_err());
    }
}
