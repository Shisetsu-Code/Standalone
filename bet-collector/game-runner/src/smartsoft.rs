use regex::Regex;
use serde_json::{Value, json};
use std::collections::HashMap;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::time::Duration;
use url::Url;

// SmartSoft mixes chip amounts and wallet decimals. Reject amounts we cannot
// represent exactly instead of reconciling with a floating-point tolerance.
const SCALE: i128 = 100_000_000;

fn decimal(value: &Value) -> Result<i128, String> {
    let number;
    let text = match value.as_str() {
        Some(text) => text,
        None if value.is_number() => {
            number = value.to_string();
            &number
        }
        None => return Err("Falta importe SmartSoft".into()),
    };
    let (whole, fraction) = text.split_once('.').unwrap_or((text, ""));
    let fraction = fraction.trim_end_matches('0');
    if whole.is_empty()
        || fraction.len() > 8
        || !whole
            .bytes()
            .chain(fraction.bytes())
            .all(|c| c.is_ascii_digit())
    {
        return Err("Importe SmartSoft fuera de la precisión admitida".into());
    }
    let whole = whole
        .parse::<i128>()
        .ok()
        .and_then(|n| n.checked_mul(SCALE));
    let fraction_value =
        fraction.parse::<i128>().unwrap_or(0) * 10_i128.pow(8 - fraction.len() as u32);
    whole
        .and_then(|n| n.checked_add(fraction_value))
        .ok_or_else(|| "Importe fuera de rango".into())
}

fn multiply(left: i128, right: i128) -> Result<i128, String> {
    let product = left.checked_mul(right).ok_or("Importe fuera de rango")?;
    if product % SCALE != 0 {
        return Err("Producto monetario fuera de la precisión admitida".into());
    }
    Ok(product / SCALE)
}

fn formatted(value: i128) -> String {
    let whole = value / SCALE;
    let fraction = value % SCALE;
    if fraction == 0 {
        return whole.to_string();
    }
    format!("{whole}.{fraction:08}")
        .trim_end_matches('0')
        .to_owned()
}

fn free_spins(board: &Value) -> bool {
    board["FreeSpinsCount"]
        .as_u64()
        .is_some_and(|count| count > 0)
}

