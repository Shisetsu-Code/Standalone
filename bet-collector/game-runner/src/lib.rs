use serde::Deserialize;
use serde::de::DeserializeOwned;
use serde_json::{Value, json};
use std::env;
use std::process::ExitCode;
use std::time::Duration;

const USAGE: &str = "game-runner providers\ngame-runner plan|run <proveedor> <juego> [modalidad]\ngame-runner provider-plan|provider-run <proveedor> [1|2]\ngame-runner status <campaña>";

#[derive(Deserialize)]
struct Provider {
    id: String,
    #[serde(default)]
    name: String,
    ready: bool,
    campaign_eligible: Option<bool>,
    campaign_coverage: Option<Value>,
    reason: Option<String>,
    games: Vec<Game>,
}

#[derive(Deserialize)]
struct Game {
    id: String,
    name: String,
    ready: bool,
    block_reason: Option<String>,
    modes: Vec<Mode>,
}

#[derive(Deserialize)]
struct Mode {
    key: String,
    #[serde(rename = "type")]
    kind: String,
    ready: Option<bool>,
    block_reason: Option<String>,
    execution_source: Option<String>,
    requires_prerequisites: Option<bool>,
}

impl Mode {
    fn available(&self) -> bool {
        self.ready != Some(false)
            && self.execution_source.as_deref() != Some("local_model")
            && self.requires_prerequisites != Some(true)
    }
}

struct Api {
    agent: ureq::Agent,
    base: String,
}

impl Api {
    fn new() -> Result<Self, String> {
        let port = env::var("BET_GAME_RUNNER_PORT")
            .unwrap_or_else(|_| "8796".into())
            .parse::<u16>()
            .map_err(|_| "Puerto local inválido")?;
        Ok(Self {
            agent: ureq::AgentBuilder::new()
                .timeout(Duration::from_secs(180))
                .redirects(0)
                .build(),
            base: format!("http://127.0.0.1:{port}/api"),
        })
    }

    fn get<T: DeserializeOwned>(&self, endpoint: &str) -> Result<T, String> {
        decode(self.agent.get(&format!("{}/{endpoint}", self.base)).call())
    }

    fn post(&self, endpoint: &str, token: &str, body: &Value) -> Result<Value, String> {
        decode(
            self.agent
                .post(&format!("{}/{endpoint}", self.base))
                .set("X-Collection-Token", token)
                .send_json(body.clone()),
        )
    }

    fn token(&self) -> Result<String, String> {
        let bootstrap: Value = self.get("bootstrap")?;
        bootstrap["token"]
            .as_str()
            .map(str::to_owned)
            .ok_or("Sesión local inválida".into())
    }
}

fn decode<T: DeserializeOwned>(response: Result<ureq::Response, ureq::Error>) -> Result<T, String> {
    match response {
        Ok(response) => response.into_json().map_err(|error| error.to_string()),
        Err(ureq::Error::Status(status, response)) => {
            let body = response.into_json::<Value>().unwrap_or(Value::Null);
            let message = body["error"]
                .as_str()
                .unwrap_or("Respuesta inesperada del recolector");
            Err(format!("HTTP {status}. {message}"))
        }
        Err(error) => Err(error.to_string()),
    }
}

fn select_mode<'a>(game: &'a Game, key: Option<&str>) -> Result<&'a Mode, String> {
    if let Some(key) = key {
        let mode = game
            .modes
            .iter()
            .find(|mode| mode.key == key)
            .ok_or_else(|| format!("Modalidad desconocida para {}: {key}", game.name))?;
        if !mode.available() {
            return Err(mode.block_reason.clone().unwrap_or_else(|| {
                "La modalidad requiere preparación, está bloqueada o usa un modelo local".into()
            }));
        }
        return Ok(mode);
    }

    let mut normal = game
        .modes
        .iter()
        .filter(|mode| mode.kind == "normal" && mode.available());
    let mode = normal
        .next()
        .ok_or("El juego no tiene una normal de demo ejecutable")?;
    if normal.next().is_some() {
        let keys: Vec<&str> = game
            .modes
            .iter()
            .filter(|m| m.kind == "normal" && m.available())
            .map(|m| m.key.as_str())
            .collect();
        return Err(format!("Indicá una modalidad exacta: {}", keys.join(", ")));
    }
    Ok(mode)
}

fn game_request(
    api: &Api,
    provider_id: &str,
    game_id: &str,
    mode_key: Option<&str>,
    start: bool,
) -> Result<Value, String> {
    let catalog: Vec<Provider> = api.get("catalog")?;
    let provider = catalog
        .iter()
        .find(|provider| provider.id == provider_id)
        .ok_or_else(|| format!("Proveedor desconocido: {provider_id}"))?;
    if !provider.ready {
        return Err(provider
            .reason
            .clone()
            .unwrap_or_else(|| "Proveedor no disponible".into()));
    }
    let game = provider
        .games
        .iter()
        .find(|game| game.id == game_id)
        .ok_or_else(|| format!("Juego desconocido en {provider_id}: {game_id}"))?;
    if !game.ready {
        return Err(game
            .block_reason
            .clone()
            .unwrap_or_else(|| "Juego no disponible".into()));
    }
    let mode = select_mode(game, mode_key)?;
    let body = json!({
        "providers": [{"id": provider.id, "games": [game.id], "mode_key": mode.key, "concurrency": 1}],
        "targets": {(&mode.kind): 1},
        "global_concurrency": 1,
        "include_local_models": false,
        "max_prerequisite_rounds": 0
    });
    let token = api.token()?;
    let preview = api.post("preview", &token, &body)?;
    let selection = json!({"provider": provider.id, "game": game.id, "mode": mode.key});
    if preview["selected_mode"] != selection
        || ["games", "variants", "target_rounds"]
            .iter()
            .any(|key| preview[key].as_u64() != Some(1))
    {
        return Err(
            "El recolector no confirmó una única ronda. Cargá la versión con selección exacta"
                .into(),
        );
    }
    let mut output = json!({"provider": provider.id, "game": game.id, "name": game.name,
        "mode": mode.key, "preview": preview});
    if start {
        output["run"] = api.post("runs", &token, &body)?;
    }
    Ok(output)
}

