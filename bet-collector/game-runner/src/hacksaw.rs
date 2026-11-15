use serde::Deserialize;
use serde_json::{Value, json};
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::path::Path;
use std::time::Duration;

const CDN: &str = "https://static-live.hacksawgaming.com";
const API: &str = "https://rgs-demo.hacksawgaming.com/api";
const USER_AGENT: &str = "game-runner/0.1.0";

fn amount(value: &Value) -> Result<i64, String> {
    value
        .as_i64()
        .or_else(|| value.as_str()?.parse().ok())
        .filter(|amount| *amount >= 0)
        .ok_or_else(|| "Importe nativo inválido".into())
}

/// Audit a sanitized trace emitted by the native Hacksaw adapter.
pub fn audit(trace: &Value) -> Result<Value, String> {
    let packets = trace.as_array().ok_or("Traza inválida")?;
    let (auth_index, auth_packet) = packets
        .iter()
        .enumerate()
        .find(|(_, packet)| packet["endpoint"] == "/api/play/authenticate")
        .ok_or("Falta autenticación")?;
    let auth = &auth_packet["response"];
    if auth_packet["http_status"] != 200
        || auth["statusCode"] != 0
        || auth["name"] != "Demo"
        || auth["accountBalance"]["currencyCode"] != "EUR"
        || auth_packet["request"]["partner"] != "demo"
        || auth_packet["request"]["mode"] != 2
    {
        return Err("La autenticación no confirma una demo EUR".into());
    }
    let before = amount(&auth["accountBalance"]["balance"])?;
    let rounds: Vec<_> = packets
        .iter()
        .enumerate()
        .filter(|(_, packet)| packet["endpoint"] == "/api/play/bet")
        .collect();
    let &(start, first) = rounds.first().ok_or("Falta solicitud de entrada")?;
    let &(end, last) = rounds.last().ok_or("Falta respuesta terminal")?;
    if start <= auth_index {
        return Err("La entrada precede a la autenticación".into());
    }
    let bets = first["request"]["bets"]
        .as_array()
        .filter(|bets| bets.len() == 1)
        .ok_or("Entrada sin apuesta única")?;
    let stake = amount(&bets[0]["betAmount"])?;
    if stake == 0 {
        return Err("Apuesta base inválida".into());
    }
    let offers = auth["bonusGames"]
        .as_array()
        .map(Vec::as_slice)
        .unwrap_or_default();
    let selected = bets[0]["buyBonus"].as_str();
    let multiplier = match selected {
        None => 1,
        Some(id) => {
            let offer = offers
                .iter()
                .find(|offer| offer["bonusGameId"] == id)
                .ok_or("Compra ausente del inventario autenticado")?;
            amount(&offer["betCostMultiplier"])?
        }
    };
    let cost = stake
        .checked_mul(multiplier)
        .filter(|cost| *cost > 0 && *cost <= before)
        .ok_or("Costo inválido")?;
    let round_id = &first["response"]["round"]["roundId"];
    if !(round_id.is_string() || round_id.is_number()) {
        return Err("Falta ID nativo de ronda".into());
    }
    let mut win = 0_i64;
    let mut steps = Vec::new();
    let mut previous: Option<&Value> = None;
    for (index, packet) in rounds {
        let request = &packet["request"];
        let response = &packet["response"];
        let round = &response["round"];
        if packet["http_status"] != 200
            || response["statusCode"] != 0
            || &round["roundId"] != round_id
        {
            return Err(format!("Respuesta de ronda inválida en paquete {index}"));
        }
        let action = request["continueInstructions"]["action"].as_str();
        if let Some(prior) = previous {
            let offered = prior["possibleActions"]
                .as_array()
                .map(Vec::as_slice)
                .unwrap_or_default();
            let allowed = action.is_some_and(|action| {
                if offered.is_empty() {
                    prior["status"] == "wfwpc" && action == "win_presentation_complete"
                } else {
                    offered.iter().any(|option| option == action)
                }
            });
            if prior["status"] == "completed"
                || &request["roundId"] != round_id
                || !request["bets"].is_null()
                || !allowed
            {
                return Err(format!("Continuación inválida en paquete {index}"));
            }
        }
        for event in round["events"].as_array().into_iter().flatten() {
            if let Some(value) = event.get("wa") {
                win = win
                    .checked_add(amount(value)?)
                    .ok_or("Premio fuera de rango")?;
            }
        }
        steps.push(json!({
            "packet_index": index, "endpoint": "/api/play/bet",
            "status": round["status"], "options_offered": round["possibleActions"],
            "selected_action": action
        }));
        previous = Some(round);
    }
    let terminal = &last["response"]["round"];
    if terminal["status"] != "completed"
        || terminal["possibleActions"]
            .as_array()
            .is_some_and(|options| !options.is_empty())
    {
        return Err("Falta cierre terminal nativo".into());
    }
    if last["response"]["accountBalance"]["currencyCode"] != "EUR" {
        return Err("Moneda final inválida".into());
    }
    let after = amount(&last["response"]["accountBalance"]["balance"])?;
    if before
        .checked_sub(cost)
        .and_then(|balance| balance.checked_add(win))
        != Some(after)
    {
        return Err("El saldo final no concilia".into());
    }
    Ok(json!({
        "round_id": round_id, "round_closed": true, "wallet_check": "match", "currency": "EUR",
        "balance_before": before, "bet": stake, "cost": cost, "win": win, "balance_after": after,
        "purchase_offers": offers.iter().map(|offer| json!({
            "id": offer["bonusGameId"], "multiplier": offer["betCostMultiplier"]
        })).collect::<Vec<_>>(),
        "selected_purchase": selected,
        "entry_packet_index": start, "accepted_packet_index": start, "closed_packet_index": end,
        "steps": steps
    }))
}