pub fn audit(row: &Value) -> Result<Value, String> {
    if row["moneda"] != "DMO" {
        return Err("Falta evidencia de moneda DMO".into());
    }
    let initial = &row["inicio"];
    let final_state = &row["final"];
    let option = row["opcion"].as_str().ok_or("Falta opción nativa")?;
    let rounds = row["rondas"]
        .as_array()
        .filter(|rounds| !rounds.is_empty())
        .ok_or("Faltan eventos de la ronda")?;
    let boards: Vec<_> = rounds
        .iter()
        .flat_map(|round| round["pasos"].as_array().into_iter().flatten())
        .collect();
    let last = *boards.last().ok_or("Falta tablero terminal")?;
    if final_state["evento"] != "start.game"
        || free_spins(last)
        || !final_state["opciones"]
            .as_array()
            .is_some_and(|options| options.iter().any(|value| value == "Start"))
    {
        return Err("No se confirmó el cierre de SmartSoft".into());
    }
    let before = decimal(&initial["Balance"])?;
    let after = decimal(&last["Balance"])?;
    let coefficient = decimal(&initial["ChipCoef"])?;
    let stake = multiply(
        multiply(
            decimal(&initial["LinePlay"])?,
            decimal(&initial["BetPerLine"])?,
        )?,
        coefficient,
    )?;
    let cost = match option {
        "Start" => stake,
        "PurchaseBonus" => {
            let first = &row["resultado"];
            let index = row["valor"]
                .as_u64()
                .and_then(|index| usize::try_from(index).ok())
                .ok_or("Falta índice de compra")?;
            if !initial["BonusPrices"]
                .as_array()
                .is_some_and(|prices| index < prices.len())
                || !free_spins(first)
                || first["FreeSpinFinished"] == true
            {
                return Err("Falta evidencia del cargo inicial de compra".into());
            }
            before
                .checked_sub(decimal(&first["Balance"])?)
                .ok_or("Cargo fuera de rango")?
        }
        "RiskBet" => {
            let multiplier = match initial["RiskBetMultipliers"].as_array() {
                Some(values) if !values.is_empty() => {
                    let index = row["valor"]
                        .as_u64()
                        .and_then(|index| usize::try_from(index).ok())
                        .ok_or("Falta índice RiskBet")?;
                    values.get(index).ok_or("RiskBet no publicado")?
                }
                _ => &initial["RiskBetMultiplier"],
            };
            multiply(stake, decimal(multiplier)?)?
        }
        _ => return Err("Modalidad SmartSoft sin conciliación nativa".into()),
    };
    let used_bonus = boards
        .iter()
        .any(|board| free_spins(board) || board["FreeSpinFinished"] == true);
    let payout = if used_bonus {
        &last["FreeSpinTotalWin"]
    } else {
        &last["TotalWin"]
    };
    let win = if payout.is_null() && !used_bonus {
        0
    } else {
        multiply(decimal(payout)?, coefficient)?
    };
    if cost <= 0
        || cost > before
        || before.checked_sub(cost).and_then(|x| x.checked_add(win)) != Some(after)
    {
        return Err("El saldo SmartSoft no concilia".into());
    }
    Ok(json!({
        "status": "completed", "closed": true, "wallet_check": "match", "currency": "DMO",
        "balance_before": formatted(before), "balance_after": formatted(after), "bet": formatted(stake),
        "cost": formatted(cost), "win": formatted(win),
        "round_phases": {
            "entry_event_index": 0, "accepted_event_index": 0, "closed_event_index": rounds.len() - 1,
            "selected_option": option, "selected_value": row["valor"],
            "options_offered": initial["opciones"], "purchase_prices": initial["BonusPrices"],
            "steps": rounds.iter().enumerate().map(|(index, round)| json!({
                "event_index": index, "event": round["estado"]["evento"],
                "options_offered": round["estado"]["opciones"],
                "selected_action": round["selected_option"]
            })).collect::<Vec<_>>()
        }
    }))
}

fn decode_entities(text: &str) -> String {
    let entities = Regex::new(r"&(?:amp|quot|apos|lt|gt|#(?:x[0-9a-fA-F]+|[0-9]+));").unwrap();
    entities
        .replace_all(text, |captures: &regex::Captures<'_>| {
            let entity = &captures[0];
            match entity {
                "&amp;" => "&".into(),
                "&quot;" => "\"".into(),
                "&apos;" => "'".into(),
                "&lt;" => "<".into(),
                "&gt;" => ">".into(),
                _ => {
                    let digits = &entity[2..entity.len() - 1];
                    let code = match digits.strip_prefix('x') {
                        Some(hex) => u32::from_str_radix(hex, 16),
                        None => digits.parse(),
                    };
                    code.ok()
                        .and_then(char::from_u32)
                        .map(|c| c.to_string())
                        .unwrap_or_else(|| entity.to_owned())
                }
            }
        })
        .into_owned()
}

fn get(client: &ureq::Agent, url: &str, stage: &str) -> Result<String, String> {
    let response = client.get(url).call().map_err(|error| match error {
        ureq::Error::Status(code, _) => format!("SmartSoft {stage} HTTP {code}"),
        ureq::Error::Transport(_) => format!("SmartSoft {stage}: fallo de transporte"),
    })?;
    if response.status() != 200 {
        return Err(format!("SmartSoft {stage} HTTP {}", response.status()));
    }
    response
        .into_string()
        .map_err(|_| format!("SmartSoft {stage}: documento inválido"))
}

