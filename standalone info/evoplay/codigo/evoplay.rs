use crate::{
    context::{RunContext, validate_target},
    model::{Game, Mode, RoundOutcome, decimal, exact_mul, exact_sub, wallet_matches},
};
use anyhow::{Context, Result, bail, ensure};
use rust_decimal::Decimal;
use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::OnceLock, time::Duration};
use url::Url;
use uuid::Uuid;

fn binding(game: &Game, mode: &Mode) -> Option<&'static Value> {
    static MAP: OnceLock<Value> = OnceLock::new();
    let map = MAP.get_or_init(|| {
        serde_json::from_str(include_str!("../../bindings/evoplay.json"))
            .expect("embedded Evoplay bindings")
    });
    let row = map.get(&game.id)?.get(&mode.key)?;
    (row["kind"] == mode.kind.as_str()).then_some(row)
}

pub fn supports(game: &Game, mode: &Mode) -> bool {
    binding(game, mode).is_some()
}

fn amount(value: &Value) -> Result<Decimal> {
    match value {
        Value::String(text) => decimal(text),
        Value::Number(number) => decimal(&number.to_string()),
        _ => bail!("Evoplay native money field missing"),
    }
}

async fn launch(ctx: &RunContext, game: &str) -> Result<(Url, Value)> {
    ensure!(
        !game.is_empty()
            && game
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-'),
        "invalid slot ID"
    );
    let mut url = Url::parse(&format!(
        "https://demo.evoplay.games/demo/fullstate/html5/evoplay/{game}"
    ))?;
    for _ in 0..6 {
        let reply = ctx.get("public_demo_launch", url.as_str()).await?;
        if matches!(reply.status, 301 | 302 | 303 | 307 | 308) {
            url = url.join(
                reply
                    .headers
                    .get("location")
                    .context("Evoplay redirect missing location")?,
            )?;
            continue;
        }
        ensure!(reply.status == 200, "Evoplay demo launch unsuccessful");
        let re = regex::Regex::new(r"\bjsvars\s*=\s*")?;
        if let Some(marker) = re.find(&reply.body) {
            let mut values = serde_json::Deserializer::from_str(&reply.body[marker.end()..])
                .into_iter::<Value>();
            return Ok((
                url,
                values
                    .next()
                    .context("Evoplay launch configuration missing")??,
            ));
        }
        let query: BTreeMap<_, _> = url.query_pairs().into_owned().collect();
        let field = |key| {
            query
                .get(key)
                .map(String::as_str)
                .filter(|v| !v.is_empty())
                .context("Evoplay query bootstrap incomplete")
        };
        let mut config_url = Url::parse(&format!(
            "{}/config-service/game-client/v2/gameConfig",
            field("config_base_url")?.trim_end_matches('/')
        ))?;
        config_url
            .query_pairs_mut()
            .append_pair("operator_code", field("operator_code")?)
            .append_pair("game_code", field("game_code")?);
        let config_reply = ctx.get("client_config", config_url.as_str()).await?;
        ensure!(
            config_reply.status == 200,
            "Evoplay client configuration unavailable"
        );
        let cfg: Value = serde_json::from_str(&config_reply.body)?;
        let config = json!({"game_name":cfg["game_name"],"customVars":field("session_token")?,
            "action_url":cfg["integration"]["game_backend_url"]});
        return Ok((url, config));
    }
    bail!("Evoplay demo redirect limit")
}

struct Session<'a> {
    ctx: &'a RunContext,
    endpoint: Url,
    headers: BTreeMap<String, String>,
    game: &'a str,
    custom: &'a Value,
}

impl Session<'_> {
    async fn send(&self, action: &str, mut request: Value, financial: bool) -> Result<Value> {
        request["game"] = json!(self.game);
        request["customVars"] = self.custom.clone();
        let boundary = Uuid::new_v4().simple().to_string();
        let mut headers = self.headers.clone();
        headers.insert(
            "content-type".into(),
            format!("multipart/form-data; boundary={boundary}"),
        );
        let body = format!(
            "--{boundary}\r\nContent-Disposition: form-data; name=\"data\"\r\n\r\n{request}\r\n--{boundary}--\r\n"
        );
        let reply = self
            .ctx
            .http(
                action,
                "POST",
                self.endpoint.as_str(),
                headers,
                body,
                financial,
            )
            .await?;
        ensure!(
            reply.status == 200,
            "Evoplay HTTP {} at {action}",
            reply.status
        );
        let value: Value = serde_json::from_str(&reply.body)?;
        ensure!(
            value["error"].is_null() || value["error"] == false,
            "Evoplay native command rejected at {action}"
        );
        Ok(value)
    }
}

