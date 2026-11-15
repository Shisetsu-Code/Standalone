use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::path::Path;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use uuid::Uuid;

const SITE: &str = "https://3oaks.com";

fn checked(
    response: Result<ureq::Response, ureq::Error>,
    stage: &str,
) -> Result<ureq::Response, String> {
    match response {
        Ok(response) if response.status() == 200 => Ok(response),
        Ok(response) => Err(format!("3 Oaks {stage} HTTP {}", response.status())),
        Err(ureq::Error::Status(status, _)) => Err(format!("3 Oaks {stage} HTTP {status}")),
        Err(_) => Err(format!("3 Oaks {stage}: transporte no confirmado")),
    }
}

fn parse(response: ureq::Response) -> Result<Value, String> {
    response
        .into_json()
        .map_err(|_| "Respuesta JSON inválida de 3 Oaks".into())
}

fn command(
    client: &ureq::Agent,
    endpoint: &str,
    name: &str,
    mut fields: Value,
) -> Result<Value, String> {
    let request_id = Uuid::new_v4().simple().to_string();
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "Reloj inválido")?;
    fields["command"] = json!(name);
    fields["request_id"] = json!(request_id);
    fields["client_command_timestamp"] = json!(timestamp.as_millis());
    let response = parse(checked(
        client
            .post(endpoint)
            .set("Origin", SITE)
            .set("Referer", &format!("{SITE}/"))
            .send_json(fields),
        name,
    )?)?;
    if response["request_id"] != request_id
        || response["command"] != name
        || response["status"]["code"] != "OK"
        || response["user"]["currency"] != "FUN"
    {
        return Err(format!("3 Oaks no confirmó la respuesta FUN de {name}"));
    }
    Ok(response)
}

struct Demo {
    client: ureq::Agent,
    endpoint: String,
    session: String,
    start: Value,
    source_url: String,
    report: Value,
}

pub fn inventory(game: &str) -> Result<Value, String> {
    Ok(open_demo(game)?.report)
}