fn demo_document(client: &ureq::Agent, mut loader: Url) -> Result<(Url, String), String> {
    let shard = Regex::new(r"^eu-server-w[0-9]+\.ssgportal\.com$").unwrap();
    for _ in 0..4 {
        if loader.scheme() != "https"
            || !loader.host_str().is_some_and(|host| shard.is_match(host))
            || !loader.path().starts_with("/SlotsDemo/")
            || !loader.username().is_empty()
            || loader.password().is_some()
            || loader.port().is_some()
        {
            return Err("Redirección fuera de SlotsDemo".into());
        }
        let response = client
            .get(loader.as_str())
            .call()
            .map_err(|error| match error {
                ureq::Error::Status(code, _) => format!("SmartSoft slots_demo HTTP {code}"),
                ureq::Error::Transport(_) => "SmartSoft slots_demo: fallo de transporte".into(),
            })?;
        match response.status() {
            200 => {
                let document = response
                    .into_string()
                    .map_err(|_| "Documento SlotsDemo inválido")?;
                return Ok((loader, document));
            }
            301 | 302 | 303 | 307 | 308 => {
                loader = loader
                    .join(
                        response
                            .header("Location")
                            .ok_or("Redirección sin destino")?,
                    )
                    .map_err(|_| "Redirección SlotsDemo inválida")?;
            }
            status => return Err(format!("SmartSoft slots_demo HTTP {status}")),
        }
    }
    Err("Límite de redirecciones SlotsDemo".into())
}

struct Demo {
    client: ureq::Agent,
    loader: Url,
    game_id: String,
    token: String,
    fraction_digits: u32,
    report: Value,
}

pub fn launcher(game: &str) -> Result<Value, String> {
    Ok(open_demo(game)?.report)
}

