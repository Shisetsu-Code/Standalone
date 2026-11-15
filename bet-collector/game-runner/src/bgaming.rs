use cookie_store::CookieStore;
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use url::Url;
use uuid::Uuid;

const ORIGIN: &str = "https://demo.bgaming-network.com";

fn trusted(url: &Url) -> bool {
    url.scheme() == "https"
        && url.port().is_none()
        && url.username().is_empty()
        && url.password().is_none()
        && url.host_str().is_some_and(|host| {
            host == "demo.bgaming-network.com" || host.ends_with(".demo.bgaming-network.com")
        })
}

struct Demo {
    client: ureq::Agent,
    cookies: CookieStore,
}

impl Demo {
    fn request(
        &mut self,
        method: &str,
        url: &Url,
        headers: &[(&str, &str)],
        body: Option<Value>,
    ) -> Result<ureq::Response, String> {
        if !trusted(url) {
            return Err("Ruta ajena a la demo oficial de BGaming".into());
        }
        let mut request = self.client.request(method, url.as_str());
        for (key, value) in headers {
            request = request.set(key, value);
        }
        let cookies = self
            .cookies
            .get_request_values(url)
            .map(|(key, value)| format!("{key}={value}"))
            .collect::<Vec<_>>()
            .join("; ");
        if !cookies.is_empty() {
            request = request.set("Cookie", &cookies);
        }
        let response = match body {
            Some(body) => request.send_json(body),
            None => request.call(),
        }
        .map_err(|error| match error {
            ureq::Error::Status(status, _) => format!("BGaming {method} HTTP {status}"),
            ureq::Error::Transport(_) => "Transporte BGaming sin confirmar".into(),
        })?;
        for cookie in response.all("Set-Cookie") {
            let _ = self.cookies.parse(cookie, url);
        }
        Ok(response)
    }

    fn launch(&mut self, mut url: Url) -> Result<(Url, String), String> {
        for _ in 0..5 {
            let response = self.request("GET", &url, &[], None)?;
            match response.status() {
                200 => {
                    return Ok((
                        url,
                        response
                            .into_string()
                            .map_err(|_| "Documento BGaming inválido")?,
                    ));
                }
                301 | 302 | 303 | 307 | 308 => {
                    url = url
                        .join(
                            response
                                .header("Location")
                                .ok_or("Redirección sin destino")?,
                        )
                        .map_err(|_| "Redirección BGaming inválida")?;
                }
                status => return Err(format!("BGaming launcher HTTP {status}")),
            }
        }
        Err("Límite de redirecciones BGaming".into())
    }
}

pub fn inventory(game: &str) -> Result<Value, String> {
    let launch = launch_demo(game)?;
    if launch.page.path() == "/hyperhive" {
        return Ok(open_hyperhive(game, launch)?.report);
    }
    Ok(open_legacy(game, launch)?.report)
}

struct Launch {
    demo: Demo,
    page: Url,
    public_url: String,
    config: Value,
}

struct Session {
    demo: Demo,
    page: Url,
    api: Url,
    csrf: String,
    csrf_value: String,
    series: u128,
    initial: Value,
    report: Value,
}

fn launch_demo(game: &str) -> Result<Launch, String> {
    if game.is_empty()
        || !game
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_')
    {
        return Err("Identidad BGaming inválida".into());
    }
    let mut demo = Demo {
        client: ureq::AgentBuilder::new()
            .try_proxy_from_env(false)
            .redirects(0)
            .user_agent("game-runner/0.1.0")
            .timeout(Duration::from_secs(30))
            .build(),
        cookies: CookieStore::default(),
    };
    let public_url = format!("{ORIGIN}/play/{game}/FUN");
    let (page, html) = demo.launch(Url::parse(&public_url).map_err(|_| "Lanzador inválido")?)?;
    let marker = regex::Regex::new(r"window\.__OPTIONS__\s*=\s*").unwrap();
    let source = marker
        .find(&html)
        .ok_or("Falta configuración del cliente BGaming")?;
    let config = Value::deserialize(&mut serde_json::Deserializer::from_str(
        &html[source.end()..],
    ))
    .map_err(|_| "Configuración BGaming inválida")?;
    if config["currency"] != "FUN" || config["server_id"] != "demo" || config["identifier"] != game
    {
        return Err("El lanzador no confirmó la identidad FUN".into());
    }
    Ok(Launch {
        demo,
        page,
        public_url,
        config,
    })
}