fn open_demo(game: &str) -> Result<Demo, String> {
    if game.is_empty()
        || !game
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'_')
    {
        return Err("Identidad 3 Oaks inválida".into());
    }
    let client = ureq::AgentBuilder::new()
        .try_proxy_from_env(false)
        .redirects(0)
        .user_agent("game-runner/0.1.0")
        .timeout(Duration::from_secs(25))
        .build();
    let details = format!("{SITE}/api/v1/games/{game}");
    let metadata = parse(checked(client.get(&details).call(), "metadata")?)?;
    if metadata["data"]["name"] != game || metadata["data"]["is_playable"] != true {
        return Err("3 Oaks no publica una demo para ese juego".into());
    }
    let launch_url = format!("{details}/play?lang=en");
    let html = checked(client.get(&launch_url).call(), "launcher")?
        .into_string()
        .map_err(|_| "Documento launcher inválido")?;
    let (_, source) = html
        .rsplit_once("})(window, {")
        .ok_or("Falta configuración del launcher")?;
    let config_text = format!("{{{source}");
    let config = Value::deserialize(&mut serde_json::Deserializer::from_str(&config_text))
        .map_err(|_| "Configuración del launcher inválida")?;
    let options = &config["options"];
    let expected =
        format!("//betman-demo.head.3oaks.com/betman-demo/gs/{game}/desktop/{{QUEUE}}/demo/");
    let queue = options["queue"].as_str().ok_or("Falta ruta de sesión")?;
    if options["provider"] != "3oaks"
        || options["project_name"] != "betman-demo"
        || options["wl"] != "demo"
        || options["game_name"] != game
        || config["desktop"]["server_url"] != expected
        || queue.len() != 32
        || !queue
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err("El launcher no confirmó el perfil oficial FUN".into());
    }
    let token = options["token"]
        .as_str()
        .filter(|token| !token.is_empty())
        .ok_or("Falta token FUN")?;
    let endpoint = format!("https:{}", expected.replace("{QUEUE}", queue));
    let login = command(
        &client,
        &endpoint,
        "login",
        json!({"token": token, "language": "en"}),
    )?;
    let session = login["session_id"]
        .as_str()
        .filter(|session| !session.is_empty())
        .ok_or("Falta sesión FUN")?;
    if !login["modes"]
        .as_array()
        .is_some_and(|modes| modes.iter().any(|mode| mode == "auto"))
    {
        return Err("Modo auto no publicado".into());
    }
    std::thread::sleep(Duration::from_millis(1500));
    let start = command(
        &client,
        &endpoint,
        "start",
        json!({
            "session_id": session, "mode": "auto", "huid": Uuid::new_v4().simple().to_string()
        }),
    )?;
    let context = &start["context"];
    let settings = &start["settings"];
    if context["round_finished"] != true
        || !settings["bets"].is_array()
        || !settings["lines"].is_array()
    {
        return Err("No se confirmó el estado inicial FUN".into());
    }
    let source_url = config["desktop"]["client_url"]
        .as_str()
        .ok_or("Falta cliente 3 Oaks")?;
    let expected_source = regex::Regex::new(&format!(
        r"^https://static\.3oaks\.com/gs/clients_[a-z0-9_]+/{game}/[a-zA-Z0-9_.-]+/$"
    ))
    .map_err(|_| "Patrón de cliente inválido")?;
    if !expected_source.is_match(source_url) {
        return Err("Ruta de cliente 3 Oaks no confirmada".into());
    }
    let report = json!({
        "provider": "threeoaks", "game_id": game, "transport": "http_direct",
        "currency": "FUN", "verified_stage": "native_start", "launch_url": launch_url,
        "endpoint_template": format!("https:{expected}"),
        "balance_before": start["user"]["balance"], "bets": settings["bets"],
        "lines": settings["lines"], "selected_lines": context["spins"]["lines"],
        "bet_factor": settings["bet_factor"], "actions": context["actions"],
        "purchase_options": context["available_buy_bonus"], "purchase_prices": settings.get("buy_bonus_prices").or_else(|| settings.get("freespins_buying_price")),
        "booster_options": context["available_booster"], "booster_prices": settings["booster_prices"]
    });
    Ok(Demo {
        client,
        endpoint,
        session: session.into(),
        start,
        source_url: format!("{source_url}src/game.js"),
        report,
    })
}

fn native_int(value: &Value) -> Result<i64, String> {
    if let Some(number) = value.as_i64() {
        return Ok(number);
    }
    let number;
    let text = match value.as_str() {
        Some(text) => text,
        None if value.is_number() => {
            number = value.to_string();
            &number
        }
        None => return Err("Falta importe 3 Oaks".into()),
    };
    let whole = match text.split_once('.') {
        Some((whole, fraction)) if fraction.bytes().all(|byte| byte == b'0') => whole,
        _ => text,
    };
    whole
        .parse()
        .map_err(|_| "Importe no entero de 3 Oaks".into())
}

fn key(value: &Value) -> String {
    value
        .as_str()
        .map(str::to_owned)
        .unwrap_or_else(|| value.to_string())
}

fn cost(base: i64, multiplier: &Value) -> Result<i64, String> {
    let text = key(multiplier);
    let (whole, fraction) = text.split_once('.').unwrap_or((&text, ""));
    let numerator = format!("{whole}{fraction}")
        .parse::<i128>()
        .map_err(|_| "Multiplicador inválido")?;
    let scale = 10_i128
        .checked_pow(fraction.len() as u32)
        .ok_or("Multiplicador fuera de rango")?;
    let gross = i128::from(base)
        .checked_mul(numerator)
        .ok_or("Costo fuera de rango")?;
    if gross <= 0 || gross % scale != 0 {
        return Err("Costo no integral".into());
    }
    i64::try_from(gross / scale).map_err(|_| "Costo fuera de rango".into())
}

fn options(value: &Value) -> &[Value] {
    value.as_array().map(Vec::as_slice).unwrap_or_default()
}

fn has(value: &Value, name: &str) -> bool {
    options(value).iter().any(|item| item == name)
}

