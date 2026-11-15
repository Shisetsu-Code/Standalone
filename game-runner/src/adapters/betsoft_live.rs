//! Betsoft public FREE sessions for reviewed legacy slots.
use crate::{
    context::RunContext,
    model::{
        Game, Mode, ModeKind, RoundOutcome, decimal, exact_add, exact_mul, now_ms, wallet_matches,
    },
};
use anyhow::{Context, Result, bail, ensure};
use regex::Regex;
use rust_decimal::Decimal;
use serde_json::json;
use std::{collections::BTreeMap, time::Duration};
use url::{Url, form_urlencoded};

type Form = BTreeMap<String, String>;

fn form(text: &str) -> Result<Form> {
    let mut fields = Form::new();
    for (key, value) in form_urlencoded::parse(text.as_bytes()) {
        ensure!(
            fields
                .insert(key.into_owned(), value.into_owned())
                .is_none(),
            "duplicate Betsoft form field"
        );
    }
    Ok(fields)
}

fn field<'a>(fields: &'a Form, key: &str) -> Result<&'a str> {
    fields
        .get(key)
        .map(String::as_str)
        .with_context(|| format!("Betsoft field {key} missing"))
}

fn slot(id: &str) -> Option<(&'static str, &'static str)> {
    match id {
        "2" => Some(("/Lucky7.game", "1")),
        "266" => Some(("/AtTheMovies.game", "25")),
        "277" => Some(("/RooksRevenge.game", "25")),
        _ => None,
    }
}

pub fn supports(game: &Game, mode: &Mode) -> bool {
    slot(&game.id).is_some() && mode.kind == ModeKind::Normal && mode.key == "normal"
}

async fn send(
    ctx: &RunContext,
    endpoint: &str,
    sid: &str,
    sequence: usize,
    mut fields: Form,
    label: &str,
    financial: bool,
) -> Result<Form> {
    fields.extend([
        ("SID".into(), sid.into()),
        ("TIME".into(), now_ms().to_string()),
        ("CREQUESTID".into(), sequence.to_string()),
    ]);
    let body = form_urlencoded::Serializer::new(String::new())
        .extend_pairs(&fields)
        .finish();
    let reply = ctx
        .http(
            label,
            "POST",
            endpoint,
            BTreeMap::from([(
                "content-type".into(),
                "application/x-www-form-urlencoded".into(),
            )]),
            body,
            financial,
        )
        .await?;
    ensure!(
        reply.status == 200,
        "Betsoft HTTP {} at {label}",
        reply.status
    );
    let result = form(&reply.body)?;
    ensure!(
        field(&result, "RESULT")? == "OK",
        "Betsoft native command rejected at {label}"
    );
    Ok(result)
}

fn settlement(gid: &str, response: &Form) -> Result<Option<Decimal>> {
    match gid {
        "2" => {
            ensure!(
                (1..=3).all(|i| response.contains_key(&format!("SLOT{i}"))),
                "Lucky 7 terminal reels missing"
            );
            Ok(Some(decimal(field(response, "PAYOUT")?)?))
        }
        "266" => {
            ensure!(
                field(response, "STATE")? == "0",
                "At the Movies native continuation is unreviewed"
            );
            if let Some(win) = response.get("COMPLEXWIN") {
                return Ok(Some(decimal(win)?));
            }
            Ok(Some(
                field(response, "PAYOUT")?
                    .split('|')
                    .try_fold(Decimal::ZERO, |total, value| {
                        exact_add(total, decimal(value)?)
                    })?,
            ))
        }
        "277" => match field(response, "STATE")? {
            "0" => Ok(Some(decimal(field(response, "TOTALWIN")?)?)),
            "1" => Ok(None),
            _ => bail!("Rook's Revenge native continuation is unreviewed"),
        },
        _ => bail!("Betsoft game settlement unavailable"),
    }
}

