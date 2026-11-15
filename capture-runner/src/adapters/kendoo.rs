//! Native capture protocol derived from standalone info/kendoo/codigo and the evidence reference adapter.
use crate::{
    context::RunContext,
    model::{Completion, Game, Mode, ModeKind, decimal, now_ms, unknown_event},
};
use anyhow::{Context, Result, ensure};
use regex::Regex;
use rust_decimal::Decimal;
use serde::Deserialize;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use url::Url;

const ORIGIN: &str = "https://betman-demo.head.kendoo.pro";
pub(crate) const GAMES: [(&str, &str); 2] = [
    ("coin-dragon", "coin_dragon"),
    ("3-power-drums", "3_power_drums"),
];

fn game_code(slug: &str) -> Option<&'static str> {
    GAMES
        .iter()
        .find(|(id, _)| *id == slug)
        .map(|(_, code)| *code)
}

pub fn supports(game: &Game, mode: &Mode) -> bool {
    game_code(&game.id).is_some() && mode.kind == ModeKind::Normal && mode.key == "normal"
}

fn launch(html: &str, code: &str) -> Result<Url> {
    let fragments = Regex::new(r"self\.__next_f\.push\((\[.*?\])\)</script>")?;
    let mut state = String::new();
    for row in fragments.captures_iter(html) {
        let item: Value = serde_json::from_str(&row[1])?;
        if let Some(fragment) = item[1].as_str() {
            state.push_str(fragment);
        }
    }
    let links = Regex::new(r#""linkToDemoWebsite"\s*:\s*("(?:[^"\\]|\\.)*")"#)?;
    let mut target = None;
    for link in links.captures_iter(&state) {
        let url = Url::parse(&serde_json::from_str::<String>(&link[1])?)?;
        if url.origin().ascii_serialization() != ORIGIN
            || url.path() != "/betman-demo/static/game.html"
        {
            continue;
        }
        let matches = |name: &str, value: &str| {
            let mut values = url.query_pairs().filter(|(key, _)| key == name);
            values.next().is_some_and(|(_, v)| v == value) && values.next().is_none()
        };
        if !matches("game", code) || !matches("wl", "demo") {
            continue;
        }
        ensure!(
            target.as_ref().is_none_or(|previous| previous == &url),
            "ambiguous Kendoo demo link"
        );
        target = Some(url);
    }
    target.context("Kendoo demo link missing")
}

fn string<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    value[key]
        .as_str()
        .filter(|v| !v.is_empty())
        .with_context(|| format!("Kendoo {key} missing"))
}

fn amount(value: &Value) -> Result<Decimal> {
    if let Some(v) = value.as_str() {
        return decimal(v);
    }
    ensure!(value.is_number(), "Kendoo amount missing");
    decimal(&value.to_string())
}

struct Session<'a> {
    ctx: &'a RunContext,
    endpoint: Url,
    launch: Url,
    sequence: usize,
}

impl Session<'_> {
    async fn command(&mut self, name: &str, mut body: Value, financial: bool) -> Result<Value> {
        self.sequence += 1;
        let id = self.sequence.to_string();
        body["request_id"] = json!(id);
        body["command"] = json!(name);
        body["client_command_timestamp"] = json!(now_ms());
        let response = self
            .ctx
            .http(
                name,
                "POST",
                self.endpoint.as_str(),
                BTreeMap::from([
                    ("origin".into(), ORIGIN.into()),
                    ("referer".into(), self.launch.to_string()),
                    ("content-type".into(), "text/plain;charset=UTF-8".into()),
                    ("accept".into(), "*/*".into()),
                ]),
                serde_json::to_string(&body)?,
                financial,
            )
            .await?;
        ensure!(
            response.status == 200,
            "Kendoo {name} HTTP {}",
            response.status
        );
        let response: Value = serde_json::from_str(&response.body)?;
        ensure!(
            response["status"]["code"] == "OK"
                && response["request_id"] == id
                && response["command"] == name,
            "Kendoo {name} did not confirm the FUN command"
        );
        Ok(response)
    }
}

