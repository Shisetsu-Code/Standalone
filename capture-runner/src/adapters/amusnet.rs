//! Native capture connector derived from standalone info/amusnet/codigo/amusnet.rs.
//! Published source SHA-256: 31374690d1ce02c04a8b5984329835e0e546e01d3212f8b3af327972e2aec524
//! Reference transport: game-runner/src/adapters/amusnet.rs; no runtime dependency.
use crate::{
    context::{NativeSocket, RunContext, SocketPayload},
    model::{Completion, Game, Mode, decimal, exact_mul, now_ms},
};
use anyhow::{Context, Result, bail, ensure};
use rust_decimal::Decimal;
use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::OnceLock};
use url::Url;
use uuid::Uuid;

const PORTAL: &str = "https://amusnet.com";
const HOST: &str = "free-pod.games.amusnet.io";

fn binding(game: &Game, mode: &Mode) -> Option<(bool, &'static Value)> {
    static MAP: OnceLock<Value> = OnceLock::new();
    let map = MAP.get_or_init(|| {
        serde_json::from_str(include_str!("../../bindings/amusnet.json"))
            .expect("embedded Amusnet bindings")
    });
    let row = map.get(&game.id)?;
    let selected = row["modes"].get(&mode.key)?;
    (selected["kind"] == mode.kind.as_str())
        .then_some((row["remote"].as_bool()?, &selected["option"]))
}

pub fn supports(game: &Game, mode: &Mode) -> bool {
    binding(game, mode).is_some()
}

fn amount(value: &Value) -> Result<Decimal> {
    match value {
        Value::Number(value) => decimal(&value.to_string()),
        Value::String(value) => decimal(value),
        _ => bail!("Amusnet native amount missing"),
    }
}

fn lowest(bets: &Value) -> Result<Decimal> {
    bets.as_array()
        .context("Amusnet native bet menu missing")?
        .iter()
        .map(amount)
        .collect::<Result<Vec<_>>>()?
        .into_iter()
        .filter(|value| *value > Decimal::ZERO)
        .min()
        .context("Amusnet positive bet option missing")
}

fn quote(settings: &Value, option: &Value, remote: bool) -> Result<Decimal> {
    let group = if let Some(groups) = settings["betOptions"]
        .as_array()
        .filter(|array| !array.is_empty())
    {
        let offers = groups
            .iter()
            .map(|group| Ok((lowest(&group["betAmounts"])?, group)))
            .collect::<Result<Vec<_>>>()?;
        offers.into_iter().min_by_key(|(bet, _)| *bet)
    } else {
        None
    };
    let values = settings
        .get("bets")
        .or_else(|| settings.get("betAmounts"))
        .filter(|value| value.as_array().is_some_and(|array| !array.is_empty()));
    let base = match values {
        Some(values) => lowest(values)?,
        None => group.context("Amusnet bet amounts missing")?.0,
    };
    let name = option["name"]
        .as_str()
        .context("Amusnet option name missing")?;
    let offered_multiplier = if name == "NONE" {
        let expected = group
            .map(|(_, group)| &group["betGroupId"])
            .unwrap_or(&Value::Null);
        ensure!(
            expected == &option["bet_group"],
            "Amusnet native bet group changed"
        );
        Decimal::ONE
    } else if remote {
        ensure!(option["id"] == name, "Amusnet remote selector changed");
        amount(&settings["buyFeatures"][name]["multiplier"])?
    } else {
        let id = &settings["featureIds"][name];
        ensure!(
            id == &option["id"] && id.is_number(),
            "Amusnet native selector changed"
        );
        amount(&settings["featureMultipliers"][id.to_string()])?
    };
    ensure!(
        offered_multiplier == amount(&option["multiplier"])? && offered_multiplier > Decimal::ZERO,
        "Amusnet mode price changed"
    );
    Ok(base)
}

struct Session<'a> {
    ctx: &'a RunContext,
    socket: NativeSocket,
    key: &'a str,
    game: &'a str,
    number: Value,
    remote: bool,
}