pub async fn execute(ctx: &RunContext, game: &Game, mode: &Mode) -> Result<RoundOutcome> {
    ensure!(
        supports(game, mode),
        "Betsoft slot/mode binding unavailable"
    );
    let gid = &game.id;
    let (path, lines) = slot(gid).context("Betsoft slot profile unavailable")?;
    let entry = format!(
        "https://democasino.betsoftgaming.com/cwguestlogin.do?bankId=675&CDN=AUTO&gameId={gid}"
    );
    let mut response = ctx.get("public_guest_launch", &entry).await?;
    if matches!(response.status, 301 | 302 | 303 | 307 | 308) {
        let target = Url::parse(&entry)?.join(
            response
                .headers
                .get("location")
                .context("Betsoft redirect missing location")?,
        )?;
        ensure!(
            target.origin().ascii_serialization() == "https://democasino.betsoftgaming.com"
                && target.path() == "/free/base/template.jsp",
            "unexpected Betsoft demo redirect"
        );
        response = ctx.get("public_guest_template", target.as_str()).await?;
    }
    ensure!(
        response.status == 200,
        "unexpected Betsoft launcher response"
    );
    let launch_re = Regex::new(r#"return "(SERVLET_URL=[^"]+)""#)?;
    let captures = launch_re
        .captures(&response.body)
        .context("Betsoft legacy launcher fields missing")?;
    let launch = form(&captures[1])?;
    ensure!(
        field(&launch, "GAMEID")? == gid,
        "Betsoft launcher answered for a different game"
    );
    let endpoint = Url::parse(field(&launch, "SERVLET_URL")?)?;
    ensure!(
        endpoint.scheme() == "https"
            && endpoint.host_str() == Some("games-gp3demo.betsoftgaming.com")
            && endpoint.path() == path
            && endpoint.query().is_none(),
        "unexpected Betsoft demo endpoint"
    );
    let sid = field(&launch, "SID")?;
    ensure!(!sid.is_empty(), "Betsoft public guest SID missing");
    let init = send(
        ctx,
        endpoint.as_str(),
        sid,
        1,
        Form::from([("CMD".into(), "ENTER".into())]),
        "enter",
        false,
    )
    .await?;
    ensure!(
        field(&init, "game_mode")? == "free"
            && field(&init, "GID")? == gid
            && field(&init, "DEFAULTNUMLINES")? == lines
            && init
                .get("STATE")
                .is_none_or(|state| matches!(state.as_str(), "0" | "MAIN" | "MAIN_STATE")),
        "Betsoft failed to confirm reviewed idle FREE settings"
    );
    let currency = match init.get("CURRENCY_CODE") {
        Some(currency) => currency.as_str(),
        None if gid == "277" => field(&init, "CURRENCY_SYMBOL")?,
        None => bail!("Betsoft demo currency missing"),
    };
    ensure!(currency == "EUR", "Betsoft demo currency changed");
    let (index, coin) = field(&init, "IBETVALUES")?
        .split_whitespace()
        .map(decimal)
        .collect::<Result<Vec<_>>>()?
        .into_iter()
        .enumerate()
        .filter(|(_, coin)| *coin > Decimal::ZERO)
        .min_by_key(|&(_, coin)| coin)
        .context("Betsoft positive coin offer missing")?;
    let cost = exact_mul(coin, decimal(lines)?)?;
    let before = decimal(field(&init, "BALANCE")?)?;
    ensure!(before >= cost, "insufficient fictional demo funds");
    ctx.save_session(&json!({"provider":"betsoft","game":gid,"sid":sid,"endpoint":endpoint.as_str(),"playMode":"free","cost":cost}))?;
    let bet = if gid == "2" {
        format!("{index} {lines} 1")
    } else {
        format!("{index}|{lines}|1")
    };
    let mut command = Form::from([("CMD".into(), "PLACEBET".into()), ("BET".into(), bet)]);
    if gid != "2" {
        command.extend([
            ("AUTOPLAYSPIN".into(), "FALSE".into()),
            ("BUY".into(), "FALSE".into()),
        ]);
    }
    for step in 0..ctx.max_steps().min(500) {
        tokio::time::sleep(Duration::from_secs(1)).await;
        let label = if step == 0 { "place_bet" } else { "do_bonus" };
        let frame = send(ctx, endpoint.as_str(), sid, step + 2, command, label, true).await?;
        ensure!(
            field(&frame, "GID")? == gid,
            "Betsoft response game changed"
        );
        let after = decimal(field(&frame, "BALANCE")?)?;
        let settled = settlement(gid, &frame)?;
        let payout = exact_mul(
            coin,
            match settled {
                Some(win) => win,
                None => decimal(field(&frame, "TOTALWIN")?)?,
            },
        )?;
        ensure!(
            wallet_matches(before, after, cost, payout),
            "Betsoft demo balance did not reconcile"
        );
        if settled.is_none() {
            command = Form::from([("CMD".into(), "DOBONUS".into())]);
            continue;
        }
        return Ok(RoundOutcome {
            native_round_id: None,
            currency: currency.into(),
            currency_source: "native_response".into(),
            monetary_unit: "major".into(),
            balance_before: before.to_string(),
            balance_after: after.to_string(),
            cost: cost.to_string(),
            payout: payout.to_string(),
            native_closed: true,
            checks: BTreeMap::from([
                ("free_demo_settings".into(), true),
                ("native_offer".into(), true),
            ]),
            native_data: json!({"game":gid,"lines":lines,"steps":step+1}),
        });
    }
    bail!("Betsoft continuation limit reached")
}