fn open_demo(game: &str) -> Result<Session, String> {
    open_legacy(game, launch_demo(game)?)
}

fn open_legacy(game: &str, launch: Launch) -> Result<Session, String> {
    let Launch {
        mut demo,
        page,
        public_url,
        config,
    } = launch;
    if page.path() == "/hyperhive" {
        return Err("La familia Hyperhive JSON-RPC requiere su inicializador propio".into());
    }
    let api = Url::parse(config["api"].as_str().ok_or("Falta API de demo")?)
        .map_err(|_| "API BGaming inválida")?;
    let csrf = config["csrfTokenHeaderName"]
        .as_str()
        .filter(|name| {
            name.to_ascii_lowercase().starts_with("x-")
                && name
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
        })
        .ok_or("Nombre de encabezado CSRF inválido")?;
    let csrf_value = config["csrfTokenHeaderValue"]
        .as_str()
        .filter(|value| !value.is_empty() && value.bytes().all(|byte| byte.is_ascii_graphic()))
        .ok_or("Encabezado CSRF inválido")?;
    let series = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "Reloj inválido")?
        .as_millis();
    let response = demo.request(
        "POST",
        &api,
        &[
            ("Origin", ORIGIN),
            ("Referer", page.as_str()),
            ("Accept", "application/json"),
            (csrf, csrf_value),
        ],
        Some(json!({"command": "init", "extra_data": {"round_series_id": series}})),
    )?;
    if response.status() != 200 {
        return Err(format!("BGaming init HTTP {}", response.status()));
    }
    let initial: Value = response
        .into_json()
        .map_err(|_| "Respuesta init inválida")?;
    if initial["flow"]["available_actions"].as_array().is_none() {
        return Err("BGaming no confirmó el estado inicial".into());
    }
    let report = json!({
        "provider": "bgaming", "game_id": game, "currency": "FUN", "transport": "http_direct",
        "verified_stage": "native_init", "launch_url": public_url, "version": config["version"],
        "api_host": api.host_str(), "api_version": initial["api_version"],
        "balance": initial["balance"], "flow_state": initial["flow"]["state"],
        "actions": initial["flow"]["available_actions"],
        "line_bets": initial["options"]["line_bets"], "lines": initial["options"]["lines"],
        "valid_bets": initial["options"]["valid_bets"],
        "feature_multipliers": initial["options"]["feature_options"]["feature_multipliers"]
    });
    Ok(Session {
        demo,
        page,
        api,
        csrf: csrf.into(),
        csrf_value: csrf_value.into(),
        series,
        initial,
        report,
    })
}

struct Hyperhive {
    demo: Demo,
    endpoint: Url,
    token: String,
    frontend: String,
    initial: Value,
    report: Value,
}