#[derive(Deserialize)]
struct Version {
    version: String,
}

fn agent(proxy: Option<&str>) -> Result<ureq::Agent, String> {
    let mut builder = ureq::AgentBuilder::new()
        .try_proxy_from_env(false)
        .user_agent(USER_AGENT)
        .redirects(0)
        .timeout(Duration::from_secs(20));
    if let Some(proxy) = proxy {
        builder = builder.proxy(ureq::Proxy::new(proxy).map_err(|_| "Relay inválido")?);
    }
    Ok(builder.build())
}

pub fn launcher(game: &str, proxy: Option<&str>) -> Result<Value, String> {
    resolve_launcher(game, proxy, &agent(proxy)?)
}

fn resolve_launcher(game: &str, proxy: Option<&str>, agent: &ureq::Agent) -> Result<Value, String> {
    if game.is_empty() || !game.bytes().all(|byte| byte.is_ascii_digit()) {
        return Err("ID numérico de Hacksaw inválido".into());
    }
    let endpoint = format!("{CDN}/{game}/version.json");
    let response = agent.get(&endpoint).call().map_err(|error| match error {
        ureq::Error::Status(status, _) => format!("Hacksaw version.json HTTP {status}"),
        ureq::Error::Transport(_) => "No se pudo consultar la versión pública de Hacksaw".into(),
    })?;
    if response.status() != 200 {
        return Err(format!("Hacksaw version.json HTTP {}", response.status()));
    }
    let Version { version } = response
        .into_json()
        .map_err(|_| "Respuesta de versión inválida")?;
    let parts: Vec<_> = version.split('.').collect();
    if !(2..=4).contains(&parts.len())
        || parts
            .iter()
            .any(|part| part.is_empty() || !part.bytes().all(|byte| byte.is_ascii_digit()))
    {
        return Err("Versión pública de Hacksaw inválida".into());
    }
    let direct = format!(
        "{CDN}/{game}/{version}/index.html?language=en&channel=desktop&gameid={game}&mode=2&token=123131&lobbyurl=https%3A%2F%2Fwww.hacksawgaming.com&currency=EUR&partner=demo&env={API}&realmoneyenv=https%3A%2F%2F"
    );
    Ok(json!({
        "provider": "hacksaw",
        "game_id": game,
        "version": version,
        "version_endpoint": endpoint,
        "direct_demo_url": direct,
        "transport": if proxy.is_some() { "http_relay" } else { "http_direct" },
        "verified_stage": "public_version"
    }))
}

pub fn authenticate_demo(game: &str, proxy: Option<&str>) -> Result<Value, String> {
    let client = agent(proxy)?;
    let (launch, _) = authenticate(game, proxy, &client)?;
    Ok(launch)
}