fn entry(start: &Value, binding: &Value, selected: &str) -> Result<(Value, i64), String> {
    let settings = &start["settings"];
    let context = &start["context"];
    let lines = native_int(&context["spins"]["lines"])?;
    let line_index = options(&settings["lines"])
        .iter()
        .position(|value| native_int(value) == Ok(lines))
        .ok_or("Líneas no publicadas")?;
    let bets = options(&settings["bets"])
        .iter()
        .map(native_int)
        .collect::<Result<Vec<_>, _>>()?;
    let bet = bets
        .into_iter()
        .min()
        .filter(|bet| *bet > 0)
        .ok_or("Falta apuesta mínima")?;
    let factors = options(&settings["bet_factor"]);
    let factor = if factors.len() == 1 {
        &factors[0]
    } else if factors.len() == options(&settings["lines"]).len() {
        &factors[line_index]
    } else {
        return Err("Factor de líneas no confirmado".into());
    };
    let factor = native_int(factor)?;
    let base = bet
        .checked_mul(factor)
        .filter(|value| *value > 0 && lines > 0)
        .ok_or("Costo base inválido")?;
    let mut params = json!({"bet_per_line": bet, "lines": lines});
    if selected == "normal" {
        return Ok((json!({"name": "spin", "params": params}), base));
    }
    for guard in options(&binding["guards"]) {
        let path = guard["path"]
            .as_str()
            .ok_or("Condición de cliente inválida")?;
        let value = path.split('.').fold(settings, |value, part| &value[part]);
        let valid = match guard["test"].as_str() {
            Some("falsy") => {
                value.is_null()
                    || value == false
                    || value == ""
                    || value.as_f64() == Some(0.0)
                    || value.as_array().is_some_and(Vec::is_empty)
                    || value.as_object().is_some_and(serde_json::Map::is_empty)
            }
            Some("positive") => value
                .as_f64()
                .or_else(|| value.as_str()?.parse().ok())
                .is_some_and(|value| value > 0.0),
            _ => false,
        };
        if !valid {
            return Err("Condición de cliente no confirmada".into());
        }
    }
    let (prefix, id) = selected
        .split_once('-')
        .ok_or("Modalidad 3 Oaks inválida")?;
    let (action, price) = match prefix {
        "buy" => {
            let offered = options(&context["available_buy_bonus"]);
            let mode = offered
                .iter()
                .find(|item| key(item) == id)
                .ok_or("Compra no publicada")?;
            let prices = settings
                .get("buy_bonus_prices")
                .unwrap_or(&settings["freespins_buying_price"]);
            let schema = binding["buy_schema"]
                .as_str()
                .ok_or("Falta serializador de compra verificado")?;
            match schema {
                "flow_numeric_zero_based_no_factor" => {
                    params["selected_mode"] = json!(
                        native_int(mode)?
                            .checked_sub(1)
                            .filter(|index| *index >= 0)
                            .ok_or("Índice de compra inválido")?
                    );
                }
                "direct_numeric"
                | "direct_string"
                | "flow_numeric"
                | "flow_string"
                | "flow_numeric_no_factor" => {
                    params["selected_mode"] = if schema.ends_with("string") {
                        json!(id)
                    } else {
                        json!(native_int(mode)?)
                    };
                    if matches!(schema, "flow_numeric" | "flow_string") {
                        params["bet_factor"] = json!(factor);
                    }
                }
                "flow_scatter_count" if lines == factor => {
                    params["bet_factor"] = json!(factor);
                    params["ante_bet"] = json!(0);
                    params["buy_spin_scatters_count"] = json!(
                        native_int(mode)?
                            .checked_add(3)
                            .ok_or("Índice de compra fuera de rango")?
                    );
                }
                "direct_plain" | "flow_plain" | "flow_plain_no_factor"
                    if offered.len() == 1 && id == "1" =>
                {
                    if schema == "flow_plain" {
                        params["bet_factor"] = json!(factor);
                    }
                }
                "direct_paid_feature" if binding["paid_feature_map"][id].is_string() => {
                    params["paid_feature"] = binding["paid_feature_map"][id].clone();
                }
                _ => return Err("Serializador de compra pendiente".into()),
            }
            ("buy_spin", &prices[id])
        }
        "booster" => {
            let mode = options(&context["available_booster"])
                .iter()
                .find(|item| key(item) == id)
                .ok_or("Booster no publicado")?;
            let price = &settings["booster_prices"][id];
            match binding["booster_schema"].as_str() {
                Some("gr_option") => {
                    params["selected_mode"] = mode.clone();
                    if has(&context["actions"], "booster_spin") {
                        ("booster_spin", price)
                    } else {
                        params["ante_bet"] = price.clone();
                        ("spin", price)
                    }
                }
                Some("ante_only") => {
                    params["ante_bet"] = price.clone();
                    ("spin", price)
                }
                _ => return Err("Serializador de booster pendiente".into()),
            }
        }
        "ante" if binding["booster_schema"] == "ante_only" => {
            let price = options(&settings["ante_bet"])
                .iter()
                .find(|value| key(value).replace('.', "_") == id)
                .ok_or("Antebet no publicado")?;
            if cost(base, price)? <= base {
                return Err("Antebet sin recargo publicado".into());
            }
            params["ante_bet"] = price.clone();
            ("spin", price)
        }
        _ => return Err("Modalidad 3 Oaks pendiente".into()),
    };
    Ok((
        json!({"name": action, "params": params}),
        cost(base, price)?,
    ))
}