pub async fn execute(ctx: &RunContext, game: &Game, mode: &Mode) -> Result<RoundOutcome> {
    let spec = binding(game, mode).context("Evoplay mode binding unavailable")?;
    let (launch, config) = launch(ctx, &game.id).await?;
    let identity = config["game_name"]
        .as_str()
        .context("Evoplay game identity missing")?;
    ensure!(
        identity
            .replace('\\', "/")
            .eq_ignore_ascii_case(&format!("fullstate/html5/evoplay/{}", game.id)),
        "Evoplay game identity changed"
    );
    let action_url = config["action_url"]
        .as_str()
        .context("Evoplay action URL missing")?;
    ensure!(
        action_url.starts_with('/') && !action_url.starts_with("//") && !action_url.contains('\\'),
        "invalid Evoplay action URL"
    );
    let endpoint = validate_target("evoplay", launch.join(action_url)?.as_str())?;
    ensure!(
        endpoint.origin() == launch.origin() && !config["customVars"].is_null(),
        "Evoplay demo session binding invalid"
    );
    let session = Session {
        ctx,
        endpoint,
        headers: BTreeMap::from([
            ("origin".into(), launch.origin().ascii_serialization()),
            ("referer".into(), launch.to_string()),
        ]),
        game: identity,
        custom: &config["customVars"],
    };
    let mut reply = session
        .send(
            "init",
            json!({"action":"init","request_id":1,"game_client_version":"local","time_offset":180}),
            false,
        )
        .await?;
    let init = &reply["init"];
    ensure!(
        init["currency"] == "DEMO"
            && reply["available_actions"] == json!(["spin"])
            && (init["restorestate"].is_null() || init["restorestate"] == false),
        "Evoplay did not confirm an idle DEMO wallet"
    );
    let denom = reply
        .get("denomination")
        .map(|v| {
            v.as_str()
                .map(str::to_owned)
                .unwrap_or_else(|| v.to_string())
        })
        .unwrap_or_else(|| "1".into());
    let mut bets = Vec::new();
    for raw in init["ranges"]["bet"][&denom]
        .as_array()
        .context("Evoplay native stake menu missing")?
    {
        let value = amount(raw)?;
        if value > Decimal::ZERO {
            bets.push((value, raw.clone()));
        }
    }
    let (bet, native_bet) = bets
        .into_iter()
        .min_by_key(|(value, _)| *value)
        .context("no positive stake offered")?;
    let lines = init["lines"].clone();
    ensure!(!lines.is_null(), "Evoplay native lines missing");
    let mut selector = None;
    let mut multiplier = Decimal::ONE;
    let mut option_free_type = None;
    for (spec_key, directory, control) in [
        ("buy_id", "store", "bonus_buy_id"),
        ("modifier", "double_chance_freespins", "double_chance"),
    ] {
        if let Some(id) = spec.get(spec_key) {
            let key = id
                .as_str()
                .map(str::to_owned)
                .unwrap_or_else(|| id.to_string());
            let offered = &init["directory"][directory][key];
            ensure!(
                offered["id"] == *id
                    && amount(&offered["price"])? == amount(&spec["price"])?
                    && spec
                        .get("native_option")
                        .is_none_or(|expected| expected == offered),
                "Evoplay offer changed"
            );
            multiplier = amount(&offered["price"])?;
            selector = Some((control, id.clone()));
            option_free_type = offered
                .pointer("/settings/freespins_type")
                .and_then(Value::as_str)
                .map(str::to_owned);
        }
    }
    let cost = exact_mul(bet, multiplier)?;
    let before = amount(&reply["balance"]["after"])?;
    ensure!(
        cost > Decimal::ZERO && before >= cost,
        "insufficient fictional demo funds or invalid price"
    );
    let mut rid = init["next_request_id"]
        .as_u64()
        .context("Evoplay next request ID missing")?;
    ctx.save_session(&json!({"provider":"evoplay","game":game.id,"mode":mode.key,"endpoint":session.endpoint.as_str(),"configuration":config,"cost":cost}))?;
    let mut action = "spin".to_owned();
    let mut macro_win = None;
    let mut free_type: Option<String> = None;
    let mut choice_sent = spec.get("freegame_type").is_none();
    for step in 0..ctx.max_steps().min(2000) {
        tokio::time::sleep(Duration::from_secs(15)).await;
        let mut request = json!({"action":action,"bet":native_bet,"lines":lines,"request_id":rid,"time_offset":180});
        rid = rid
            .checked_add(1)
            .context("Evoplay request sequence overflow")?;
        if game.id == "joltcircuit" {
            request["lines_count"] = lines.clone();
        }
        if let Some((key, id)) = &selector {
            if step == 0 || *key == "double_chance" {
                request[*key] = id.clone();
            }
        }
        if matches!(
            action.as_str(),
            "initfreespin" | "freespin" | "freedrop" | "freerespin" | "initspin"
        ) {
            let explicit = spec["freegame_type"]
                .as_str()
                .filter(|_| matches!(action.as_str(), "initfreespin" | "freespin" | "initspin"));
            let selected = explicit
                .or_else(|| {
                    option_free_type
                        .as_deref()
                        .filter(|_| action == "initfreespin")
                })
                .or(free_type.as_deref());
            if let Some(selected) = selected {
                request["freegame_type"] = json!(selected);
            }
            choice_sent |= explicit.is_some();
        }
        reply = session.send(&action, request, true).await?;
        if step == 0 {
            ensure!(
                exact_sub(before, amount(&reply["balance"]["before"])?)? == cost,
                "Evoplay native debit differs from the offered price"
            );
        }
        if let Some(win) = reply
            .pointer("/macro_round/wins/total")
            .filter(|v| !v.is_null())
        {
            macro_win = Some(amount(win)?);
        }
        let actions = reply["available_actions"]
            .as_array()
            .context("Evoplay continuation offer missing")?;
        if actions.contains(&json!("spin")) {
            ensure!(choice_sent, "Evoplay selected bonus choice was not reached");
            let win = match macro_win {
                Some(win) => win,
                None if step == 0 => amount(&reply["spin"]["wins"]["total"])?,
                None => bail!("Evoplay cumulative prize missing at closure"),
            };
            let after = amount(&reply["balance"]["after"])?;
            ensure!(
                wallet_matches(before, after, cost, win),
                "Evoplay demo wallet did not reconcile"
            );
            return Ok(RoundOutcome {
                native_round_id: None,
                currency: "DEMO".into(),
                monetary_unit: "native".into(),
                currency_source: "native_response".into(),
                balance_before: before.to_string(),
                balance_after: after.to_string(),
                cost: cost.to_string(),
                payout: win.to_string(),
                native_closed: true,
                checks: BTreeMap::from([
                    ("idle_demo_session".into(), true),
                    ("native_debit".into(), true),
                ]),
                native_data: json!({"steps":step+1,"offer":selector}),
            });
        }
        ensure!(
            actions.len() == 1,
            "Evoplay continuation requires a separate native choice"
        );
        action = actions[0]
            .as_str()
            .filter(|s| {
                matches!(
                    *s,
                    "initfreespin"
                        | "freespin"
                        | "initspin"
                        | "drop"
                        | "freedrop"
                        | "respin"
                        | "freerespin"
                )
            })
            .context("Evoplay continuation action unavailable")?
            .to_owned();
        if let Some(received) = reply
            .as_object()
            .into_iter()
            .flat_map(|obj| obj.values())
            .find_map(|v| v.pointer("/freespins/type").and_then(Value::as_str))
        {
            free_type = Some(received.to_owned());
        }
    }
    bail!("Evoplay round exceeded continuation limit")
}
