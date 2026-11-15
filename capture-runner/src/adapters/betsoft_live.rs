//! Native capture protocol derived from standalone info/betsoft/codigo and the evidence reference adapter.
//! Betsoft public FREE sessions for reviewed legacy slots.
use crate::{
    context::RunContext,
    model::{Completion, Game, Mode, ModeKind, decimal, now_ms, unknown_event},
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

fn settlement(gid: &str, response: &Form) -> Result<Option<()>> {
    match gid {
        "2" if (1..=3).all(|i| response.contains_key(&format!("SLOT{i}"))) => Ok(Some(())),
        "266" | "277" => match field(response, "STATE")? {
            "0" => Ok(Some(())),
            "1" if gid == "277" => Ok(None),
            state => Err(unknown_event(format!("Betsoft {gid} next state {state}"))),
        },
        _ => Err(unknown_event("Betsoft terminal reels/state unavailable")),
    }
}

pub async fn execute(
    ctx: &RunContext,
    game: &Game,
    mode: &Mode,
    _settings: &serde_json::Value,
) -> Result<Completion> {
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
    let (index, _coin) = field(&init, "IBETVALUES")?
        .split_whitespace()
        .map(decimal)
        .collect::<Result<Vec<_>>>()?
        .into_iter()
        .enumerate()
        .filter(|(_, coin)| *coin > Decimal::ZERO)
        .min_by_key(|&(_, coin)| coin)
        .context("Betsoft positive coin offer missing")?;
    ctx.save_session(&json!({"provider":"betsoft","game":gid,"sid":sid,"endpoint":endpoint.as_str(),"playMode":"free"}))?;
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
        let settled = settlement(gid, &frame)?;
        if settled.is_none() {
            command = Form::from([("CMD".into(), "DOBONUS".into())]);
            continue;
        }
        return Ok(Completion {
            native_round_id: None,
            details: json!({"game":gid,"lines":lines,"steps":step+1}),
        });
    }
    bail!("Betsoft continuation limit reached")
}

#[cfg(test)]
mod capture_tests {
    use super::*;

    #[test]
    fn terminal_native_reels_and_states_ignore_money() {
        assert!(
            settlement("2", &form("SLOT1=1&SLOT2=2&SLOT3=3").unwrap())
                .unwrap()
                .is_some()
        );
        assert!(
            settlement("266", &form("STATE=0").unwrap())
                .unwrap()
                .is_some()
        );
        assert!(
            settlement("277", &form("STATE=1").unwrap())
                .unwrap()
                .is_none()
        );
    }
    #[test]
    fn unrecognized_state_is_typed() {
        assert!(
            settlement("277", &form("STATE=99").unwrap())
                .unwrap_err()
                .downcast_ref::<crate::model::UnknownEvent>()
                .is_some()
        );
    }
}