fn open_hyperhive(game: &str, launch: Launch) -> Result<Hyperhive, String> {
    let Launch {
        mut demo,
        page,
        public_url,
        config,
    } = launch;
    if !page
        .host_str()
        .is_some_and(|host| host.ends_with(".demo.bgaming-network.com"))
    {
        return Err("Origen Hyperhive no confirmado".into());
    }
    let token = config["play_token"]
        .as_str()
        .filter(|token| !token.is_empty())
        .ok_or("Falta sesión Hyperhive")?;
    let origin = page.origin().ascii_serialization();
    let referer = format!("{origin}/");
    let headers = [
        ("Referer", referer.as_str()),
        ("Origin", origin.as_str()),
        ("Accept", "application/json"),
    ];
    let mut frontend_url = page.join("/").map_err(|_| "Frontend Hyperhive inválido")?;
    frontend_url.query_pairs_mut().append_pair("token", token);
    let response = demo.request("GET", &frontend_url, &headers, None)?;
    if response.status() != 200 {
        return Err(format!("Hyperhive frontend HTTP {}", response.status()));
    }
    let frontend = response
        .into_string()
        .map_err(|_| "Frontend Hyperhive inválido")?;
    let cocos = frontend.contains("src/import-map.json") && frontend.contains("System.import");
    let id = Uuid::new_v4().to_string();
    let endpoint = page.join("/api").map_err(|_| "API Hyperhive inválida")?;
    let mut params = json!({"token": token});
    if cocos {
        params["req"] = json!({});
    }
    std::thread::sleep(Duration::from_millis(500));
    let response = demo.request(
        "POST",
        &endpoint,
        &headers,
        Some(json!({"id": id, "jsonrpc": "2.0", "method": "init", "params": params})),
    )?;
    if response.status() != 200 {
        return Err(format!("Hyperhive init HTTP {}", response.status()));
    }
    let envelope: Value = response
        .into_json()
        .map_err(|_| "Respuesta Hyperhive inválida")?;
    let initial = &envelope["result"];
    let attributes = &initial["currency_attributes"];
    if envelope["jsonrpc"] != "2.0"
        || envelope["id"] != id
        || !envelope["error"].is_null()
        || initial["currency"] != "FUN"
        || attributes["code"] != "FUN"
        || attributes["subunits"] != 100
    {
        return Err("Hyperhive no confirmó la inicialización FUN".into());
    }
    let report = json!({
        "provider": "bgaming", "family": "hyperhive", "game_id": game, "currency": "FUN",
        "transport": "http_direct", "verified_stage": "jsonrpc_init", "launch_url": public_url,
        "endpoint": endpoint.as_str(), "rpc_method": "init", "cocos_frontend": cocos,
        "bet_limits": initial["config"]["bet_limits"], "balance": initial["balance"],
        "purchased_features_allowed": initial["config"]["purchased_features"],
        "open_state_present": !initial["state"].is_null()
    });
    Ok(Hyperhive {
        demo,
        endpoint,
        token: token.into(),
        frontend,
        initial: initial.clone(),
        report,
    })
}

fn source_pins(game: &str) -> Option<(&'static str, &'static str)> {
    match game {
        "BookOfHiddenTombs" => Some((
            "259e842f245e3b68352722d61fca2b3244a4f546a528e876fa9bb466899f0fd4",
            "8a8de87f02c2532db2ac0cce920f5dbb96059fd1b77efccf093d874e0157b6e6",
        )),
        "MysteryGarden" => Some((
            "1c486acb50bf2149370bdcd6db3f5816471c6f6f46682e0fc0ba0163eeb303e3",
            "75d0830b5396434867f898734cc6511a07a339e1bc98e0d9cf94f68cc757d116",
        )),
        _ => None,
    }
}

pub fn supports_case(case: &Value) -> bool {
    case["provider"] == "bgaming"
        && case["execution_source"] == "native_remote"
        && matches!(
            (
                case["game"]["game_id"].as_str(),
                case["mode"]["key"].as_str()
            ),
            (
                Some("BookOfHiddenTombs"),
                Some("normal" | "freespin_chance" | "freespin_buy:0" | "freespin_buy:1")
            ) | (Some("MysteryGarden"), Some("normal" | "freespin_buy"))
                | (
                    Some("RedHotChilliChickens"),
                    Some("normal" | "bonus_buy:normal" | "bonus_buy:super")
                )
                | (
                    Some("ChickenFire"),
                    Some(
                        "normal"
                            | "buy_chance"
                            | "buy_bonus"
                            | "buy_super_bonus"
                            | "buy_ultra_bonus"
                    )
                )
        )
}