fn authenticate(
    game: &str,
    proxy: Option<&str>,
    client: &ureq::Agent,
) -> Result<(Value, Value), String> {
    let game_id: u32 = game
        .parse()
        .map_err(|_| "ID numérico de Hacksaw inválido")?;
    let mut launch = resolve_launcher(game, proxy, client)?;
    let endpoint = format!("{API}/play/authenticate");
    let request = json!({
        "seq": 1, "partner": "demo", "gameId": game_id, "gameVersion": launch["version"],
        "currency": "EUR", "languageCode": "en-us", "mode": 2, "branding": "default",
        "channel": 1, "userAgent": USER_AGENT, "token": "123131"
    });
    let response = client
        .post(&endpoint)
        .set("Origin", CDN)
        .set("Referer", &format!("{CDN}/"))
        .send_json(request.clone())
        .map_err(|error| match error {
            ureq::Error::Status(status, _) => format!("Hacksaw authenticate HTTP {status}"),
            ureq::Error::Transport(_) => "No se pudo confirmar la autenticación de Hacksaw".into(),
        })?;
    if response.status() != 200 {
        return Err(format!("Hacksaw authenticate HTTP {}", response.status()));
    }
    let auth: Value = response
        .into_json()
        .map_err(|_| "Respuesta de autenticación inválida")?;
    if auth["statusCode"] != 0
        || auth["name"] != "Demo"
        || !(auth["gameId"] == game || auth["gameId"] == game_id)
        || !(auth["roundId"] == "0" || auth["roundId"] == 0)
        || !auth["roundStatus"].is_null()
        || auth["accountBalance"]["currencyCode"] != "EUR"
        || !auth["sessionUuid"]
            .as_str()
            .is_some_and(|id| !id.is_empty())
    {
        return Err("La respuesta no confirma una sesión demo nueva para ese juego".into());
    }
    let levels = auth["betLevels"]
        .as_array()
        .ok_or("Faltan importes publicados")?;
    let minimum = levels
        .iter()
        .map(amount)
        .collect::<Result<Vec<_>, _>>()?
        .into_iter()
        .filter(|value| *value > 0)
        .min()
        .ok_or("Falta importe mínimo")?;
    launch["verified_stage"] = json!("authenticated_demo");
    launch["authenticate_endpoint"] = json!(endpoint);
    launch["currency"] = json!("EUR");
    launch["balance_before"] = json!(amount(&auth["accountBalance"]["balance"])?);
    launch["minimum_bet"] = json!(minimum);
    launch["purchase_offers"] = json!(auth["bonusGames"].as_array().into_iter().flatten()
        .map(|offer| json!({"id": offer["bonusGameId"], "multiplier": offer["betCostMultiplier"]}))
        .collect::<Vec<_>>());
    Ok((
        launch,
        json!({
            "endpoint": "/api/play/authenticate", "http_status": 200,
            "request": request, "response": auth
        }),
    ))
}

fn redact(value: &Value) -> Value {
    match value {
        Value::Object(fields) => Value::Object(
            fields
                .iter()
                .map(|(key, value)| {
                    let cleaned = match key.to_ascii_lowercase().as_str() {
                        "sessionuuid" | "token" | "playerid" | "cookie" | "authorization"
                        | "set-cookie" => json!("[REDACTED]"),
                        _ => redact(value),
                    };
                    (key.clone(), cleaned)
                })
                .collect(),
        ),
        Value::Array(items) => Value::Array(items.iter().map(redact).collect()),
        _ => value.clone(),
    }
}

fn record(journal: &mut File, entry: &Value) -> Result<(), String> {
    serde_json::to_writer(&mut *journal, entry).map_err(|e| e.to_string())?;
    journal
        .write_all(b"\n")
        .and_then(|_| journal.sync_data())
        .map_err(|e| e.to_string())
}

