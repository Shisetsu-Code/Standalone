use crate::{
    context::RunContext,
    model::{Game, Mode, ModeKind, RoundOutcome, decimal, exact_add, exact_mul},
};
use anyhow::{Context, Result, bail, ensure};
use regex::Regex;
use rust_decimal::Decimal;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use url::Url;

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
fn parameters(table: &Value, history: &Value) -> Result<Value> {
    ensure!(
        history["status"] == "FINISHED",
        "fresh session has unfinished round"
    );
    let mut p = history["betting_param"].clone();
    let map = p.as_object_mut().context("missing betting parameters")?;
    for (field, set) in [
        ("bet_per_line", "bets_set"),
        ("num_of_lines", "lines_set"),
        ("denom", "denoms_set"),
    ] {
        let target = amount(map.get(field).context("missing bet parameter")?)?;
        let offered = table[set].as_array().context("missing bet offer")?;
        ensure!(
            offered.iter().any(|v| amount(v).is_ok_and(|n| n == target)),
            "unpublished initial bet: {field}"
        );
    }
    map.insert("extra_bet".into(), json!(0));
    map.insert("bonusId".into(), json!(""));
    map.remove("buyInId");
    Ok(p)
}
fn next_step(history: &Value, config: &Value) -> Result<Option<(&'static str, Value)>> {
    if history["status"] == "FINISHED" {
        return Ok(None);
    }
    ensure!(
        history["status"].as_str().is_some_and(|s| !s.is_empty()),
        "missing game status"
    );
    let features = history["features"].as_array().context("missing features")?;
    if let Some(f) = features.iter().rev().find(|f| f["status"] == "IN_PROGRESS") {
        let state = &f["current_state"];
        let fid = f["feature_id"].as_str().context("missing feature id")?;
        if state["is_final"] == true
            || state["isFinal"] == true
            || ((fid == "PICKME" || fid == "WHEEL_WIN") && state["tries"] == 0)
        {
            return Ok(Some(("END_FEATURE", Value::Null)));
        }
        let action = match fid {
            "SLOT" => {
                if !state["curr_reaction"].is_null() && state["curr_reaction"] != false {
                    "logic.api.gamelogic.slot.Drop_Action"
                } else {
                    "logic.api.gamelogic.slot.Slot_Action"
                }
            }
            "FREE_GAME" => {
                let selecting = state["played_free_games"] == 0
                    || (state["not_played_free_games"] == 0
                        && state["number_of_lucky_free_games_retriggers"]
                            .as_i64()
                            .unwrap_or(0)
                            > 0);
                let configs = config["game"]["features"]
                    .as_array()
                    .context("missing published feature configuration")?;
                let selection = configs.iter().find(|f| {
                    f["featureID"] == "FREE_GAME"
                        && f["featureClassName"].as_str().is_some_and(|name| {
                            name.contains("SelectionFreegamesFeature")
                                || name == "ChunjieFreegamesFeature"
                        })
                });
                if selecting && let Some(selection) = selection {
                    let state_choices = state["states"]
                        .as_array()
                        .and_then(|a| a.iter().find_map(|s| s["choice"].as_array()))
                        .filter(|a| !a.is_empty());
                    let multipliers = selection["params"]["multipliers"]
                        .as_array()
                        .filter(|a| !a.is_empty());
                    let selected = if state_choices.is_some() || multipliers.is_some() {
                        0
                    } else {
                        let inputs = config["input"]
                            .as_array()
                            .context("missing published free-game inputs")?;
                        inputs
                            .iter()
                            .flat_map(|c| c["actions"]["onClick"].as_array().into_iter().flatten())
                            .filter(|a| a["event"]["className"] == "FREEGAMES_SELECT")
                            .filter_map(|a| a["event"]["arg"].as_u64())
                            .min()
                            .context("missing published free-game selection")?
                    };
                    return Ok(Some((
                        "STEP_FEATURE",
                        json!({"@type":"logic.api.gamelogic.freegames.Free_Games_Choose_Type_Action","player_choice":selected}),
                    )));
                }
                if state["not_played_free_games"] == 0 && state["is_drop"] != true {
                    return Ok(Some(("END_FEATURE", Value::Null)));
                }
                if state["is_drop"] == true {
                    "logic.api.gamelogic.freegames.Free_Games_Drop_Action"
                } else {
                    "logic.api.gamelogic.freegames.Free_Games_Action"
                }
            }
            "RABBITS_WIN" => {
                if state["tries"].as_i64().is_some_and(|v| v <= 0) {
                    return Ok(Some(("END_FEATURE", Value::Null)));
                }
                "logic.api.gamelogic.rabbits.Rabbits_Action"
            }
            "WHEEL_WIN" => "logic.api.gamelogic.wheel.Wheel_Action",
            "COCKTAIL_WIN" => {
                if state["tries"].as_i64().context("missing tries")? <= 0 {
                    return Ok(Some(("END_FEATURE", Value::Null)));
                }
                "logic.api.gamelogic.cocktail_wins.Cocktail_Action"
            }
            "PICKME" | "MATCH3" | "PICKME_EXTENDED" | "CHANCE_WIN" | "PENALTY" | "PYRAMID_WIN" => {
                let (kind, field, choice) = choice_action(fid, state)?;
                let mut payload = json!({"@type":kind});
                payload[field] = json!(choice);
                return Ok(Some(("STEP_FEATURE", payload)));
            }
            _ => bail!("unsupported active feature: {fid}"),
        };
        return Ok(Some(("STEP_FEATURE", json!({"@type":action}))));
    }
    if let Some(f) = features
        .iter()
        .find(|f| f["status"] == "NOT_STARTED" && f["feature_id"] != "GAMBLE")
    {
        let fid = f["feature_id"]
            .as_str()
            .filter(|s| !s.is_empty())
            .context("missing feature id")?;
        return Ok(Some((
            "START_FEATURE",
            json!(["logic.api.gamelogic.FeatureID", fid]),
        )));
    }
    ensure!(
        features
            .iter()
            .all(|f| matches!(f["status"].as_str(), Some("FINISHED" | "NOT_STARTED"))),
        "unknown feature status"
    );
    Ok(Some(("END_GAME", Value::Null)))
}
fn choice_action(fid: &str, state: &Value) -> Result<(&'static str, &'static str, usize)> {
    let (kind, field, cells, hidden): (&str, &str, &Value, bool) = match fid {
        "PICKME" => (
            "logic.api.gamelogic.pickme.PickMe_Action",
            "player_choice",
            &state["field"],
            true,
        ),
        "MATCH3" => (
            "logic.api.gamelogic.match3.Match3_Action",
            "player_choice",
            &state["field"],
            true,
        ),
        "PICKME_EXTENDED" => {
            let level = state["level"].as_u64().context("missing level")? as usize;
            (
                "logic.api.gamelogic.pickmeExtended.PickMeExtendedAction",
                "player_choice",
                &state["items"][level],
                true,
            )
        }
        "CHANCE_WIN" => (
            "logic.api.gamelogic.chance.Chance_Action",
            "player_choice",
            &state["field"],
            false,
        ),
        "PENALTY" => (
            "logic.api.gamelogic.penalty.Penalty_Action",
            "playerChoice",
            &state["field"],
            false,
        ),
        "PYRAMID_WIN" => {
            let level = state["level"].as_i64().context("missing pyramid level")?;
            if level == 0 {
                return Ok((
                    "logic.api.gamelogic.pyramid.Pyramid_Action",
                    "player_choice",
                    1,
                ));
            }
            ensure!(level == 1, "unknown pyramid level");
            let row = state["row_in_pyramid"]
                .as_u64()
                .context("missing pyramid row")? as usize;
            (
                "logic.api.gamelogic.pyramid.Pyramid_Action",
                "player_choice",
                &state["pyramid_fields"][row],
                false,
            )
        }
        _ => bail!("unknown choice"),
    };
    let a = cells.as_array().context("missing choice options")?;
    let choice = if hidden {
        a.iter().position(|v| {
            v.as_i64().is_some_and(|n| {
                if fid == "PICKME_EXTENDED" {
                    n == -1
                } else {
                    n < 0
                }
            })
        })
    } else if !a.is_empty() {
        Some(0)
    } else {
        None
    };
    Ok((kind, field, choice.context("no offered choice")?))
}
async fn invoke(
    ctx: &RunContext,
    socket: &mut crate::context::NativeSocket,
    n: &mut u64,
    method: &str,
    payload: Value,
    financial: bool,
) -> Result<Value> {
    *n += 1;
    let request =
        json!({"@type":"MethodInvocation","requestId":*n,"method":method,"payload":payload});
    let response = ctx
        .ws_json(socket, method, &request, financial, Some(&n.to_string()))
        .await?;
    let payload = response
        .get("payload")
        .context("missing invocation payload")?
        .clone();
    ensure!(
        payload["@type"] != "InvocationError",
        "provider invocation error: {}",
        payload["code"]
    );
    Ok(payload)
}
fn valid_https(url: &Url, hosts: &[&str]) -> bool {
    url.scheme() == "https"
        && hosts.contains(&url.host_str().unwrap_or(""))
        && url.username().is_empty()
        && url.password().is_none()
        && url.port().is_none()
}
async fn get_official_play(ctx: &RunContext, mut url: Url) -> Result<String> {
    let path_re = Regex::new(r"^/(?:es/juegos|games)/[a-z0-9-]+/play$")?;
    for _ in 0..5 {
        ensure!(
            valid_https(&url, &["endorphina.com"])
                && path_re.is_match(url.path())
                && url.query().is_none()
                && url.fragment().is_none(),
            "invalid official demo play URL"
        );
        let response = ctx.get("official_play", url.as_str()).await?;
        if matches!(response.status, 301 | 302 | 303 | 307 | 308) {
            let location = response
                .headers
                .iter()
                .find(|(key, _)| key.eq_ignore_ascii_case("location"))
                .map(|(_, value)| value)
                .context("official play redirect missing location")?;
            url = url.join(location)?;
            continue;
        }
        ensure!(
            (200..300).contains(&response.status),
            "official play HTTP error"
        );
        return Ok(response.body);
    }
    bail!("too many official play redirects")
}
async fn get_follow(ctx: &RunContext, label: &str, mut url: Url) -> Result<(Url, String)> {
    for _ in 0..5 {
        ensure!(
            valid_https(&url, &["edemo.endorphina.com", "demo.endorphina.network"]),
            "unexpected demo redirect host"
        );
        let r = ctx.get(label, url.as_str()).await?;
        if (300..400).contains(&r.status) {
            let location = r
                .headers
                .iter()
                .find(|(k, _)| k.eq_ignore_ascii_case("location"))
                .map(|(_, v)| v)
                .context("redirect missing location")?;
            url = url.join(location)?;
            continue;
        }
        ensure!((200..300).contains(&r.status), "demo HTTP error");
        return Ok((url, r.body));
    }
    bail!("too many demo redirects")
}