fn verify_source(
    client: &ureq::Agent,
    game: &str,
    (loader_hash, source_hash): (&str, &str),
) -> Result<(), String> {
    let base = format!("https://cdn.bgaming-network.com/html/{game}/");
    let fetch = |route: &str| -> Result<String, String> {
        let response =
            client
                .get(&format!("{base}{route}"))
                .call()
                .map_err(|error| match error {
                    ureq::Error::Status(status, _) => format!("BGaming source HTTP {status}"),
                    _ => "Fallo de transporte al leer cliente BGaming".into(),
                })?;
        if response.status() != 200 {
            return Err(format!("BGaming source HTTP {}", response.status()));
        }
        response
            .into_string()
            .map_err(|_| "Cliente BGaming inválido".into())
    };
    let loader = fetch("loader.js")?;
    if format!("{:x}", Sha256::digest(loader.as_bytes())) != loader_hash {
        return Err("Cambió el loader BGaming verificado".into());
    }
    let asset_pattern = regex::Regex::new(r"/assets/[A-Za-z0-9_-]+\.js").unwrap();
    let assets: std::collections::BTreeSet<_> = asset_pattern
        .find_iter(&loader)
        .map(|m| m.as_str())
        .collect();
    let route = if assets.len() == 1 {
        assets.first().unwrap().trim_start_matches('/').to_owned()
    } else {
        let pattern = regex::Regex::new(r#"res:[A-Za-z_$][\w$]*="([A-Za-z0-9_.-]+)""#).unwrap();
        let path = pattern
            .captures(&loader)
            .ok_or("Ruta de bundle sin confirmar")?;
        format!("{}/bundle.js", &path[1])
    };
    let source = fetch(&route)?;
    if format!("{:x}", Sha256::digest(source.as_bytes())) != source_hash {
        return Err("Cambió el bundle BGaming verificado".into());
    }
    Ok(())
}

pub fn run_case(case: &Value, path: &Path) -> Result<Value, String> {
    if !supports_case(case) {
        return Err("Caso BGaming fuera del contrato Rust verificado".into());
    }
    let game = case["game"]["game_id"].as_str().ok_or("Falta ID BGaming")?;
    if matches!(game, "RedHotChilliChickens" | "ChickenFire") {
        return run_hyperhive_slot(case, path, game);
    }
    let pins = source_pins(game).ok_or("Faltan hashes BGaming")?;
    let mut journal = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)
        .map_err(|error| error.to_string())?;
    let mut log = |event: Value| -> Result<(), String> {
        serde_json::to_writer(&mut journal, &event).map_err(|error| error.to_string())?;
        journal
            .write_all(b"\n")
            .and_then(|_| journal.sync_data())
            .map_err(|error| error.to_string())
    };
    let mut session = open_demo(game)?;
    verify_source(&session.demo.client, game, pins)?;
    let initial = &session.initial;
    let bets = initial["options"]["available_bets"]
        .as_array()
        .filter(|bets| !bets.is_empty())
        .ok_or("Faltan apuestas BGaming publicadas")?;
    let bet = bets
        .iter()
        .map(|value| {
            value
                .as_i64()
                .filter(|bet| *bet > 0)
                .ok_or("Nivel BGaming inválido")
        })
        .collect::<Result<Vec<_>, _>>()?
        .into_iter()
        .min()
        .ok_or("Falta mínimo BGaming")?;
    let before = initial["balance"]["wallet"]
        .as_i64()
        .filter(|amount| *amount >= bet)
        .ok_or("Saldo FUN insuficiente")?;
    if initial["api_version"] != "2"
        || initial["flow"]["state"] != "ready"
        || initial["flow"]["command"] != "init"
        || !initial["flow"]["round_id"].is_null()
        || initial["flow"]["available_actions"] != json!(["init", "spin"])
        || initial["options"]["currency"]["code"] != "FUN"
        || initial["balance"]["game"] != 0
        || initial["options"]["feature_options"]["feature_multipliers"]["base_bet"] != 10
    {
        return Err("Estado inicial distinto del contrato revisado".into());
    }
    log(
        json!({"event": "initialized", "inventory": session.report, "loader_sha256": pins.0, "source_sha256": pins.1}),
    )?;
    let mode = case["mode"]["key"]
        .as_str()
        .ok_or("Falta modalidad BGaming")?;
    let mut fields = json!({"bet": bet});
    let feature = (mode != "normal").then(|| mode.split_once(':').unwrap_or((mode, "")));
    let cost = if let Some((name, level)) = feature {
        let advertised = &initial["options"]["feature_options"];
        if advertised["disabled_features"]
            .as_array()
            .is_some_and(|items| items.iter().any(|item| item == name))
        {
            return Err("Modalidad deshabilitada por BGaming".into());
        }
        let quote = &advertised["feature_multipliers"][name];
        let multiplier = if level.is_empty() {
            quote
        } else {
            &quote[level]
        };
        let multiplier = multiplier
            .as_i64()
            .filter(|n| *n > 0)
            .ok_or("Precio no publicado")?;
        let numerator = bet.checked_mul(multiplier).ok_or("Costo fuera de rango")?;
        if numerator % 10 != 0 {
            return Err("Costo de modalidad no integral".into());
        }
        fields["purchased_feature"] = json!(name);
        if !level.is_empty() {
            fields["purchased_feature_level"] = json!(level);
        }
        numerator / 10
    } else {
        bet
    };
    let wallet = before
        .checked_sub(cost)
        .filter(|wallet| *wallet >= 0)
        .ok_or("Saldo FUN insuficiente")?;
    let mut steps = Vec::new();
    let mut round_id = Value::Null;
    let mut command = "spin";
    let mut win = 0_i64;
    for index in 0..500 {
        std::thread::sleep(Duration::from_millis(500));
        log(json!({"event": "sending", "index": index, "command": command, "options": fields}))?;
        let mut request =
            json!({"command": command, "extra_data": {"round_series_id": session.series}});
        if index == 0 {
            request["options"] = fields.clone();
        }
        let response = session.demo.request(
            "POST",
            &session.api,
            &[
                ("Origin", ORIGIN),
                ("Referer", session.page.as_str()),
                ("Accept", "application/json"),
                (&session.csrf, &session.csrf_value),
            ],
            Some(request),
        )?;
        if response.status() != 200 {
            return Err(format!("BGaming {command} HTTP {}", response.status()));
        }
        let reply: Value = response
            .into_json()
            .map_err(|_| "Respuesta de ronda BGaming inválida")?;
        let flow = &reply["flow"];
        let round = &flow["round_id"];
        let step = json!({"index": index, "action": command, "state": flow["state"],
            "options_offered": flow["available_actions"], "round_id": round, "balance": reply["balance"],
            "native_win": reply["outcome"]["win"], "confirmed_feature": flow["purchased_feature"]});
        log(json!({"event": "received", "step": step}))?;
        steps.push(step);
        if index == 0 {
            round_id = round.clone();
        }
        if flow["command"] != command
            || !(round.is_string() || round.is_number())
            || round != &round_id
        {
            return Err("Respuesta BGaming no correlacionada; conservar journal".into());
        }
        if index == 0 {
            if let Some((name, level)) = feature {
                let confirmation = &flow["purchased_feature"];
                let confirmed_level = confirmation["level"]
                    .as_str()
                    .map(str::to_owned)
                    .unwrap_or_else(|| confirmation["level"].to_string());
                if confirmation["name"] != name || (!level.is_empty() && confirmed_level != level) {
                    return Err("BGaming no confirmó la modalidad elegida".into());
                }
            }
        }
        if reply["balance"]["wallet"].as_i64() != Some(wallet) {
            return Err("Débito o saldo de continuación BGaming sin conciliar".into());
        }
        let award = reply["outcome"]["win"]
            .as_i64()
            .filter(|win| *win >= 0)
            .ok_or("Falta premio nativo BGaming")?;
        win = win
            .checked_add(award)
            .ok_or("Premio BGaming fuera de rango")?;
        if flow["state"] == "closed" {
            if reply["balance"]["game"].as_i64() != Some(win) {
                return Err("Crédito pendiente BGaming sin conciliar".into());
            }
            let after = wallet
                .checked_add(win)
                .ok_or("Saldo BGaming fuera de rango")?;
            let report = json!({
                "status": "completed", "closed": true, "source": "native_remote", "wallet_check": "match",
                "currency": "FUN", "bet": bet, "cost": cost, "win": win, "round_id": round_id,
                "balance_before": before, "balance_after": after, "wallet_after": wallet, "pending_credit": win,
                "round_phases": {"transport": "http_direct", "entry_event_index": 0, "accepted_event_index": 0,
                    "closed_event_index": index, "selected_option": mode,
                    "feature_multipliers": session.report["feature_multipliers"], "steps": steps}
            });
            log(json!({"event": "audit", "report": report}))?;
            return Ok(report);
        }
        let actions = flow["available_actions"]
            .as_array()
            .ok_or("Faltan continuaciones BGaming")?;
        let available: Vec<_> = actions.iter().filter(|action| *action != "init").collect();
        match available.as_slice() {
            [action] if *action == "freespin" => command = "freespin",
            [action] if *action == "respin" => command = "respin",
            _ => return Err("Elección o continuación BGaming pendiente; conservar journal".into()),
        }
        fields = Value::Null;
    }
    Err("Límite de continuaciones BGaming".into())
}