fn write(journal: &mut File, event: Value) -> Result<(), String> {
    serde_json::to_writer(&mut *journal, &event).map_err(|error| error.to_string())?;
    journal
        .write_all(b"\n")
        .and_then(|_| journal.sync_data())
        .map_err(|error| error.to_string())
}

fn json_file(path: &Path) -> Result<Value, String> {
    serde_json::from_reader(File::open(path).map_err(|error| error.to_string())?)
        .map_err(|error| error.to_string())
}

pub fn run_case(case: &Value, folder: &Path) -> Result<Value, String> {
    let explicit_root =
        std::env::var_os("EVIDENCIA_NATIVE_CASE_ROOT").map(std::path::PathBuf::from);
    let suite = explicit_root
        .as_deref()
        .or_else(|| folder.ancestors().nth(3))
        .filter(|root| root.is_absolute())
        .ok_or("Ruta de suite 3 Oaks inválida")?;
    let dashboard = suite.join("demo-dashboard");
    let reference = dashboard.join("threeoaks/reference");
    let cooldown = dashboard.join("threeoaks/rate-limit.json");
    if cooldown.exists() {
        let until = json_file(&cooldown)?["until"]
            .as_f64()
            .ok_or("Enfriamiento 3 Oaks inválido")?;
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| "Reloj inválido")?;
        if until > now.as_secs_f64() {
            return Err("Enfriamiento 3 Oaks vigente".into());
        }
    }
    run_with_bindings(
        case,
        &folder.join("threeoaks-native.jsonl"),
        &json_file(&reference.join("serializer-bindings.json"))?,
        &json_file(&reference.join("continuation-bindings.json"))?,
        |path| std::fs::read(dashboard.join(path)).map_err(|error| error.to_string()),
    )
}