pub async fn execute(
    ctx: &RunContext,
    game: &Game,
    mode: &Mode,
    _settings: &serde_json::Value,
) -> Result<Completion> {
    ensure!(supports(game, mode), "Kendoo mode has no reviewed binding");
    let code = game_code(&game.id).context("Kendoo native game binding missing")?;
    let page = ctx
        .get(
            "official_game",
            &format!("https://kendoo.com/games/{}", game.id),
        )
        .await?;
    ensure!(
        page.status == 200,
        "Kendoo official game HTTP {}",
        page.status
    );
    let launch = launch(&page.body, code)?;
    let html = ctx.get("demo_launch", launch.as_str()).await?;
    ensure!(html.status == 200, "Kendoo launcher HTTP {}", html.status);
    let literal = Regex::new(r"\}\)\(window,\s*(\{)")?;
    let start = literal
        .captures(&html.body)
        .and_then(|v| v.get(1))
        .context("Kendoo bootstrap missing")?
        .start();
    let binding = Value::deserialize(&mut serde_json::Deserializer::from_str(&html.body[start..]))?;
    let options = &binding["options"];
    ensure!(
        options["wl"] == "demo" && options["protocol"] == "goreel",
        "unexpected Kendoo demo protocol"
    );
    let queue = string(options, "queue")?;
    ensure!(
        queue
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_'),
        "invalid Kendoo queue"
    );
    let endpoint =
        launch.join(&string(&binding["desktop"], "server_url")?.replace("{QUEUE}", queue))?;
    ensure!(
        endpoint.origin().ascii_serialization() == ORIGIN
            && endpoint.path() == format!("/betman-demo/gs/{code}/desktop/{queue}/demo/")
            && endpoint.query().is_none(),
        "unexpected Kendoo endpoint"
    );
    let mut wire = Session {
        ctx,
        endpoint,
        launch,
        sequence: 0,
    };
    let login = wire
        .command(
            "login",
            json!({"token":string(options,"token")?,"language":"en"}),
            false,
        )
        .await?;
    let session = string(&login, "session_id")?;
    let start = wire
        .command(
            "start",
            json!({"session_id":session,"huid":string(&login["user"],"huid")?,"mode":"auto"}),
            false,
        )
        .await?;
    ensure!(
        start["session_id"] == session && start["context"]["round_finished"] == true,
        "Kendoo session is not idle"
    );
    let settings = &start["settings"];
    let bets = settings["bets"]
        .as_array()
        .context("Kendoo stakes missing")?;
    let mut minimum = None;
    for bet in bets {
        let n = amount(bet)?;
        ensure!(n > Decimal::ZERO, "invalid Kendoo stake");
        if minimum.as_ref().is_none_or(|(old, _)| n < *old) {
            minimum = Some((n, bet));
        }
    }
    let (_minimum, bet) = minimum.context("empty Kendoo stake offer")?;
    let lines = settings["lines"]
        .as_array()
        .and_then(|v| v.first())
        .and_then(Value::as_u64)
        .filter(|n| *n > 0)
        .context("Kendoo lines missing")?;
    ctx.save_session(&json!({"game":code,"session":session}))?;
    let mut params = json!({"bet_per_line":bet,"lines":lines});
    let mut current = start;
    let mut action = "spin".to_owned();

    for index in 0..ctx.max_steps() {
        ensure!(
            current["context"]["actions"]
                .as_array()
                .is_some_and(|v| v.iter().any(|p| p == &action)),
            "Kendoo action not offered"
        );
        current = wire.command("play",json!({"session_id":session,"action":{"name":action,"params":params},
            "set_denominator":1,"quick_spin":2,"sound":false,"autogame":false,"mobile":"0","portrait":false,"fullscreen":false}),true).await?;
        ensure!(current["session_id"] == session, "Kendoo session changed");
        let context = &current["context"];
        if context["round_finished"] == true {
            return Ok(Completion {
                native_round_id: None,
                details: json!({"game":code,"steps":index+1}),
            });
        }
        action = next_action(context)?.to_owned();
        params = json!({});
    }
    anyhow::bail!("Kendoo continuation limit reached")
}

fn next_action(context: &Value) -> Result<&str> {
    let actions = context["actions"]
        .as_array()
        .ok_or_else(|| unknown_event("Kendoo continuation missing"))?;
    if actions.len() != 1 {
        return Err(unknown_event(format!(
            "Kendoo ambiguous or unknown action menu: {actions:?}"
        )));
    }
    match actions[0].as_str() {
        Some(action @ ("bonus_init" | "respin" | "bonus_spins_stop")) => Ok(action),
        _ => Err(unknown_event(format!(
            "Kendoo unsupported next action: {}",
            actions[0]
        ))),
    }
}

#[cfg(test)]
mod capture_tests {
    use super::*;

    #[test]
    fn free_native_action_needs_no_wallet() {
        assert_eq!(
            next_action(&json!({"round_finished":false,"actions":["respin"]})).unwrap(),
            "respin"
        );
    }
    #[test]
    fn novel_or_mixed_menu_alerts() {
        for actions in [json!(["new"]), json!(["respin", "new"]), json!([])] {
            assert!(
                next_action(&json!({"actions":actions}))
                    .unwrap_err()
                    .downcast_ref::<crate::model::UnknownEvent>()
                    .is_some()
            );
        }
    }
}