fn run_hyperhive_slot(case: &Value, path: &Path, game: &str) -> Result<Value, String> {
    let chicken = game == "ChickenFire";
    let (route, source_hash) = if chicken {
        (
            "/assets/index-CoAzB5sA.js",
            "3447e6d2577faf09770c691dff91c15e10106981158b523080c99ac887c2ca33",
        )
    } else {
        (
            "/main.js",
            "28652da884003877001e520669c43ca36dabf882c1e05a0df0812035c61c5602",
        )
    };
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)
        .map_err(|error| error.to_string())?;
    let mut log = |entry: Value| -> Result<(), String> {
        serde_json::to_writer(&mut file, &entry).map_err(|error| error.to_string())?;
        file.write_all(b"\n")
            .and_then(|_| file.sync_data())
            .map_err(|error| error.to_string())
    };
    let mut session = open_hyperhive(game, launch_demo(game)?)?;
    let origin = session.endpoint.origin().ascii_serialization();
    let referer = format!("{origin}/");
    let headers = [
        ("Origin", origin.as_str()),
        ("Referer", referer.as_str()),
        ("Accept", "application/json"),
    ];
    let script = regex::Regex::new(&format!(
        r#"<script[^>]+src=["'](?:\./|/)?{}(?:\?[^"']*)?["']"#,
        regex::escape(route.trim_start_matches('/'))
    ))
    .map_err(|_| "Ruta de cliente inválida")?;
    if !script.is_match(&session.frontend) {
        return Err("Cambió el script elegido por el cliente".into());
    }
    let url = session
        .endpoint
        .join(route)
        .map_err(|_| "Ruta cliente inválida")?;
    let source = session.demo.request("GET", &url, &headers, None)?;
    if source.status() != 200 {
        return Err(format!("Hyperhive source HTTP {}", source.status()));
    }
    let source = source
        .into_string()
        .map_err(|_| "Cliente Hyperhive inválido")?;
    if format!("{:x}", Sha256::digest(source.as_bytes())) != source_hash {
        return Err("Cambió el hash del cliente Hyperhive".into());
    }
    let initial = &session.initial;
    if !initial["state"].is_null()
        || initial["final"] == false
        || initial["freebets"]
            .as_array()
            .is_some_and(|items| !items.is_empty())
        || initial["freebets"]
            .as_object()
            .is_some_and(|items| !items.is_empty())
        || initial["currency_attributes"]["exponent"] != 2
    {
        return Err("La sesión Hyperhive no está libre para una ronda nueva".into());
    }
    let bet = initial["config"]["bet_limits"]
        .as_array()
        .ok_or("Faltan límites nativos")?
        .iter()
        .map(|value| {
            value
                .as_i64()
                .filter(|n| *n > 0)
                .ok_or("Límite nativo inválido")
        })
        .collect::<Result<Vec<_>, _>>()?
        .into_iter()
        .min()
        .ok_or("Falta importe mínimo")?;
    let before = initial["balance"].as_i64().ok_or("Falta saldo FUN")?;
    let mode = case["mode"]["key"].as_str().ok_or("Falta modalidad")?;
    let bet_type = if chicken { "bet" } else { "betting" };
    let mut request = json!({"bet": bet, "bet_type": bet_type});
    let allowed = |feature: &str| {
        initial["config"]["purchased_features"]
            .as_array()
            .is_some_and(|items| items.iter().any(|item| item == feature))
    };
    let products: &[(&str, &str, i64, i64)] = if chicken {
        &[
            ("buy_chance", "buy_chance", 3, 2),
            ("buy_bonus", "buy_bonus", 60, 1),
            ("buy_super_bonus", "buy_bonus", 90, 1),
            ("buy_ultra_bonus", "buy_bonus", 120, 1),
        ]
    } else {
        &[
            ("bonus_buy:normal", "bonus_buy", 100, 1),
            ("bonus_buy:super", "bonus_buy", 200, 1),
        ]
    };
    let offered = products
        .iter()
        .filter(|(_, feature, _, _)| allowed(feature))
        .collect::<Vec<_>>();
    let cost = if mode == "normal" {
        if !chicken {
            request["action"] = json!("spin");
        }
        bet
    } else {
        let (_, feature, numerator, denominator) = **offered
            .iter()
            .find(|(key, _, _, _)| *key == mode)
            .ok_or("Modalidad Hyperhive no ofrecida")?;
        request["purchased_feature"] = json!(feature);
        if chicken && feature == "buy_bonus" {
            request["feature_id"] = json!(mode);
        }
        if !chicken {
            request["isSuperBonus"] = json!(mode.ends_with(":super"));
        }
        bet.checked_mul(numerator)
            .filter(|amount| amount % denominator == 0)
            .map(|amount| amount / denominator)
            .ok_or("Costo nativo inválido")?
    };
    if cost > before {
        return Err("Saldo FUN insuficiente".into());
    }
    let offers = offered.iter().map(|(key, _, numerator, denominator)|
        json!({"key": key, "multiplier_ratio": [numerator, denominator]})).collect::<Vec<_>>();
    let mut lock = initial["state_lock"].as_str().unwrap_or("").to_owned();
    let mut steps = Vec::new();
    let mut round_id = Value::Null;
    let mut stages = 0;
    let mut opening_win = 0;
    let mut last_balance = before - cost;
    log(
        json!({"event": "initialized", "inventory": session.report, "source_sha256": source_hash,
               "purchase_offers": offers}),
    )?;
    for index in 0..if chicken { 500 } else { 2 } {
        let id = Uuid::new_v4().to_string();
        std::thread::sleep(Duration::from_millis(500));
        log(json!({"event": "sending", "index": index, "method": "play", "request": request}))?;
        let response = session.demo.request(
            "POST",
            &session.endpoint,
            &headers,
            Some(json!({
                "id": id, "jsonrpc": "2.0", "method": "play",
                "params": {"token": session.token, "state_lock": lock, "req": request}
            })),
        )?;
        if response.status() != 200 {
            return Err(format!("Hyperhive play HTTP {}", response.status()));
        }
        let envelope: Value = response
            .into_json()
            .map_err(|_| "Respuesta Hyperhive inválida")?;
        if envelope["id"] != id || envelope["jsonrpc"] != "2.0" || !envelope["error"].is_null() {
            return Err("Respuesta Hyperhive sin correlación".into());
        }
        let result = &envelope["result"];
        let final_flag = result["final"]
            .as_bool()
            .ok_or("Falta fase final Hyperhive")?;
        let win_field = if chicken {
            &result["resp"]["totalWin"]
        } else if index == 0 {
            &result["resp"]["game"]["spin"]["totalWin"]
        } else {
            &result["resp"]["game"]["totalWin"]
        };
        let step = json!({"index": index, "request": request, "final": final_flag,
                         "balance": result["balance"], "next_action": result["resp"]["nextAction"],
                         "native_win": win_field});
        log(json!({"event": "received", "step": step}))?;
        steps.push(step);
        if index == 0 {
            round_id = result["round"].clone();
            if chicken {
                opening_win =
                    integral_award(win_field).ok_or("Falta premio inicial Chicken Fire")?;
                let resp = &result["resp"];
                stages = resp["data"]
                    .as_array()
                    .filter(|data| {
                        !data.is_empty()
                            && data.len() < 500
                            && data
                                .iter()
                                .all(|stage| stage["respinsCount"].as_u64().is_some())
                    })
                    .ok_or("Etapas Chicken Fire no confirmadas")?
                    .len();
                if resp["baseBet"] != bet || resp["stageIndex"] != 0 {
                    return Err("Selector o etapa inicial Chicken Fire no confirmados".into());
                }
                log(
                    json!({"event": "opening_award", "stages": stages, "native_win": opening_win}),
                )?;
            }
        }
        if result["round"] != round_id {
            return Err("Cambió la identidad Hyperhive".into());
        }
        if chicken {
            let balance = result["balance"]
                .as_i64()
                .ok_or("Saldo Chicken Fire inválido")?;
            let ceiling = (before - cost)
                .checked_add(opening_win)
                .ok_or("Saldo fuera de rango")?;
            if balance < last_balance || balance > ceiling {
                return Err("Saldo de etapa Chicken Fire fuera del intervalo conciliable".into());
            }
            last_balance = balance;
        }
        if final_flag {
            let win = if chicken {
                opening_win
            } else {
                integral_award(win_field).ok_or("Premio nativo fuera del formato verificado")?
            };
            let after = result["balance"].as_i64().ok_or("Saldo final inválido")?;
            if before
                .checked_sub(cost)
                .and_then(|base| base.checked_add(win))
                != Some(after)
            {
                return Err("Saldo Hyperhive sin conciliar".into());
            }
            let report = json!({"status": "completed", "source": "native_remote", "closed": true,
                "wallet_check": "match", "currency": "FUN", "bet": bet, "cost": cost, "win": win,
                "balance_before": before, "balance_after": after,
                "round_phases": {"transport": "http_direct", "endpoint": session.endpoint.as_str(),
                    "entry_event_index": 0, "accepted_event_index": 0, "closed_event_index": index,
                    "options_offered": offers, "selected_option": mode, "steps": steps}});
            log(json!({"event": "audit", "report": report}))?;
            return Ok(report);
        }
        if chicken && index >= stages {
            return Err("Etapas Chicken Fire agotadas sin cierre".into());
        }
        if !chicken
            && (index != 0
                || result["resp"]["nextAction"] != "BONUS"
                || result["balance"].as_i64() != before.checked_sub(cost))
        {
            return Err("Fase o débito Hyperhive sin confirmar; conservar journal".into());
        }
        lock = result["state_lock"]
            .as_str()
            .filter(|value| !value.is_empty())
            .ok_or("Falta continuidad Hyperhive")?
            .into();
        request = if chicken {
            json!({"bet": bet, "bet_type": bet_type})
        } else {
            json!({"bet": bet, "bet_type": bet_type, "action": "bonus"})
        };
    }
    Err("Ronda Hyperhive pendiente".into())
}

fn integral_award(value: &Value) -> Option<i64> {
    let number = value.as_number()?;
    if let Some(amount) = number.as_i64() {
        return (amount >= 0).then_some(amount);
    }
    let text = number.to_string();
    let (whole, fraction) = text.split_once('.')?;
    if fraction.is_empty() || !fraction.bytes().all(|byte| byte == b'0') {
        return None;
    }
    whole.parse::<i64>().ok().filter(|amount| *amount >= 0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hyperhive_integral_awards_accept_decimal_notation_without_rounding() {
        assert_eq!(integral_award(&json!(1238.0)), Some(1238));
        assert_eq!(integral_award(&json!(4114)), Some(4114));
        assert_eq!(integral_award(&json!(1.25)), None);
        assert_eq!(integral_award(&json!("1238.0")), None);
    }
}