impl Session<'_> {
    async fn call(
        &mut self,
        command: &str,
        mut request: Value,
        round_action: bool,
    ) -> Result<Value> {
        let id = format!("qa-{}", Uuid::new_v4());
        request["command"] = json!(command);
        request["gin"] = json!(self.game);
        request["sessionKey"] = json!(self.key);
        request["messageId"] = json!(id);
        self.ctx
            .ws_codec(
                &mut self.socket,
                command,
                SocketPayload::Text(request.to_string()),
                round_action,
                None,
                |frame| {
                    let SocketPayload::Text(text) = frame else {
                        return Err(crate::model::unknown_event(
                            "Amusnet unexpected binary frame".to_string(),
                        ));
                    };
                    if text == "pong" {
                        return Ok(Vec::new());
                    }
                    let answer: Value = serde_json::from_str(text)?;
                    Ok(if answer["messageId"] == id {
                        vec![answer]
                    } else {
                        Vec::new()
                    })
                },
            )
            .await
    }

    async fn action(&mut self, command: &str, mut request: Value) -> Result<Value> {
        let reply = if self.remote {
            request["gameCommand"] = json!(command.to_ascii_uppercase());
            request["gameNumber"] = self.number.clone();
            let outer = self
                .call("forward", json!({"payload":request}), true)
                .await?;
            outer.get("payload").cloned().unwrap_or(outer)
        } else {
            request["gameCommand"] = json!(command);
            self.call("bet", json!({"gameNumber":self.number,"bet":request}), true)
                .await?
        };
        ensure!(
            reply
                .get("msg")
                .or_else(|| reply.get("status"))
                .is_none_or(|value| value == "success"),
            "Amusnet native command rejected"
        );
        Ok(reply)
    }
}

fn bet_request(
    game: &str,
    option: &Value,
    base: Decimal,
    remote: bool,
    free: bool,
) -> Result<Value> {
    let multiplier = if free {
        Decimal::ONE
    } else {
        amount(&option["multiplier"])?
    };
    let stake = exact_mul(base, multiplier)?;
    ensure!(
        stake.fract().is_zero(),
        "Amusnet bet has a fractional native unit"
    );
    let stake = stake
        .normalize()
        .to_string()
        .parse::<u64>()
        .context("Amusnet bet out of range")?;
    let mut request = json!({"bet":stake,"betMultiplier":serde_json::from_str::<Value>(&multiplier.to_string())?,
        "bonus":free,"autoplay":false});
    if remote {
        request["buyFeature"] = if free {
            json!("NONE")
        } else {
            option["name"].clone()
        };
    } else {
        request["featureId"] = if free { json!(0) } else { option["id"].clone() };
    }
    if let Some(group) = option.get("bet_group") {
        request["betGroupId"] = group.clone();
    }
    if matches!(game, "414" | "450") {
        request["gameMode"] = json!(2);
    }
    Ok(request)
}

