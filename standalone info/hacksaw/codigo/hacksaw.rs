use crate::{
    context::RunContext,
    model::{Game, Mode, ModeKind, RoundOutcome, decimal, exact_add, exact_mul},
};
use anyhow::{Context, Result, bail, ensure};
use rust_decimal::Decimal;
use serde_json::{Value, json};
use std::collections::BTreeMap;

fn amount(v: &Value) -> Result<Decimal> {
    let s = match v {
        Value::String(s) => s.clone(),
        Value::Number(n) => n.to_string(),
        _ => bail!("missing native amount"),
    };
    let n = decimal(&s)?;
    ensure!(n >= Decimal::ZERO, "negative native amount");
    Ok(n)
}
fn id(v: &Value) -> Result<String> {
    match v {
        Value::String(s) if !s.is_empty() => Ok(s.clone()),
        Value::Number(n) => Ok(n.to_string()),
        _ => bail!("missing native identifier"),
    }
}
fn offer(auth: &Value, key: &str) -> Result<Decimal> {
    let offers = auth["bonusGames"]
        .as_array()
        .context("missing native offers")?;
    let mut matching = offers
        .iter()
        .filter(|v| v["bonusGameId"].as_str() == Some(key));
    let item = matching
        .next()
        .context("inventory mode not offered in fresh session")?;
    ensure!(matching.next().is_none(), "duplicate native offer");
    let multiplier = amount(&item["betCostMultiplier"])?;
    ensure!(multiplier > Decimal::ZERO, "invalid native price");
    Ok(multiplier)
}
fn audit(responses: &[Value], round_id: &str) -> Result<Decimal> {
    ensure!(!responses.is_empty(), "missing round responses");
    let mut win = Decimal::ZERO;
    for response in responses {
        ensure!(response["statusCode"].as_i64() == Some(0), "provider error");
        let round = &response["round"];
        ensure!(id(&round["roundId"])? == round_id, "round identity changed");
        if let Some(events) = round["events"].as_array() {
            for event in events {
                if !event["wa"].is_null() {
                    win = exact_add(win, amount(&event["wa"])?)?;
                }
            }
        }
    }
    let last = &responses.last().unwrap()["round"];
    ensure!(
        last["status"].as_str() == Some("completed"),
        "round not closed"
    );
    ensure!(
        last["possibleActions"].is_null()
            || last["possibleActions"]
                .as_array()
                .is_some_and(|a| a.is_empty()),
        "closed round has actions"
    );
    Ok(win)
}
async fn call(ctx: &RunContext, endpoint: &str, body: Value, financial: bool) -> Result<Value> {
    let response = ctx
        .json(
            endpoint,
            &format!("https://rgs-demo.hacksawgaming.com/api/play/{endpoint}"),
            &body,
            BTreeMap::new(),
            financial,
        )
        .await?;
    ensure!(
        response["statusCode"].as_i64() == Some(0),
        "Hacksaw provider error: {}",
        response["statusCode"]
    );
    Ok(response)
}
pub async fn execute(
    ctx: &RunContext,
    game: &Game,
    mode: &Mode,
    _settings: &Value,
) -> Result<RoundOutcome> {
    ensure!(
        !game.id.is_empty() && game.id.bytes().all(|b| b.is_ascii_digit()),
        "invalid game id"
    );
    let gid: u64 = game.id.parse()?;
    let variant = mode.key == "mode-extreme" && game.id == "1426";
    match mode.kind {
        ModeKind::Normal => ensure!(mode.key == "normal", "unsupported normal selector"),
        ModeKind::Purchase | ModeKind::Booster if !variant => {}
        ModeKind::Variant if variant => {}
        ModeKind::Purchase if variant => {}
        _ => bail!("unsupported Hacksaw mode"),
    }
    let version_response = ctx
        .get(
            "version",
            &format!(
                "https://static-live.hacksawgaming.com/{}/version.json",
                game.id
            ),
        )
        .await?;
    ensure!(
        (200..300).contains(&version_response.status),
        "version HTTP error"
    );
    let version_json: Value = serde_json::from_str(&version_response.body)?;
    let version = version_json["version"]
        .as_str()
        .context("missing version")?;
    let parts: Vec<_> = version.split('.').collect();
    ensure!(
        (2..=4).contains(&parts.len())
            && parts
                .iter()
                .all(|p| !p.is_empty() && p.bytes().all(|b| b.is_ascii_digit())),
        "invalid published version"
    );
    let settings = call(
        ctx,
        "partnerSettings",
        json!({"partner":"demo","currency":"EUR","gameId":gid,"usePartnerCurrency":true}),
        false,
    )
    .await?;
    let auth = call(ctx, "authenticate", json!({"seq":1,"partner":"demo","gameId":gid,"gameVersion":version,"currency":"EUR","languageCode":"en-us","mode":2,"branding":"default","channel":1,"userAgent":"Mozilla/5.0","token":"demo","currencyMultiplier":1}), false).await?;
    ensure!(
        auth["name"] == "Demo"
            && (auth["roundStatus"].is_null()
                || auth["roundStatus"] == false
                || auth["roundStatus"] == ""
                || auth["roundStatus"] == 0)
            && (auth["roundId"].is_null() || auth["roundId"] == "0" || auth["roundId"] == 0),
        "not a fresh public demo"
    );
    ensure!(
        auth["accountBalance"]["currencyCode"] == "EUR",
        "unexpected demo currency"
    );
    ensure!(
        id(&auth["gameId"])? == game.id,
        "authenticated game id mismatch"
    );
    let session = auth["sessionUuid"]
        .as_str()
        .filter(|s| !s.is_empty())
        .context("missing session")?;
    let before = amount(&auth["accountBalance"]["balance"])?;
    let bets = auth["betLevels"]
        .as_array()
        .context("missing published bets")?;
    let bet = bets
        .iter()
        .map(amount)
        .collect::<Result<Vec<_>>>()?
        .into_iter()
        .min()
        .context("empty published bets")?;
    ensure!(
        bet > Decimal::ZERO && bet.fract() == Decimal::ZERO,
        "invalid published bet"
    );
    let bonus = if mode.kind != ModeKind::Normal && !variant {
        Some(mode.key.as_str())
    } else {
        None
    };
    let multiplier = if let Some(key) = bonus {
        offer(&auth, key)?
    } else {
        Decimal::ONE
    };
    let cost = exact_mul(bet, multiplier)?;
    ensure!(before >= cost, "insufficient demo balance");
    let mut wager = json!({"betAmount":bet.to_string()});
    if let Some(key) = bonus {
        wager["buyBonus"] = json!(key);
    }
    if game.id == "1426" {
        let volatility = if variant {
            "extreme"
        } else if let Some(key) = bonus {
            key.rsplit('_').next().unwrap_or("")
        } else {
            "low"
        };
        ensure!(
            volatility == "low" || volatility == "extreme",
            "unpublished volatility selector"
        );
        wager["customData"] = json!({"volatility":volatility});
    }
    ctx.save_session(&json!({"provider":"hacksaw","game":game.id,"version":version,"sessionUuid":session,"currency":"EUR"}))?;
    let mut seq = 2u64;
    let mut response = call(ctx, "bet", json!({"seq":seq,"sessionUuid":session,"bets":[wager],"offerId":null,"promotionId":null,"autoplay":false}), true).await?;
    let round_id = id(&response["round"]["roundId"])?;
    let mut responses = vec![response.clone()];
    for _ in 0..ctx.max_steps() {
        let round = &response["round"];
        ensure!(id(&round["roundId"])? == round_id, "round identity changed");
        if round["status"] == "completed" {
            break;
        }
        let action = if let Some(actions) = round["possibleActions"]
            .as_array()
            .filter(|a| !a.is_empty())
        {
            actions[0]
                .as_str()
                .filter(|s| !s.is_empty())
                .context("invalid native action")?
                .to_string()
        } else if round["status"] == "wfwpc" {
            "win_presentation_complete".to_string()
        } else {
            bail!("unsupported native round state: {}", round["status"]);
        };
        seq += 1;
        response = call(ctx, "bet", json!({"seq":seq,"sessionUuid":session,"roundId":round["roundId"],"continueInstructions":{"action":action}}), true).await?;
        responses.push(response.clone());
    }
    let win = audit(&responses, &round_id)?;
    ensure!(
        response["accountBalance"]["currencyCode"] == "EUR",
        "final currency mismatch"
    );
    let after = amount(&response["accountBalance"]["balance"])?;
    let mut checks = BTreeMap::new();
    checks.insert("fresh_demo_and_currency".into(), true);
    checks.insert("native_offer".into(), true);
    Ok(RoundOutcome {
        native_round_id: Some(round_id),
        currency: "EUR".into(),
        monetary_unit: "native".into(),
        currency_source: "native_response".into(),
        balance_before: before.to_string(),
        balance_after: after.to_string(),
        cost: cost.to_string(),
        payout: win.to_string(),
        native_closed: true,
        checks,
        native_data: json!({"monetary_unit":"native_units_unverified", "currency_decimals":null, "currency_unit_evidence":"not published in available protocol sources", "version":version,"settings":settings,"authentication":auth,"bet":bet.to_string(),"multiplier":multiplier.to_string(),"responses":responses}),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn advertised_control_and_exact_payout() {
        let auth = json!({"bonusGames":[{"bonusGameId":"fs","betCostMultiplier":100}]});
        assert_eq!(offer(&auth, "fs").unwrap().to_string(), "100");
        assert!(offer(&auth, "absent").is_err());
        let responses = vec![
            json!({"statusCode":0,"round":{"roundId":"r","status":"completed","possibleActions":[],"events":[{"wa":"12.5"}]},"accountBalance":{"balance":"912.5","currencyCode":"EUR"}}),
        ];
        assert_eq!(audit(&responses, "r").unwrap().to_string(), "12.5");
    }
    #[test]
    fn rejects_changed_round_and_unclosed() {
        assert!(
            audit(
                &[json!({"statusCode":0,"round":{"roundId":"other","status":"completed"}})],
                "r"
            )
            .is_err()
        );
        assert!(audit(&[json!({"statusCode":0,"round":{"roundId":"r","status":"completed","possibleActions":["next"]}})], "r").is_err());
    }
}