pub fn run_case(case: &Value, journal_path: &Path) -> Result<Value, String> {
    let game = case["game"]["id"].as_str().ok_or("Falta ID del juego")?;
    if case["provider"] != "hacksaw" || case["execution_source"] != "native_remote" {
        return Err("Caso ajeno al runner nativo de Hacksaw".into());
    }
    let mut journal = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(journal_path)
        .map_err(|e| format!("No se pudo reservar el journal de ronda: {e}"))?;
    let proxy = Some("http://127.0.0.1:8793");
    let client = agent(proxy)?;
    let (launch, auth) = authenticate(game, proxy, &client)?;
    let auth = &auth;
    let session = &auth["response"]["sessionUuid"];
    let spec = &case["mode"]["spec"];
    let bonus = spec["bonus_id"].as_str();
    let base_mode = spec["base_mode"].as_str();
    let stake = amount(&launch["minimum_bet"])?;
    let mut bet = json!({"betAmount": stake.to_string()});
    if let Some(id) = bonus {
        let offer = launch["purchase_offers"]
            .as_array()
            .into_iter()
            .flatten()
            .find(|offer| offer["id"] == id)
            .ok_or("Compra no ofrecida")?;
        let multiplier = amount(&offer["multiplier"])?;
        if amount(&spec["multiplier"])? != multiplier
            || stake.checked_mul(multiplier).is_none_or(|cost| {
                cost <= 0 || cost > launch["balance_before"].as_i64().unwrap_or(0)
            })
        {
            return Err("El precio o saldo de la compra cambió".into());
        }
        bet["buyBonus"] = json!(id);
    } else if case["type"] != "normal" && base_mode.is_none() {
        return Err("Modalidad sin selector nativo".into());
    }
    if game == "1426" {
        let volatility = bonus
            .and_then(|id| id.rsplit('_').next())
            .or(base_mode)
            .unwrap_or("low");
        if !matches!(volatility, "low" | "extreme")
            || base_mode.is_some_and(|mode| mode != volatility)
        {
            return Err("Volatilidad nativa inválida".into());
        }
        bet["customData"] = json!({"volatility": volatility});
    } else if base_mode.is_some() {
        return Err("Selector no publicado para este juego".into());
    }
    if stake > amount(&launch["balance_before"])? {
        return Err("Saldo demo insuficiente".into());
    }
    let mut trace = vec![redact(auth)];
    record(&mut journal, &trace[0])?;
    let mut request = json!({
        "seq": 2, "sessionUuid": session, "bets": [bet],
        "offerId": null, "promotionId": null, "autoplay": false
    });
    let mut round_id = Value::Null;
    for seq in 2..=201 {
        let mut packet = json!({"endpoint": "/api/play/bet", "request": redact(&request)});
        record(&mut journal, &json!({"event": "sending", "packet": packet}))?;
        let response = match client
            .post(&format!("{API}/play/bet"))
            .set("Origin", CDN)
            .set("Referer", &format!("{CDN}/"))
            .send_json(request)
        {
            Ok(response) => response,
            Err(ureq::Error::Status(status, _)) => {
                record(
                    &mut journal,
                    &json!({"event": "http_error", "http_status": status, "seq": seq}),
                )?;
                return Err(format!("Hacksaw bet HTTP {status}"));
            }
            Err(_) => return Err("Resultado HTTP incierto: conservar journal".into()),
        };
        let status = response.status();
        let reply: Value = response
            .into_json()
            .map_err(|_| "Respuesta de ronda inválida")?;
        packet["http_status"] = json!(status);
        packet["response"] = redact(&reply);
        record(
            &mut journal,
            &json!({"event": "received", "packet": packet}),
        )?;
        trace.push(packet);
        let round = &reply["round"];
        if seq == 2 {
            round_id = round["roundId"].clone();
        }
        if status != 200
            || reply["statusCode"] != 0
            || !(round_id.is_string() || round_id.is_number())
            || round["roundId"] != round_id
        {
            return Err("Respuesta de ronda sin confirmar".into());
        }
        if round["status"] == "completed" {
            let mut report = audit(&json!(trace))?;
            report["status"] = json!("completed");
            report["closed"] = json!(true);
            report["source"] = json!("native_remote");
            report["round_phases"] = json!({
                "transport": "http_relay", "entry_packet_index": report["entry_packet_index"],
                "accepted_packet_index": report["accepted_packet_index"], "closed_packet_index": report["closed_packet_index"],
                "options_offered": report["purchase_offers"], "selected_option": bonus.or(base_mode),
                "steps": report["steps"]
            });
            record(&mut journal, &json!({"event": "audit", "report": report}))?;
            return Ok(report);
        }
        let action = round["possibleActions"]
            .as_array()
            .and_then(|items| items.first())
            .and_then(Value::as_str)
            .or_else(|| (round["status"] == "wfwpc").then_some("win_presentation_complete"))
            .ok_or("Continuación nativa desconocida")?;
        request = json!({"seq": seq + 1, "sessionUuid": session, "roundId": round_id,
                         "continueInstructions": {"action": action}});
    }
    Err("Límite de continuaciones alcanzado".into())
}