fn provider_request(
    api: &Api,
    provider: &str,
    concurrency: u8,
    start: bool,
) -> Result<Value, String> {
    let body = json!({
        "providers": [{"id": provider, "games": [], "concurrency": concurrency}],
        "targets": {"normal": 1},
        "global_concurrency": concurrency,
        "skip_held": true,
        "include_local_models": false,
        "max_prerequisite_rounds": 0
    });
    let token = api.token()?;
    let preview = api.post("preview", &token, &body)?;
    if preview["skip_held"] != true {
        return Err("El recolector debe confirmar la exclusión de rondas retenidas".into());
    }
    let mut output = json!({"provider": provider, "preview": preview});
    if start {
        output["run"] = api.post("runs", &token, &body)?;
    }
    Ok(output)
}

fn providers(api: &Api) -> Result<Value, String> {
    let catalog: Vec<Provider> = api.get("catalog")?;
    Ok(Value::Array(
        catalog
            .into_iter()
            .filter(|provider| provider.campaign_eligible.unwrap_or(provider.ready))
            .map(|provider| {
                let normal_games = provider
                    .games
                    .iter()
                    .filter(|game| {
                        game.ready
                            && game
                                .modes
                                .iter()
                                .any(|mode| mode.kind == "normal" && mode.available())
                    })
                    .count();
                json!({"id": provider.id, "name": provider.name, "games": provider.games.len(),
            "campaign_coverage": provider.campaign_coverage,
            "normal_games": normal_games, "ready": provider.ready, "reason": provider.reason})
            })
            .collect(),
    ))
}

fn campaign_status(api: &Api, id: &str) -> Result<Value, String> {
    if id.len() != 32 || !id.bytes().all(|value| value.is_ascii_hexdigit()) {
        return Err("Identificador de campaña inválido".into());
    }
    let state: Value = api.get("state")?;
    let run = state["runs"]
        .as_array()
        .and_then(|runs| runs.iter().find(|run| run["id"] == id))
        .ok_or("Campaña ausente del historial reciente")?;
    let attempts: Vec<Value> = api.get("attempts")?;
    let attempts: Vec<_> = attempts
        .into_iter()
        .filter(|attempt| attempt["run_id"] == id)
        .collect();
    Ok(json!({"active": state["active"] == id, "run": run, "recent_attempts": attempts}))
}

fn command(args: &[String], usage: &str) -> Result<Value, String> {
    let api = Api::new()?;
    match args {
        [action] if action == "providers" => providers(&api),
        [action, provider] if action == "provider-plan" || action == "provider-run" => {
            provider_request(&api, provider, 2, action == "provider-run")
        }
        [action, provider, limit] if action == "provider-plan" || action == "provider-run" => {
            let concurrency = match limit.as_str() {
                "1" => 1,
                "2" => 2,
                _ => return Err("Usá 1 o 2 juegos simultáneos".into()),
            };
            provider_request(&api, provider, concurrency, action == "provider-run")
        }
        [action, provider, game] if action == "plan" || action == "run" => {
            game_request(&api, provider, game, None, action == "run")
        }
        [action, provider, game, mode] if action == "plan" || action == "run" => {
            game_request(&api, provider, game, Some(mode), action == "run")
        }
        [action, id] if action == "status" => campaign_status(&api, id),
        _ => Err(usage.into()),
    }
}

pub fn main(provider: Option<&str>) -> ExitCode {
    let mut args: Vec<_> = env::args().skip(1).collect();
    let usage = match provider {
        Some(id) => format!(
            "{id} plan|run <juego> [modalidad]\n{id} provider-plan|provider-run [1|2]\n{id} status <campaña>"
        ),
        None => USAGE.into(),
    };
    if args.as_slice() == ["--help"] {
        println!("{usage}");
        return ExitCode::SUCCESS;
    }
    if let Some(id) = provider {
        match args.first().map(String::as_str) {
            Some("plan" | "run" | "provider-plan" | "provider-run") => args.insert(1, id.into()),
            Some("status") => {}
            _ => {
                eprintln!("{usage}");
                return ExitCode::FAILURE;
            }
        }
    }
    match command(&args, &usage) {
        Ok(value) => {
            println!(
                "{}",
                serde_json::to_string_pretty(&value).expect("JSON response")
            );
            ExitCode::SUCCESS
        }
        Err(error) => {
            eprintln!("{error}");
            ExitCode::FAILURE
        }
    }
}
pub mod bgaming;
pub mod hacksaw;
pub mod smartsoft;
pub mod threeoaks;