pub async fn execute(
    ctx: &RunContext,
    game: &Game,
    mode: &Mode,
    _settings: &Value,
) -> Result<Completion> {
    let (remote, option) = binding(game, mode).context("Amusnet mode binding missing")?;
    let headers = BTreeMap::from([
        ("origin".into(), PORTAL.into()),
        ("referer".into(), format!("{PORTAL}/")),
        ("user-agent".into(), "Mozilla/5.0".into()),
    ]);
    let lobby = ctx
        .json(
            "demo_lobby",
            &format!("{PORTAL}/api/lobby"),
            &json!({"timestamp":now_ms()}),
            headers.clone(),
            false,
        )
        .await?;
    let token = lobby["token"]
        .as_str()
        .filter(|value| !value.is_empty())
        .context("Amusnet fresh guest token missing")?;
    let mut launch = Url::parse(&format!("https://{HOST}/demo/v1/launch"))?;
    launch.query_pairs_mut().extend_pairs([
        ("gameId", game.id.as_str()),
        ("language", "en"),
        ("client", "desktop"),
        ("token", token),
    ]);
    let reply = ctx
        .http(
            "demo_launch",
            "GET",
            launch.as_str(),
            headers,
            String::new(),
            false,
        )
        .await?;
    ensure!(
        reply.status == 200,
        "Amusnet launcher HTTP {}",
        reply.status
    );
    let marker = regex::Regex::new(r"\bvar\s+connectionParams\s*=\s*")?
        .find(&reply.body)
        .context("Amusnet connection parameters missing")?;
    let config = serde_json::Deserializer::from_str(&reply.body[marker.end()..])
        .into_iter::<Value>()
        .next()
        .context("Amusnet launcher configuration missing")??;
    let demo_host = config["tcpHost"]
        .as_str()
        .context("Amusnet demo socket host missing")?;
    ensure!(
        config["portalCode"] == "Corporate_All_Portal_FUN"
            && matches!(demo_host, HOST | "free-pod01.games.amusnet.io")
            && config["remote"].as_bool().unwrap_or(false) == remote,
        "Amusnet public FUN launcher contract changed"
    );
    let key = config["sessionKey"]
        .as_str()
        .filter(|value| !value.is_empty())
        .context("Amusnet session key missing")?;
    let mut ws = Url::parse(&format!("wss://{demo_host}/"))?;
    ws.query_pairs_mut().append_pair("sessionKey", key);
    let socket = ctx
        .websocket(
            ws.as_str(),
            "https://prod.cdn.amusnet.io",
            None,
            BTreeMap::new(),
        )
        .await?;
    let mut session = Session {
        ctx,
        socket,
        key,
        game: &game.id,
        number: json!("-1"),
        remote,
    };
    let init = session
        .call("init_game", json!({"platformType":"desktop"}), false)
        .await?;
    ensure!(
        init["status"] == "success",
        "Amusnet did not confirm native initialization"
    );
    let state = &init["states"]["gameState"];
    let current = state
        .pointer("/complex/currentState/state")
        .unwrap_or(&state["state"]);
    ensure!(
        current.as_str().is_some_and(|state| matches!(
            state.to_ascii_lowercase().as_str(),
            "idle" | "finished"
        )),
        "Amusnet demo is not idle"
    );
    if !state["gameNumber"].is_null() {
        session.number = state["gameNumber"].clone();
    }
    let settings = &init["settings"]["gameSettings"];
    let base = quote(settings.get("complex").unwrap_or(settings), option, remote)?;
    let mut request = bet_request(&game.id, option, base, remote, false)?;
    let cost = amount(&request["bet"])?;
    ctx.save_session(&json!({"provider":"amusnet","game":game.id,"sessionKey":key,"currency":"FUN","mode":mode.key,"cost":cost}))?;
    let mut command = "bet";
    let mut root = None;
    for step in 0..ctx.max_steps().min(600) {
        let reply = session.action(command, request).await?;
        if let Some(number) = reply
            .get("gameNumber")
            .filter(|value| value.is_string() || value.is_number())
        {
            ensure!(
                root.as_ref().is_none_or(|prior| prior == number),
                "Amusnet native round identity changed"
            );
            root.get_or_insert_with(|| number.clone());
            session.number = number.clone();
        }
        let state = reply["state"]
            .as_str()
            .ok_or_else(|| crate::model::unknown_event("Amusnet native round state missing"))?
            .to_ascii_lowercase();
        match known_state(&state)? {
            "idle" | "finished" => {
                return Ok(Completion {
                    native_round_id: root.map(|value| {
                        value
                            .as_str()
                            .map(str::to_owned)
                            .unwrap_or_else(|| value.to_string())
                    }),
                    details: json!({"steps":step+1,"option":option["name"]}),
                });
            }
            "freespin" => {
                command = if remote { "freespin" } else { "bet" };
                request = bet_request(&game.id, option, base, remote, true)?;
            }
            "gamble" => {
                command = "collect";
                request = json!({});
            }
            "hold_and_spin" if remote => {
                command = "HOLD_AND_SPIN";
                request = json!({"bet":0,"betMultiplier":1,"bonus":false,"buyFeature":"NONE","autoplay":false});
            }
            _ => {
                return Err(crate::model::unknown_event(
                    "Amusnet continuation requires a game-specific control".to_string(),
                ));
            }
        }
    }
    Err(crate::model::unknown_event(
        "Amusnet continuation limit reached",
    ))
}

fn known_state(state: &str) -> Result<&str> {
    match state {
        "idle" | "finished" | "freespin" | "gamble" | "hold_and_spin" => Ok(state),
        _ => Err(crate::model::unknown_event(format!(
            "Amusnet unknown state {state}"
        ))),
    }
}

#[cfg(test)]
mod capture_tests {
    use super::*;

    #[test]
    fn native_terminal_state_needs_no_wallet_and_unknown_is_typed() {
        let reply = json!({"state":"finished","gameNumber":"r1"});
        assert_eq!(
            known_state(reply["state"].as_str().unwrap()).unwrap(),
            "finished"
        );
        assert!(
            known_state("new_bonus")
                .unwrap_err()
                .downcast_ref::<crate::model::UnknownEvent>()
                .is_some()
        );
    }
}