fn open_demo(game: &str) -> Result<Demo, String> {
    if game.is_empty() || !game.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'_') {
        return Err("Identidad SmartSoft inválida".into());
    }
    let client = ureq::AgentBuilder::new()
        .try_proxy_from_env(false)
        .redirects(0)
        .timeout(Duration::from_secs(20))
        .user_agent("game-runner/0.1.0")
        .build();
    let catalogue = get(
        &client,
        "https://www.smartsoftgaming.com/games",
        "catalogue",
    )?;
    let href = Regex::new(r#"href="([^"]+)""#).unwrap();
    let entry = href
        .captures_iter(&catalogue)
        .filter_map(|capture| {
            let decoded = decode_entities(&capture[1]);
            let candidate = if decoded.starts_with("eu-server.ssgportal.com/") {
                format!("https://{decoded}")
            } else {
                decoded
            };
            let mut url = Url::parse(&candidate).ok()?;
            if !matches!(url.scheme(), "http" | "https")
                || url.host_str() != Some("eu-server.ssgportal.com")
                || url.path() != "/GameLauncher/Loader.aspx"
                || !url.username().is_empty()
                || url.password().is_some()
                || url.port().is_some()
            {
                return None;
            }
            let mut query = url.query_pairs();
            let demo =
                query.any(|(key, value)| key == "PortalName" && value.eq_ignore_ascii_case("DEMO"));
            let matches_game = url
                .query_pairs()
                .any(|(key, value)| key == "GameName" && value == game);
            if !demo || !matches_game {
                return None;
            }
            url.set_scheme("https").ok()?;
            Some(url)
        })
        .next()
        .ok_or("Falta enlace oficial para ese juego")?;
    let launch = get(&client, entry.as_str(), "launcher")?;
    let loader_pattern = Regex::new(
        r#"https://eu-server-w[0-9]+\.ssgportal\.com/SlotsDemo/Loader\.aspx\?[^\s"'<>]+"#,
    )
    .unwrap();
    let loader = loader_pattern
        .find(&launch)
        .ok_or("Falta el cargador SlotsDemo")?;
    let loader =
        Url::parse(&decode_entities(loader.as_str())).map_err(|_| "Cargador SlotsDemo inválido")?;
    let (loader, document) = demo_document(&client, loader)?;
    let inputs = Regex::new(r"(?i)<input\b[^>]*>").unwrap();
    let attributes =
        Regex::new(r#"([a-zA-Z_][\w:-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))"#).unwrap();
    let mut fields = HashMap::new();
    for input in inputs.find_iter(&document) {
        let attrs: HashMap<_, _> = attributes
            .captures_iter(input.as_str())
            .map(|capture| {
                let name = capture[1].to_ascii_lowercase();
                let value = capture
                    .get(2)
                    .or_else(|| capture.get(3))
                    .or_else(|| capture.get(4))
                    .unwrap();
                (name, decode_entities(value.as_str()))
            })
            .collect();
        if let Some(id) = attrs.get("id") {
            fields.insert(id.clone(), attrs.get("value").cloned().unwrap_or_default());
        }
    }
    let currency: Value = serde_json::from_str(fields.get("Currency").ok_or("Falta moneda demo")?)
        .map_err(|_| "Moneda demo inválida")?;
    if currency["CurrencyCode"] != "DMO"
        || !fields
            .get("PortalName")
            .is_some_and(|name| name.eq_ignore_ascii_case("DEMO"))
        || !fields.get("Token").is_some_and(|value| !value.is_empty())
        || !fields.get("GameId").is_some_and(|value| !value.is_empty())
    {
        return Err(format!(
            "Sesión DMO SmartSoft sin confirmar (moneda DMO: {}, portal DEMO: {}, token: {}, juego: {})",
            currency["CurrencyCode"] == "DMO",
            fields
                .get("PortalName")
                .is_some_and(|name| name.eq_ignore_ascii_case("DEMO")),
            fields.get("Token").is_some_and(|value| !value.is_empty()),
            fields.get("GameId").is_some_and(|value| !value.is_empty()),
        ));
    }
    let report = json!({
        "provider": "smartsoft", "game_id": game, "currency": "DMO", "transport": "http_direct",
        "verified_stage": "demo_document",
        "launcher_host": entry.host_str(),
        "native_host": loader.host_str(),
        "native_api_path": "/SlotsDemo//api/GenericSlotApi"
    });
    Ok(Demo {
        client,
        loader,
        game_id: fields.remove("GameId").ok_or("Falta GameId demo")?,
        token: fields.remove("Token").ok_or("Falta token demo")?,
        fraction_digits: currency["FractionDigit"]
            .as_u64()
            .filter(|digits| *digits <= 8)
            .ok_or("Precisión DMO inválida")? as u32,
        report,
    })
}

impl Demo {
    fn endpoint(&self, method: &str, tail: Option<&str>) -> Result<Url, String> {
        let mut url = self
            .loader
            .join("/SlotsDemo//api/GenericSlotApi")
            .map_err(|_| "Endpoint SlotsDemo inválido")?;
        let mut path = url
            .path_segments_mut()
            .map_err(|_| "Endpoint SlotsDemo inválido")?;
        path.extend(method.split('/'))
            .push(&self.game_id)
            .push(&self.token);
        if let Some(tail) = tail {
            path.push(tail);
        }
        drop(path);
        Ok(url)
    }
}

fn api_json(response: Result<ureq::Response, ureq::Error>, stage: &str) -> Result<Value, String> {
    let response = response.map_err(|error| match error {
        ureq::Error::Status(code, _) => format!("SmartSoft {stage} HTTP {code}"),
        ureq::Error::Transport(_) => format!("SmartSoft {stage}: fallo de transporte"),
    })?;
    if response.status() != 200 {
        return Err(format!("SmartSoft {stage} HTTP {}", response.status()));
    }
    response
        .into_json()
        .map_err(|_| format!("SmartSoft {stage}: respuesta inválida"))
}

pub fn inventory(game: &str) -> Result<Value, String> {
    let mut demo = open_demo(game)?;
    let response = initial_state(&demo)?;
    let initial = state_summary(&response)?;
    demo.report["verified_stage"] = json!("native_start");
    demo.report["event"] = initial["evento"].clone();
    demo.report["balance_before"] = initial["Balance"].clone();
    demo.report["selection"] = json!({
        "lines": initial["LinePlay"], "bet_per_line": initial["BetPerLine"], "chip_coefficient": initial["ChipCoef"]
    });
    demo.report["options_offered"] = initial["opciones"].clone();
    demo.report["purchase_prices"] = initial["BonusPrices"].clone();
    demo.report["risk_bet_multipliers"] = initial["RiskBetMultipliers"].clone();
    demo.report["risk_bet_multiplier"] = initial["RiskBetMultiplier"].clone();
    demo.report["endpoints"] = json!([
        {"method": "POST", "path": "/SlotsDemo//api/GenericSlotApi/CustomEvent/{game_id}/{session_token}"},
        {"method": "GET", "path": "/SlotsDemo//api/GenericSlotApi/Events/{game_id}/{session_token}/0"}
    ]);
    Ok(demo.report)
}

fn initial_state(demo: &Demo) -> Result<Value, String> {
    let update = demo.endpoint("CustomEvent", None)?;
    api_json(
        demo.client
            .post(update.as_str())
            .set("Referer", demo.loader.as_str())
            .send_json(json!({"EventCode": "update.balance"})),
        "update_balance",
    )?;
    let events = demo.endpoint("Events", Some("0"))?;
    let response = api_json(
        demo.client
            .get(events.as_str())
            .set("Referer", demo.loader.as_str())
            .call(),
        "events",
    )?;
    let event = &response["PlayerEvent"];
    let options = event["Options"]
        .as_array()
        .ok_or("Faltan opciones nativas")?;
    if event["EventType"]["Code"] != "start.game"
        || !options.iter().any(|option| option["OptionKey"] == "Start")
    {
        return Err("SmartSoft no confirmó un estado inicial apto para Start".into());
    }
    let board = response["Board"]["MachineInfo"]
        .as_array()
        .and_then(|boards| boards.last())
        .ok_or("Falta saldo demo de MachineInfo")?;
    if decimal(&board["Balance"])? <= 0 {
        return Err("Saldo DMO no disponible".into());
    }
    Ok(response)
}

fn board_summary(event: &Value, board: &Value) -> Result<Value, String> {
    let name = event["EventType"]["Code"]
        .as_str()
        .ok_or("Falta fase nativa")?;
    let options = event["Options"]
        .as_array()
        .ok_or("Faltan opciones nativas")?;
    let mut summary = json!({"evento": name, "opciones": options.iter()
        .filter_map(|option| option["OptionKey"].as_str()).collect::<Vec<_>>()});
    for key in [
        "Balance",
        "LinePlay",
        "BetPerLine",
        "ChipCoef",
        "TotalWin",
        "FreeSpinTotalWin",
        "FreeSpinsCount",
        "FreeSpinFinished",
        "BonusPrices",
        "RiskBetMultipliers",
        "RiskBetMultiplier",
    ] {
        if let Some(value) = board.get(key) {
            summary[key] = value.clone();
        }
    }
    Ok(summary)
}

fn state_summary(response: &Value) -> Result<Value, String> {
    let event = &response["PlayerEvent"];
    let board = response["Board"]["MachineInfo"]
        .as_array()
        .and_then(|boards| boards.last())
        .unwrap_or(&event["Board"]);
    board_summary(event, board)
}

pub fn run_case(case: &Value, path: &Path) -> Result<Value, String> {
    if case["provider"] != "smartsoft" || case["execution_source"] != "native_remote" {
        return Err("Caso ajeno al runner SmartSoft".into());
    }
    let game = case["game"]["code"]
        .as_str()
        .ok_or("Falta juego SmartSoft")?;
    let spec = &case["mode"]["spec"];
    let mut option = spec["option"].as_str().ok_or("Falta opción SmartSoft")?;
    if !matches!(option, "Start" | "RiskBet" | "PurchaseBonus") {
        return Err("Modalidad SmartSoft pendiente".into());
    }
    let value = spec["value"].as_u64();
    let mut journal = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)
        .map_err(|error| format!("No se pudo reservar el journal SmartSoft: {error}"))?;
    let mut log = |entry: Value| -> Result<(), String> {
        serde_json::to_writer(&mut journal, &entry).map_err(|error| error.to_string())?;
        journal
            .write_all(b"\n")
            .and_then(|_| journal.sync_data())
            .map_err(|error| error.to_string())
    };
    let demo = open_demo(game)?;
    let mut current = initial_state(&demo)?;
    let initial = state_summary(&current)?;
    let coefficient = decimal(&initial["ChipCoef"])?;
    let selector = format!(
        "{},{},{}",
        formatted(decimal(&initial["LinePlay"])?),
        formatted(decimal(&initial["BetPerLine"])?),
        formatted(
            coefficient
                .checked_mul(10_i128.pow(demo.fraction_digits))
                .ok_or("Coeficiente fuera de rango")?
        )
    );
    let mut evidence = json!({"juego": game, "moneda": "DMO", "opcion": option,
                              "valor": value, "inicio": initial});
    let mut rounds = Vec::new();
    let endpoint = demo.endpoint("Event/2", None)?;
    log(json!({"event": "initialized", "state": initial, "selection": selector}))?;
    for index in 0..60 {
        let state = state_summary(&current)?;
        if !state["opciones"]
            .as_array()
            .is_some_and(|options| options.iter().any(|item| item == option))
        {
            return Err("Opción ausente en el estado nativo".into());
        }
        if index == 0
            && option == "PurchaseBonus"
            && !value.is_some_and(|value| {
                initial["BonusPrices"]
                    .as_array()
                    .is_some_and(|prices| value < prices.len() as u64)
            })
        {
            return Err("Precio de compra no publicado".into());
        }
        if index == 0 && option == "RiskBet" {
            let multiplier = match initial["RiskBetMultipliers"].as_array() {
                Some(values) if !values.is_empty() => value
                    .and_then(|idx| usize::try_from(idx).ok())
                    .and_then(|idx| values.get(idx))
                    .ok_or("RiskBet no publicado")?,
                _ => &initial["RiskBetMultiplier"],
            };
            if decimal(multiplier)? == 0 {
                return Err("RiskBet no publicado".into());
            }
        }
        let event_id = &current["PlayerEvent"]["EventId"];
        if !(event_id.is_string() || event_id.is_number()) {
            return Err("Falta ID de evento SmartSoft".into());
        }
        let selected_value = if index == 0 {
            value.map(|value| value.to_string())
        } else {
            None
        };
        let pieces = if index == 0 || matches!(option, "Start" | "PlayBonus") {
            &selector
        } else {
            ""
        };
        log(
            json!({"event": "sending", "index": index, "option": option, "value": selected_value,
                   "pieces": pieces, "endpoint": "/SlotsDemo//api/GenericSlotApi/Event/2/{game_id}/{session_token}"}),
        )?;
        current = api_json(
            demo.client
                .post(endpoint.as_str())
                .set("Referer", demo.loader.as_str())
                .send_json(
                    json!({"EventId": event_id, "SelectedOption": option, "SelectedPieces": pieces,
                              "SelectedValue": selected_value}),
                ),
            "event",
        )?;
        let state = state_summary(&current)?;
        let boards = current["Board"]["MachineInfo"]
            .as_array()
            .into_iter()
            .flatten()
            .map(|board| board_summary(&current["PlayerEvent"], board))
            .collect::<Result<Vec<_>, _>>()?;
        let step = json!({"estado": state, "pasos": boards, "selected_option": option});
        log(json!({"event": "received", "index": index, "step": step}))?;
        rounds.push(step);
        if index == 0 {
            evidence["resultado"] = state.clone();
        }
        if state["evento"] == "start.game"
            && (!free_spins(&state) || state["FreeSpinFinished"] == true)
        {
            evidence["final"] = state;
            evidence["rondas"] = json!(rounds);
            let mut report = audit(&evidence)?;
            report["source"] = json!("native_remote");
            report["round_phases"]["transport"] = json!("http_direct");
            report["round_phases"]["endpoint"] = json!({
                "method": "POST", "path": "/SlotsDemo//api/GenericSlotApi/Event/2/{game_id}/{session_token}"
            });
            log(json!({"event": "audit", "report": report}))?;
            return Ok(report);
        }
        let candidates: &[&str] = if state["evento"] == "start.game" {
            &["Start"]
        } else {
            &["PlayBonus", "FreeSpin", "PlayFreeSpin", "Finish"]
        };
        option = candidates
            .iter()
            .copied()
            .find(|key| {
                state["opciones"]
                    .as_array()
                    .is_some_and(|options| options.iter().any(|item| item == *key))
            })
            .ok_or("Continuación SmartSoft desconocida")?;
    }
    Err("Límite de continuaciones SmartSoft".into())
}