pub async fn execute(
    ctx: &RunContext,
    game: &Game,
    mode: &Mode,
    settings: &Value,
) -> Result<RoundOutcome> {
    match mode.kind {
        ModeKind::Normal => ensure!(mode.key == "normal", "invalid normal selector"),
        ModeKind::Purchase => ensure!(
            mode.key.starts_with("buy-") && mode.key.len() > 4,
            "invalid buy selector"
        ),
        _ => bail!("unsupported Endorphina mode"),
    }
    let play = Url::parse(
        settings["launch_url"]
            .as_str()
            .context("Endorphina requires settings.launch_url with the official game play URL")?,
    )?;
    let landing = get_official_play(ctx, play.clone()).await?;
    let re = Regex::new(r"window\.location\.href\s*=\s*'([^']+)'")?;
    let launcher = Url::parse(&re.captures(&landing).context("missing official launcher")?[1])?;
    ensure!(
        valid_https(&launcher, &["edemo.endorphina.com"]),
        "unexpected official launcher"
    );
    let (demo_url, _) = get_follow(ctx, "demo_launcher", launcher).await?;
    ensure!(
        demo_url.host_str() == Some("demo.endorphina.network"),
        "unexpected final demo host"
    );
    let pairs: Vec<(String, String)> = demo_url
        .query_pairs()
        .map(|(k, v)| (k.into_owned(), v.into_owned()))
        .collect();
    let unique = |name: &str| -> Result<String> {
        let mut it = pairs.iter().filter(|(k, _)| k == name);
        let v = it
            .next()
            .context("missing demo launch parameter")?
            .1
            .clone();
        ensure!(
            it.next().is_none() && !v.is_empty(),
            "invalid demo launch parameter"
        );
        Ok(v)
    };
    let launch = unique("launch")?;
    ensure!(
        launch == "https://demo.endorphina.network/organic/websocket/launch",
        "unexpected launch endpoint"
    );
    let session = unique("session")?;
    let sign = unique("sign")?;
    let info = format!(
        "UA={}&L=en-US&V=1280x720x1&R=1280x720&TZ=GMT-0300&LS=[\"en-US\"]&OS=Win 10.0&ARCH=intel&AR=1&DP=12",
        ctx.user_agent()
    );
    let encoded_info: String = info
        .bytes()
        .map(|b| {
            if b.is_ascii_alphanumeric() || b"-_.~".contains(&b) {
                (b as char).to_string()
            } else {
                format!("%{b:02X}")
            }
        })
        .collect();
    let body = url::form_urlencoded::Serializer::new(String::new())
        .append_pair("session", &session)
        .append_pair("sign", &sign)
        .append_pair("info", &encoded_info)
        .append_pair("mobile", "false")
        .finish();
    let mut headers = BTreeMap::new();
    headers.insert(
        "content-type".into(),
        "application/x-www-form-urlencoded".into(),
    );
    let response = ctx
        .http("launch", "POST", &launch, headers, body, false)
        .await?;
    ensure!((200..300).contains(&response.status), "launch HTTP error");
    let launched: Value = serde_json::from_str(&response.body)?;
    let native_game = launched["game"]
        .as_str()
        .map(str::to_owned)
        .or_else(|| launched["game"].as_u64().map(|n| n.to_string()))
        .context("missing native game")?;
    let native_name = launched["gameName"]
        .as_str()
        .context("missing native game name")?;
    ensure!(
        native_name.eq_ignore_ascii_case(&game.name),
        "launched game name differs from inventory"
    );
    if native_game.bytes().all(|b| b.is_ascii_digit()) {
        ensure!(
            native_game == game.id,
            "launched game id differs from inventory"
        );
    }
    let native_re = Regex::new(r"^endorphina2_[A-Za-z0-9_]+$")?;
    ensure!(
        native_re.is_match(&native_game),
        "unrecognized published native game path"
    );
    let config_url = format!(
        "https://demo.endorphina.network/games-wgl/endorphina2/{}/configs/config.desktop.json",
        &native_game["endorphina2_".len()..]
    );
    let config_response = ctx.get("game_feature_config", &config_url).await?;
    ensure!(
        (200..300).contains(&config_response.status),
        "feature configuration HTTP error"
    );
    let config: Value = serde_json::from_str(&config_response.body)?;
    ensure!(
        config["game"]["features"].is_array(),
        "missing published feature configuration"
    );
    let currency = launched["currency"]
        .as_str()
        .filter(|v| !v.is_empty())
        .context("missing demo currency")?
        .to_string();
    let mut endpoint = Url::parse(
        launched["endpoint"]
            .as_str()
            .context("missing websocket endpoint")?,
    )?;
    let endpoint_re = Regex::new(r"^/organic/websocket/endpoint/[0-9]+$")?;
    ensure!(
        endpoint.scheme() == "wss"
            && endpoint.host_str() == Some("dyndemo.endorphina.network")
            && endpoint.port().is_none()
            && endpoint.username().is_empty()
            && endpoint.password().is_none()
            && endpoint.query().is_none()
            && endpoint.fragment().is_none()
            && endpoint_re.is_match(endpoint.path()),
        "unexpected websocket endpoint"
    );
    let ws_session = launched["session"]
        .as_str()
        .filter(|s| !s.is_empty())
        .context("missing websocket session")?;
    let ws_sign = launched["sign"]
        .as_str()
        .filter(|s| !s.is_empty())
        .context("missing websocket signature")?;
    endpoint
        .query_pairs_mut()
        .append_pair("session", ws_session)
        .append_pair("sign", ws_sign);
    let mut handshake = endpoint.clone();
    handshake
        .set_scheme("https")
        .map_err(|_| anyhow::anyhow!("invalid handshake URL"))?;
    let r = ctx.get("websocket_handshake", handshake.as_str()).await?;
    ensure!((200..300).contains(&r.status), "handshake HTTP error");
    let mut socket = ctx
        .websocket(
            endpoint.as_str(),
            "https://demo.endorphina.network",
            Some("json"),
            BTreeMap::new(),
        )
        .await?;
    let mut n = 0;
    let table = invoke(
        ctx,
        &mut socket,
        &mut n,
        "GET_PAYTABLE_INFO",
        Value::Null,
        false,
    )
    .await?;
    let mut balance = invoke(ctx, &mut socket, &mut n, "GET_BALANCE", Value::Null, false).await?;
    // Public demo funding may arrive just after the socket opens; only this read is polled.
    for _ in 0..5 {
        if amount(&balance["balance"])? > Decimal::ZERO {
            break;
        }
        tokio::time::sleep(std::time::Duration::from_millis(400)).await;
        balance = invoke(ctx, &mut socket, &mut n, "GET_BALANCE", Value::Null, false).await?;
    }
    let history = invoke(
        ctx,
        &mut socket,
        &mut n,
        "GET_LAST_GAME",
        Value::Null,
        false,
    )
    .await?;
    if let Some(c) = balance["currency"].as_str() {
        ensure!(c == currency, "balance currency mismatch");
    }
    let before = amount(&balance["balance"])?;
    let mut p = parameters(&table, &history)?;
    let price = if mode.kind == ModeKind::Purchase {
        let buy = &mode.key[4..];
        let offers = table["buyIns"]
            .as_array()
            .context("missing native buy offers")?;
        let mut matches = offers.iter().filter(|v| v["id"].as_str() == Some(buy));
        let offer = matches
            .next()
            .context("inventory buy not offered by fresh session")?;
        ensure!(matches.next().is_none(), "duplicate native buy offer");
        let price = amount(&offer["price"])?;
        ensure!(price > Decimal::ZERO, "invalid native buy price");
        p["buyInId"] = json!(buy);
        price
    } else {
        Decimal::ONE
    };
    let base = exact_add(
        exact_mul(amount(&p["bet_per_line"])?, amount(&p["num_of_lines"])?)?,
        amount(&p["extra_bet"])?,
    )?;
    let cost = exact_mul(exact_mul(base, amount(&p["denom"])?)?, price)?;
    ensure!(
        cost > Decimal::ZERO && before >= cost,
        "invalid or insufficient demo balance"
    );
    ctx.save_session(&json!({"provider":"endorphina","game":game.id,"native_game":native_game,"currency":currency,"endpoint":endpoint.as_str(),"play_url":play.as_str()}))?;
    let start = invoke(ctx, &mut socket, &mut n, "START_GAME", p.clone(), true).await?;
    let mut current = start["data"].clone();
    ensure!(current.is_object(), "missing started history");
    let mut trace = vec![json!({"method":"START_GAME","payload":start})];
    for _ in 0..ctx.max_steps() {
        let Some((method, payload)) = next_step(&current, &config)? else {
            break;
        };
        let result = invoke(ctx, &mut socket, &mut n, method, payload.clone(), true).await?;
        trace.push(json!({"method":method,"request_payload":payload,"result":result}));
        current = match method {
            "START_FEATURE" => {
                invoke(
                    ctx,
                    &mut socket,
                    &mut n,
                    "GET_LAST_GAME",
                    Value::Null,
                    false,
                )
                .await?
            }
            "STEP_FEATURE" => result["historyItem"].clone(),
            "END_FEATURE" => result,
            "END_GAME" => result["data"].clone(),
            _ => unreachable!(),
        };
        ensure!(current.is_object(), "missing continuation history");
    }
    ensure!(
        current["status"] == "FINISHED",
        "round did not close within step limit"
    );
    let features = current["features"]
        .as_array()
        .context("missing final features")?;
    let mut raw_win = Decimal::ZERO;
    for f in features {
        raw_win = exact_add(raw_win, amount(&f["current_win"])?)?;
    }
    let denom = amount(&current["betting_param"]["denom"])?;
    ensure!(denom == amount(&p["denom"])?, "bet denomination changed");
    let payout = exact_mul(raw_win, denom)?;
    let final_balance = invoke(ctx, &mut socket, &mut n, "GET_BALANCE", Value::Null, false).await?;
    if let Some(c) = final_balance["currency"].as_str() {
        ensure!(c == currency, "final currency mismatch");
    }
    let after = amount(&final_balance["balance"])?;
    // The published JSON client does not establish an explicit round identifier.
    let native_round_id = None;
    let mut checks = BTreeMap::new();
    checks.insert("fresh_demo_and_currency".into(), true);
    checks.insert("native_offer".into(), true);
    Ok(RoundOutcome {
        native_round_id,
        currency,
        monetary_unit: "native".into(),
        currency_source: "native_response".into(),
        balance_before: before.to_string(),
        balance_after: after.to_string(),
        cost: cost.to_string(),
        payout: payout.to_string(),
        native_closed: true,
        checks,
        native_data: json!({"launch":launched,"paytable":table,"feature_config":config,"initial_history":history,"parameters":p,"price":price.to_string(),"final_history":current,"steps":trace}),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        model::{CampaignPlan, InventorySnapshot, Job, RoundSpec},
        store::Store,
    };
    use std::sync::{Arc, Mutex};
    use tokio::{
        io::{AsyncReadExt, AsyncWriteExt},
        net::TcpListener,
    };

    async fn play_fixture(
        locations: Vec<Option<String>>,
    ) -> (
        tempfile::TempDir,
        RunContext,
        Arc<Mutex<Vec<String>>>,
        tokio::task::JoinHandle<()>,
    ) {
        let dir = tempfile::tempdir().unwrap();
        let store = Store::open(dir.path()).unwrap();
        let inventory: InventorySnapshot = serde_json::from_value(json!({
            "id":"official-play-fixture", "sources":[], "providers":[{
                "id":"endorphina", "name":"Endorphina", "ready":true,
                "campaign_eligible":true, "games":[{
                    "id":"fixture", "name":"Fixture", "ready":true,
                    "modes":[{"key":"normal","type":"normal","label":"Normal"}]
                }]
            }]
        }))
        .unwrap();
        store.install_inventory(&inventory).unwrap();
        let plan = CampaignPlan {
            schema_version: 1,
            id: "official-play-fixture".into(),
            inventory_id: inventory.id,
            coverage: None,
            jobs: vec![Job {
                provider: "endorphina".into(),
                game: "fixture".into(),
                mode: "normal".into(),
                samples: 1,
                settings: Value::Null,
            }],
        };
        store.create_campaign(&plan).unwrap();
        let round = store
            .create_round(&RoundSpec {
                campaign_id: plan.id,
                inventory_id: plan.inventory_id,
                job_index: 0,
                sample_index: 0,
                provider: "endorphina".into(),
                game: "fixture".into(),
                mode: "normal".into(),
                kind: ModeKind::Normal,
                settings: Value::Null,
            })
            .unwrap();
        let mut ctx = RunContext::new(store, round.id, "endorphina", 2, 10, None).unwrap();
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        ctx.route_to_fixture(&format!("http://{}", listener.local_addr().unwrap()))
            .unwrap();
        let requests = Arc::new(Mutex::new(Vec::new()));
        let saved = requests.clone();
        let task = tokio::spawn(async move {
            for (index, location) in locations.into_iter().enumerate() {
                let (mut socket, _) = listener.accept().await.unwrap();
                let mut bytes = Vec::new();
                while !bytes.ends_with(b"\r\n\r\n") {
                    let mut byte = [0u8];
                    socket.read_exact(&mut byte).await.unwrap();
                    bytes.push(byte[0]);
                    assert!(bytes.len() < 16_384);
                }
                let request = String::from_utf8(bytes).unwrap();
                let has_cookie = request
                    .to_ascii_lowercase()
                    .lines()
                    .any(|l| l.starts_with("cookie:") && l.contains("play_session=initialized"));
                saved.lock().unwrap().push(request);
                let (status, headers, body) = match location {
                    Some(location) => (
                        302,
                        format!(
                            "Location: {location}\r\nSet-Cookie: play_session=initialized; Path=/\r\n"
                        ),
                        "",
                    ),
                    None if index == 0 || has_cookie => (200, String::new(), "official landing"),
                    None => (403, String::new(), "HTTP session missing"),
                };
                let response = format!(
                    "HTTP/1.1 {status} Fixture\r\nContent-Length: {}\r\nConnection: close\r\n{headers}\r\n{body}",
                    body.len()
                );
                socket.write_all(response.as_bytes()).await.unwrap();
                socket.shutdown().await.unwrap();
            }
        });
        (dir, ctx, requests, task)
    }

    #[tokio::test]
    async fn official_play_redirect_preserves_its_http_session() {
        let (_dir, ctx, requests, task) =
            play_fixture(vec![Some("/es/juegos/fixture/play".into()), None]).await;
        let html = get_official_play(
            &ctx,
            Url::parse("https://endorphina.com/games/fixture/play").unwrap(),
        )
        .await
        .unwrap();
        assert_eq!(html, "official landing");
        task.await.unwrap();
        let requests = requests.lock().unwrap();
        assert_eq!(requests.len(), 2);
        assert!(requests[0].starts_with("GET /endorphina.com/games/fixture/play "));
        assert!(requests[1].starts_with("GET /endorphina.com/es/juegos/fixture/play "));
        for request in requests.iter() {
            assert!(
                request
                    .to_ascii_lowercase()
                    .contains("user-agent: mozilla/5.0\r\n")
            );
        }
    }

    #[tokio::test]
    async fn official_play_redirect_cannot_leave_the_reviewed_public_route() {
        for destination in [
            "https://evil.example/games/fixture/play",
            "https://edemo.endorphina.com/games/fixture/play",
            "http://endorphina.com/games/fixture/play",
            "https://endorphina.com/games/fixture/play?session=stale",
            "https://endorphina.com/account",
        ] {
            let (_dir, ctx, requests, task) = play_fixture(vec![Some(destination.into())]).await;
            let error = get_official_play(
                &ctx,
                Url::parse("https://endorphina.com/games/fixture/play").unwrap(),
            )
            .await
            .unwrap_err();
            assert!(error.to_string().contains("invalid official demo play URL"));
            task.await.unwrap();
            assert_eq!(requests.lock().unwrap().len(), 1);
        }
    }

    #[tokio::test]
    async fn official_play_redirect_loop_is_bounded() {
        let (_dir, ctx, requests, task) =
            play_fixture(vec![Some("/games/fixture/play".into()); 5]).await;
        let error = get_official_play(
            &ctx,
            Url::parse("https://endorphina.com/games/fixture/play").unwrap(),
        )
        .await
        .unwrap_err();
        assert!(
            error
                .to_string()
                .contains("too many official play redirects")
        );
        task.await.unwrap();
        assert_eq!(requests.lock().unwrap().len(), 5);
    }

    #[test]
    fn fresh_bet_must_be_published() {
        let t = json!({"bets_set":[1,2],"lines_set":[40],"denoms_set":["0.010"]});
        let h = json!({"status":"FINISHED","betting_param":{"bet_per_line":1,"num_of_lines":40,"denom":"0.010","buyInId":"old"}});
        assert!(parameters(&t, &h).unwrap().get("buyInId").is_none());
        assert!(parameters(&t, &json!({"status":"IN_PROGRESS"})).is_err());
        assert!(
            parameters(
                &json!({"bets_set":[1],"lines_set":[5],"denoms_set":["0.010"]}),
                &h
            )
            .is_err()
        );
    }
    #[test]
    fn closure_and_native_actions() {
        assert!(
            next_step(&json!({"status":"FINISHED","features":[]}), &Value::Null)
                .unwrap()
                .is_none()
        );
        let h = json!({"status":"IN_PROGRESS","features":[{"feature_id":"SLOT","status":"IN_PROGRESS","current_state":{"curr_reaction":{"pending":true}}}]});
        assert_eq!(
            next_step(&h, &Value::Null).unwrap().unwrap().1["@type"],
            "logic.api.gamelogic.slot.Drop_Action"
        );
        assert!(next_step(&json!({"status":"IN_PROGRESS","features":[{"feature_id":"UNKNOWN","status":"IN_PROGRESS","current_state":{}}]}),&Value::Null).is_err());
    }
    #[test]
    fn hidden_choice_uses_offered_cell() {
        let (action, field, index) = choice_action("PICKME", &json!({"field":[0,-1,-1]})).unwrap();
        assert_eq!(
            (action, field, index),
            (
                "logic.api.gamelogic.pickme.PickMe_Action",
                "player_choice",
                1
            )
        );
    }
}