pub fn run_with_bindings(
    case: &Value,
    journal_path: &Path,
    serializers: &Value,
    bindings: &Value,
    read_reference: impl FnOnce(&str) -> Result<Vec<u8>, String>,
) -> Result<Value, String> {
    if case["provider"] != "threeoaks" || case["execution_source"] != "native_remote" {
        return Err("Caso ajeno a 3 Oaks".into());
    }
    let game = case["game"]["id"].as_str().ok_or("Falta juego 3 Oaks")?;
    let mode = case["mode"]["spec"]["native_key"]
        .as_str()
        .ok_or("Falta modalidad 3 Oaks")?;
    let mut journal = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(journal_path)
        .map_err(|error| error.to_string())?;
    let demo = open_demo(game)?;
    let source = checked(demo.client.get(&demo.source_url).call(), "source")?
        .into_string()
        .map_err(|_| "Cliente 3 Oaks invalido")?;
    if source.is_empty() || source.trim_start().starts_with('<') {
        return Err("Falta codigo cliente de 3 Oaks".into());
    }
    let hash = format!("{:x}", Sha256::digest(source.as_bytes()));
    let continuation_hash = if game == "lucky_penny_2"
        && hash == "61b0cf0caffc04853790954850d84b8529ab856bcd357a2f6cc712508a4fc2c3"
    {
        let old = "95135fb72b22ea1045080f34e45b59da8f664c96c0c0c25245cfe2b848a60b80";
        let path = bindings[old]["source_file"]
            .as_str()
            .ok_or("Falta cliente anterior verificado")?;
        let bytes = read_reference(path)?;
        if format!("{:x}", Sha256::digest(&bytes)) != old {
            return Err("Cambió el cliente de referencia".into());
        }
        old
    } else {
        &hash
    };
    let continuation = &bindings[continuation_hash];
    if (!continuation.is_null() && continuation["game_id"] != game)
        || (game == "lucky_penny_2" && continuation.is_null())
    {
        return Err("Continuaciones sin vínculo de cliente".into());
    }
    let (mut action, cost) = entry(&demo.start, &serializers[&hash], mode)?;
    let before = native_int(&demo.start["user"]["balance"])?;
    if cost > before
        || !action["name"]
            .as_str()
            .is_some_and(|name| has(&demo.start["context"]["actions"], name))
    {
        return Err("Entrada o fondos FUN no disponibles".into());
    }
    write(
        &mut journal,
        json!({"event": "initialized", "client_sha256": hash, "inventory": demo.report}),
    )?;
    let mut steps = Vec::new();
    for index in 0..=2000 {
        std::thread::sleep(Duration::from_millis(1500));
        write(
            &mut journal,
            json!({"event": "sending", "index": index, "action": action}),
        )?;
        let response = command(
            &demo.client,
            &demo.endpoint,
            "play",
            json!({
                "session_id": demo.session, "action": action, "set_denominator": 1,
                "quick_spin": 0, "sound": false, "autogame": false, "mobile": "0",
                "portrait": false, "fullscreen": false, "viewportSize": "1280x800"
            }),
        )?;
        let state = &response["context"];
        let step = json!({"index": index, "action": action, "state": state["current"],
                          "options_offered": state["actions"], "last_action": state["last_action"],
                          "round_finished": state["round_finished"], "balance": response["user"]["balance"],
                          "total_win": state["spins"]["total_win"]});
        write(&mut journal, json!({"event": "received", "step": step}))?;
        steps.push(step);
        if state["last_action"] != action["name"] {
            return Err("Respuesta de acción no correlacionada".into());
        }
        if state["round_finished"] == true {
            if state["current"] != "spins" || !has(&state["actions"], "spin") {
                return Err("Falta estado terminal de 3 Oaks".into());
            }
            let win = native_int(&state["spins"]["total_win"])?;
            let after = native_int(&response["user"]["balance"])?;
            if win < 0
                || before
                    .checked_sub(cost)
                    .and_then(|value| value.checked_add(win))
                    != Some(after)
            {
                return Err("Saldo final FUN sin conciliar".into());
            }
            let report = json!({"status": "completed", "source": "native_remote", "closed": true,
                "wallet_check": "match", "currency": "FUN", "cost": cost, "win": win,
                "balance_before": before, "balance_after": after,
                "round_phases": {"transport": "http_direct", "endpoint": demo.report["endpoint_template"],
                    "entry_event_index": 0, "accepted_event_index": 0, "closed_event_index": index,
                    "selected_option": mode, "purchase_options": demo.report["purchase_options"],
                    "purchase_prices": demo.report["purchase_prices"], "steps": steps}});
            write(&mut journal, json!({"event": "audit", "report": report}))?;
            return Ok(report);
        }
        let next = options(&state["actions"]);
        let [only] = next else {
            return Err("Decisión 3 Oaks pendiente".into());
        };
        let name = only.as_str().ok_or("Continuación inválida")?;
        if !matches!(
            name,
            "respin"
                | "bonus_init"
                | "bonus_spins_stop"
                | "freespin_init"
                | "freespin"
                | "freespin_stop"
        ) && !has(&continuation["empty_actions"], name)
        {
            return Err("Continuación 3 Oaks sin serializador verificado".into());
        }
        action = json!({"name": name, "params": {}});
    }
    Err("Límite de continuaciones 3 Oaks".into())
}
