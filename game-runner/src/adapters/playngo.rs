//! Public practice=1/demo=2 Play'n GO transport and conservative normal-round rules.
use crate::{
    context::{NativeSocket, RunContext, SocketPayload},
    model::{Game, Mode, ModeKind, RoundOutcome, now_ms, sha256},
};
use anyhow::{Context, Result, bail, ensure};
use regex::Regex;
use rust_decimal::{Decimal, prelude::ToPrimitive};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::LazyLock,
};
use url::Url;

const RELEASED: &str = "https://released.playngonetwork.com";
const SERVER: &str = "https://ascflyp.playngonetwork.com/";

static BINDINGS: LazyLock<BTreeMap<String, Value>> = LazyLock::new(|| {
    serde_json::from_slice(include_bytes!("../../bindings/playngo.json"))
        .expect("compiled Play'n GO bindings")
});

pub fn embedded_settings(game: &Game) -> Result<Value> {
    BINDINGS
        .get(&game.id)
        .cloned()
        .context("Play'n GO game has no reviewed embedded binding")
}

pub fn supports(game: &Game, mode: &Mode) -> bool {
    matches!(
        (mode.kind, mode.key.as_str()),
        (ModeKind::Normal, "normal") | (ModeKind::Booster, "go-ultra")
    ) && BINDINGS
        .get(&game.id)
        .and_then(|settings| settings["modes"].as_array())
        .is_some_and(|modes| modes.iter().any(|key| key == mode.key.as_str()))
}

pub fn validate(game: &Game, mode: &Mode, settings: &Value) -> Result<()> {
    ensure!(
        supports(game, mode),
        "Play'n GO mode has no reviewed binding"
    );
    ensure!(
        !game.id.is_empty() && game.id.bytes().all(|b| b.is_ascii_digit()),
        "invalid native game identity"
    );
    let gid = settings["gid"]
        .as_str()
        .context("Play'n GO requires a public catalogue GID")?;
    ensure!(
        !gid.is_empty()
            && gid
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit()),
        "invalid public GID"
    );
    let hash = settings["source_sha256"]
        .as_str()
        .context("Play'n GO requires a reviewed public client hash")?;
    ensure!(
        hash.len() == 64 && hash.bytes().all(|b| b.is_ascii_hexdigit()),
        "invalid reviewed source hash"
    );
    Ok(())
}

fn query(path: &str, values: &[(&str, &str)]) -> Result<String> {
    let mut url = Url::parse(&format!("{RELEASED}{path}"))?;
    url.query_pairs_mut().extend_pairs(values.iter().copied());
    Ok(url.to_string())
}
async fn get(ctx: &RunContext, label: &str, url: &str) -> Result<String> {
    let response = ctx.get(label, url).await?;
    ensure!(response.status == 200, "Play'n GO HTTP failure at {label}");
    Ok(response.body)
}
fn packet(number: &mut u64, session: &str, command: &str) -> Result<String> {
    ensure!(
        !session.is_empty()
            && session
                .chars()
                .all(|c| !c.is_control() && !c.is_whitespace()),
        "invalid native session identity"
    );
    ensure!(
        !command.contains(['\r', '\n']),
        "native command contains line separator"
    );
    let text = format!("d={}\r\n{session}\r\n{command}\r\n", *number);
    *number = number
        .checked_add(1)
        .context("native packet counter overflow")?;
    Ok(text)
}
async fn post(
    ctx: &RunContext,
    number: &mut u64,
    session: &str,
    command: &str,
    label: &str,
) -> Result<Vec<Command>> {
    let body = packet(number, session, command)?;
    let response = ctx
        .http(
            label,
            "POST",
            SERVER,
            BTreeMap::from([
                ("content-type".into(), "text/plain".into()),
                ("origin".into(), RELEASED.into()),
            ]),
            body,
            false,
        )
        .await?;
    ensure!(response.status == 200, "Play'n GO command HTTP failure");
    let parsed = commands(&response.body)?;
    ensure!(
        !parsed.iter().any(|x| matches!(x.code, 110 | 111)),
        "Play'n GO rejected bootstrap"
    );
    Ok(parsed)
}
fn decode_handshake(payload: &SocketPayload) -> Result<Vec<Value>> {
    let text = match payload {
        SocketPayload::Text(text) => text.as_str(),
        SocketPayload::Binary(bytes) => {
            std::str::from_utf8(bytes).context("invalid SignalR handshake UTF-8")?
        }
    };
    let body = text
        .strip_suffix('\u{1e}')
        .context("missing SignalR handshake terminator")?;
    let value: Value = serde_json::from_str(body)?;
    ensure!(value == json!({}), "SignalR handshake not accepted");
    Ok(vec![value])
}
fn decode_commands(payload: &SocketPayload) -> Result<Vec<Value>> {
    let SocketPayload::Binary(bytes) = payload else {
        bail!("unexpected text frame after SignalR handshake")
    };
    let mut parsed = Vec::new();
    for value in decode_frames(bytes)? {
        let frame = value
            .as_array()
            .context("SignalR message is not an array")?;
        match frame.first().and_then(Value::as_u64) {
            Some(6) => ensure!(frame.len() == 1, "invalid SignalR heartbeat"),
            Some(7) => bail!("native SignalR transport closed"),
            Some(1) => {
                ensure!(
                    frame.len() >= 5 && frame[1].is_object() && frame[3] == "Commands",
                    "unrecognized SignalR invocation"
                );
                let args = frame[4]
                    .as_array()
                    .context("native invocation arguments missing")?;
                ensure!(args.len() == 1, "ambiguous native command payload");
                parsed.extend(commands(
                    args[0]
                        .as_str()
                        .context("native command payload is not text")?,
                )?);
            }
            _ => bail!("unreviewed SignalR message type"),
        }
    }
    if parsed.is_empty() {
        Ok(vec![])
    } else {
        Ok(vec![serde_json::to_value(parsed)?])
    }
}
async fn send(
    ctx: &RunContext,
    socket: &mut NativeSocket,
    number: &mut u64,
    session: &str,
    command: &str,
    label: &str,
    financial: bool,
) -> Result<Vec<Command>> {
    let body = packet(number, session, command)?;
    let payload = encode_frame(&json!([1, {}, null, "ProcessPacket", [body], []]))?;
    let value = ctx
        .ws_codec(
            socket,
            label,
            SocketPayload::Binary(payload),
            financial,
            None,
            decode_commands,
        )
        .await?;
    let parsed: Vec<Command> = serde_json::from_value(value)?;
    ensure!(
        !parsed.iter().any(|x| matches!(x.code, 110 | 111)),
        "Play'n GO rejected native command"
    );
    for item in &parsed {
        if item.code == 103 {
            ensure!(
                item.args.as_slice() == [session],
                "native session owner changed"
            );
        }
    }
    Ok(parsed)
}
fn public_source_url(configuration: &Value, gid: &str) -> Result<String> {
    let root = configuration["resourceRoot"]
        .as_str()
        .context("public resource root missing")?;
    let root_url = Url::parse(root)?;
    ensure!(
        root_url.scheme() == "https"
            && root_url.host_str() == Some("cdn.playngonetwork.com")
            && root_url.username().is_empty()
            && root_url.password().is_none()
            && root_url.port().is_none()
            && root_url.query().is_none()
            && root_url.fragment().is_none(),
        "unverified public CDN root"
    );
    let game = configuration["gameURL"]
        .as_str()
        .context("published game URL missing")?;
    let game_url = root_url.join(game)?;
    ensure!(
        game_url.origin() == root_url.origin(),
        "game URL left the public CDN"
    );
    let parts = game_url.path().split('/').collect::<Vec<_>>();
    let asset = parts
        .get(parts.len().saturating_sub(2))
        .copied()
        .unwrap_or(gid);
    ensure!(
        !asset.is_empty()
            && asset
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit()),
        "unreviewed public asset identity"
    );
    Ok(format!(
        "{}/games/{asset}/{asset}_desktop.bundle.js",
        root.trim_end_matches('/')
    ))
}
fn settle(before: u64, cost: u64, last: &[Command], all: &[Command]) -> Result<(u64, u64)> {
    let wallet = latest(last, 52).context("final native wallet missing")?;
    ensure!(
        wallet.len() >= 2 && wallet[1] == "0",
        "native round wallet not idle"
    );
    let end = latest(all, 3).context("native payout missing")?;
    ensure!(
        end.len() >= 4 && native(&end[3])? == 0,
        "native free-spin round remains open"
    );
    let win = native(&end[2])?;
    let after = native(&wallet[0])?;
    ensure!(
        cost > 0 && before.checked_sub(cost).and_then(|n| n.checked_add(win)) == Some(after),
        "native payout/wallet mismatch"
    );
    Ok((win, after))
}

pub async fn execute(
    ctx: &RunContext,
    game: &Game,
    mode: &Mode,
    settings: &Value,
) -> Result<RoundOutcome> {
    validate(game, mode, settings)?;
    let gid = settings["gid"].as_str().unwrap();
    let launch = get(
        ctx,
        "launcher",
        &query(
            "/casino/ContainerLauncher",
            &[
                ("pid", "2"),
                ("gid", gid),
                ("lang", "en_GB"),
                ("practice", "1"),
                ("channel", "desktop"),
                ("demo", "2"),
            ],
        )?,
    )
    .await?;
    ensure!(
        launch.contains("practice"),
        "unrecognized public practice launcher"
    );
    let groups = Regex::new(r"productGroup:\s*(\d+)")?;
    let group = groups.captures(&launch).context("product group missing")?;
    ensure!(
        group.get(1).unwrap().as_str() == "2",
        "unexpected public product group"
    );
    let info: Value = serde_json::from_str(
        &get(
            ctx,
            "game_identity",
            &format!("{RELEASED}/games/getgamebygid/{gid}"),
        )
        .await?,
    )?;
    let game_id = info["gameId"]
        .as_str()
        .map(str::to_owned)
        .unwrap_or_else(|| info["gameId"].to_string());
    ensure!(
        game_id == game.id,
        "public GID/native game identity mismatch"
    );
    let pre: Value = serde_json::from_str(
        &get(
            ctx,
            "prelaunch",
            &query(
                "/configuration/prelaunchconfiguration",
                &[
                    ("gameId", &game.id),
                    ("language", "en_GB"),
                    ("productGroup", "2"),
                    ("practice", "1"),
                    ("channel", "desktop"),
                ],
            )?,
        )
        .await?,
    )?;
    ensure!(pre["Server"] == SERVER, "unverified public practice server");
    let mut number = 1u64;
    let ua = url::form_urlencoded::byte_serialize(ctx.user_agent().as_bytes()).collect::<String>();
    let first = post(
        ctx,
        &mut number,
        "0",
        &format!(
            "103 12 \"en_GB\" {} \"{ua}\" \"{gid}\" \"desktop\"",
            game.id
        ),
        "new_demo_session",
    )
    .await?;
    let first_session = latest(&first, 103)
        .and_then(|a| a.first())
        .filter(|s| !s.is_empty())
        .context("fresh demo session missing")?;
    let login = post(
        ctx,
        &mut number,
        first_session,
        "101 \"\" \"\" \"\" \"\" \"\" \"\"",
        "demo_login",
    )
    .await?;
    let auth = latest(&login, 101).context("DEMO login missing")?;
    ensure!(
        auth.len() >= 2 && native(&auth[0])? > 0 && auth[1] == "DEMO",
        "native DEMO login not confirmed"
    );
    let session = latest(&login, 103)
        .and_then(|a| a.first())
        .unwrap_or(first_session);
    ensure!(
        !session.is_empty() && session != "[REDACTED]",
        "fresh session owner missing"
    );
    ctx.save_session(&json!({"provider":"playngo","game":game.id,"gid":gid,"session_id":session,"server":SERVER,"practice":1,"demo":2,"currency":"DEMO"}))?;
    let jurisdiction = auth.get(3).map(String::as_str).unwrap_or("GB");
    let now = now_ms().to_string();
    let configuration: Value = serde_json::from_str(
        &get(
            ctx,
            "configuration",
            &query(
                "/configuration/v2",
                &[
                    ("pid", "2"),
                    ("gameid", &game.id),
                    ("lang", "en_GB"),
                    ("practice", "1"),
                    ("channel", "desktop"),
                    ("jurisdiction", jurisdiction),
                    ("platform", "megaton"),
                    ("currency", "DEMO"),
                    ("_r", &now),
                ],
            )?,
        )
        .await?,
    )?;
    let source_url = public_source_url(&configuration, gid)?;
    let source = get(ctx, "public_client", &source_url).await?;
    let source_hash = sha256(source.as_bytes());
    ensure!(
        source.contains("desktop_Entry")
            && settings["source_sha256"]
                .as_str()
                .is_some_and(|s| s.eq_ignore_ascii_case(&source_hash)),
        "reviewed public client changed; no bet sent"
    );
    let raw = configuration["settings"]
        .as_str()
        .context("public native settings missing")?;
    let raw = raw.strip_prefix("&settings=").unwrap_or(raw);
    ensure!(
        !raw.chars().any(|c| c.is_whitespace() || c == '"'),
        "unreviewed settings encoding"
    );
    let xml = percent_decode(raw, true)?;
    let mut socket = ctx
        .websocket(
            "wss://ascflyp.playngonetwork.com//gamehub",
            RELEASED,
            None,
            BTreeMap::new(),
        )
        .await?;
    ctx.ws_codec(
        &mut socket,
        "signalr_handshake",
        SocketPayload::Text("{\"protocol\":\"messagepack\",\"version\":2}\u{1e}".into()),
        false,
        None,
        decode_handshake,
    )
    .await?;
    let initial = send(
        ctx,
        &mut socket,
        &mut number,
        session,
        &format!("104 {} 0 %22{raw}%22", game.id),
        "initialize",
        false,
    )
    .await?;
    ensure!(
        latest(&initial, 104) == Some(&["1".to_string()][..]) && latest(&initial, 109).is_some(),
        "native game initialization incomplete"
    );
    let wallet = latest(&initial, 52).context("initial wallet missing")?;
    ensure!(
        wallet.len() >= 2 && wallet[1] == "0",
        "fresh demo wallet is not idle"
    );
    let before = native(&wallet[0])?;
    let mut p = profile(&source, &initial, &xml, &configuration)?;
    if mode.kind == ModeKind::Booster {
        apply_ultra(&source, &initial, &mut p)?;
    }
    ensure!(before >= p.cost, "insufficient fictional demo balance");
    let mut response = send(
        ctx,
        &mut socket,
        &mut number,
        session,
        &format!("1 {} {} {} 1", p.coins, p.lines, p.denomination),
        mode.key.as_str(),
        true,
    )
    .await?;
    let mut all = response.clone();
    let mut steps = vec![json!({"action":mode.key,"responses":response})];
    let mut processed_free = 0u64;
    for _ in 1..ctx.max_steps() {
        let Some(action) = continuation(&response, processed_free)? else {
            break;
        };
        response = send(
            ctx,
            &mut socket,
            &mut number,
            session,
            &action,
            "continuation",
            true,
        )
        .await?;
        if action.starts_with("7 ") {
            processed_free = processed_free
                .checked_add(1)
                .context("free-spin counter overflow")?;
        }
        all.extend(response.clone());
        steps.push(json!({"action":action,"responses":response}));
    }
    let (win, after) = settle(before, p.cost, &response, &all)?;
    Ok(RoundOutcome {
        native_round_id: None,
        currency: "DEMO".into(),
        monetary_unit: "native".into(),
        currency_source: "native_response".into(),
        balance_before: before.to_string(),
        balance_after: after.to_string(),
        cost: p.cost.to_string(),
        payout: win.to_string(),
        native_closed: true,
        checks: BTreeMap::from([
            ("fresh_public_DEMO_session".into(), true),
            ("reviewed_client".into(), true),
            ("native_entry_and_continuations".into(), true),
        ]),
        native_data: json!({"currency_denominator":p.scale,"source_sha256":source_hash,"source_url":source_url,"profile":{"coins":p.coins,"lines":p.lines,"denomination":p.denomination},"initial":initial,"steps":steps}),
    })
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
struct Command {
    code: u64,
    args: Vec<String>,
}

fn percent_decode(text: &str, plus: bool) -> Result<String> {
    let mut out = Vec::new();
    let bytes = text.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' {
            ensure!(i + 2 < bytes.len(), "invalid native percent escape");
            let a = (bytes[i + 1] as char)
                .to_digit(16)
                .context("invalid native percent escape")?;
            let b = (bytes[i + 2] as char)
                .to_digit(16)
                .context("invalid native percent escape")?;
            out.push((a * 16 + b) as u8);
            i += 3;
        } else {
            out.push(if plus && bytes[i] == b'+' {
                b' '
            } else {
                bytes[i]
            });
            i += 1;
        }
    }
    String::from_utf8(out).context("native string is not UTF-8")
}

fn commands(text: &str) -> Result<Vec<Command>> {
    let mut out = Vec::new();
    for line in text.strip_prefix("d=").unwrap_or(text).lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let mut chars = line.chars().peekable();
        let mut code = String::new();
        while chars.peek().is_some_and(char::is_ascii_digit) {
            code.push(chars.next().unwrap());
        }
        ensure!(
            !code.is_empty() && chars.peek().is_none_or(|c| c.is_whitespace()),
            "unrecognized native command"
        );
        let mut args = Vec::new();
        loop {
            while chars.peek().is_some_and(|c| c.is_whitespace()) {
                chars.next();
            }
            let Some(first) = chars.next() else { break };
            let mut token = String::new();
            if first == '"' {
                let mut closed = false;
                while let Some(c) = chars.next() {
                    if c == '"' {
                        closed = true;
                        break;
                    }
                    if c == '\\' {
                        let escaped = chars.next().context("unterminated native escape")?;
                        if escaped != '"' {
                            token.push('\\');
                        }
                        token.push(escaped);
                    } else {
                        token.push(c);
                    }
                }
                ensure!(
                    closed && chars.peek().is_none_or(|c| c.is_whitespace()),
                    "unterminated or malformed native quoted argument"
                );
            } else {
                token.push(first);
                while chars.peek().is_some_and(|c| !c.is_whitespace()) {
                    token.push(chars.next().unwrap());
                }
            }
            args.push(percent_decode(&token, false)?);
        }
        out.push(Command {
            code: code.parse()?,
            args,
        });
    }
    Ok(out)
}

const MAX_MESSAGE: usize = 16 * 1024 * 1024;
fn pack(value: &Value, out: &mut Vec<u8>, depth: usize) -> Result<()> {
    ensure!(
        depth < 32 && out.len() <= MAX_MESSAGE,
        "MessagePack limit exceeded"
    );
    match value {
        Value::Null => out.push(0xc0),
        Value::Bool(false) => out.push(0xc2),
        Value::Bool(true) => out.push(0xc3),
        Value::Number(n) => {
            if let Some(n) = n.as_u64() {
                if n < 128 {
                    out.push(n as u8);
                } else if n <= u8::MAX as u64 {
                    out.extend([0xcc, n as u8]);
                } else if n <= u16::MAX as u64 {
                    out.push(0xcd);
                    out.extend((n as u16).to_be_bytes());
                } else if n <= u32::MAX as u64 {
                    out.push(0xce);
                    out.extend((n as u32).to_be_bytes());
                } else {
                    out.push(0xcf);
                    out.extend(n.to_be_bytes());
                }
            } else {
                let n = n
                    .as_i64()
                    .context("MessagePack command number must be integral")?;
                if n >= -32 {
                    out.push(n as i8 as u8);
                } else {
                    out.push(0xd3);
                    out.extend(n.to_be_bytes());
                }
            }
        }
        Value::String(s) => {
            ensure!(s.len() <= MAX_MESSAGE, "MessagePack string too long");
            if s.len() < 32 {
                out.push(0xa0 | s.len() as u8);
            } else if s.len() <= 255 {
                out.extend([0xd9, s.len() as u8]);
            } else if s.len() <= 65535 {
                out.push(0xda);
                out.extend((s.len() as u16).to_be_bytes());
            } else {
                out.push(0xdb);
                out.extend((s.len() as u32).to_be_bytes());
            }
            out.extend_from_slice(s.as_bytes());
        }
        Value::Array(values) => {
            ensure!(values.len() <= 65535, "MessagePack array too long");
            if values.len() < 16 {
                out.push(0x90 | values.len() as u8);
            } else {
                out.push(0xdc);
                out.extend((values.len() as u16).to_be_bytes());
            }
            for value in values {
                pack(value, out, depth + 1)?;
            }
        }
        Value::Object(values) => {
            ensure!(values.len() <= 65535, "MessagePack map too long");
            if values.len() < 16 {
                out.push(0x80 | values.len() as u8);
            } else {
                out.push(0xde);
                out.extend((values.len() as u16).to_be_bytes());
            }
            for (key, value) in values {
                pack(&Value::String(key.clone()), out, depth + 1)?;
                pack(value, out, depth + 1)?;
            }
        }
    }
    ensure!(out.len() <= MAX_MESSAGE, "MessagePack payload too long");
    Ok(())
}

fn encode_frame(value: &Value) -> Result<Vec<u8>> {
    let mut data = Vec::new();
    pack(value, &mut data, 0)?;
    let mut size = data.len();
    let mut out = Vec::new();
    while size >= 128 {
        out.push(((size & 127) | 128) as u8);
        size >>= 7;
    }
    out.push(size as u8);
    out.extend(data);
    Ok(out)
}

struct Decoder<'a> {
    bytes: &'a [u8],
    at: usize,
}
impl Decoder<'_> {
    fn take(&mut self, n: usize) -> Result<&[u8]> {
        ensure!(
            n <= self.bytes.len().saturating_sub(self.at),
            "truncated MessagePack value"
        );
        let start = self.at;
        self.at += n;
        Ok(&self.bytes[start..self.at])
    }
    fn unsigned(&mut self, n: usize) -> Result<u64> {
        let mut value = 0u64;
        for byte in self.take(n)? {
            value = (value << 8) | u64::from(*byte);
        }
        Ok(value)
    }
    fn string(&mut self, len: usize) -> Result<Value> {
        Ok(json!(
            std::str::from_utf8(self.take(len)?).context("invalid MessagePack UTF-8")?
        ))
    }
    fn array(&mut self, len: usize, depth: usize) -> Result<Value> {
        ensure!(
            len <= self.bytes.len().saturating_sub(self.at),
            "impossible MessagePack array size"
        );
        let mut values = Vec::new();
        for _ in 0..len {
            values.push(self.value(depth + 1)?);
        }
        Ok(Value::Array(values))
    }
    fn map(&mut self, len: usize, depth: usize) -> Result<Value> {
        ensure!(
            len <= self.bytes.len().saturating_sub(self.at) / 2,
            "impossible MessagePack map size"
        );
        let mut values = serde_json::Map::new();
        for _ in 0..len {
            let key = self
                .value(depth + 1)?
                .as_str()
                .context("non-string MessagePack map key")?
                .to_string();
            let value = self.value(depth + 1)?;
            ensure!(
                values.insert(key, value).is_none(),
                "duplicate MessagePack map key"
            );
        }
        Ok(Value::Object(values))
    }
    fn value(&mut self, depth: usize) -> Result<Value> {
        ensure!(depth < 32, "MessagePack nesting limit exceeded");
        let kind = self.take(1)?[0];
        match kind {
            0x00..=0x7f => Ok(json!(kind)),
            0xe0..=0xff => Ok(json!(kind as i8)),
            0x80..=0x8f => self.map(usize::from(kind & 15), depth),
            0x90..=0x9f => self.array(usize::from(kind & 15), depth),
            0xa0..=0xbf => self.string(usize::from(kind & 31)),
            0xc0 => Ok(Value::Null),
            0xc2 => Ok(json!(false)),
            0xc3 => Ok(json!(true)),
            0xcc => Ok(json!(self.unsigned(1)?)),
            0xcd => Ok(json!(self.unsigned(2)?)),
            0xce => Ok(json!(self.unsigned(4)?)),
            0xcf => Ok(json!(self.unsigned(8)?)),
            0xd0 => Ok(json!(self.unsigned(1)? as i8)),
            0xd1 => Ok(json!(self.unsigned(2)? as i16)),
            0xd2 => Ok(json!(self.unsigned(4)? as i32)),
            0xd3 => Ok(json!(self.unsigned(8)? as i64)),
            0xd9..=0xdb => {
                let size = self.unsigned(1usize << (kind - 0xd9))? as usize;
                self.string(size)
            }
            0xdc | 0xdd => {
                let size = self.unsigned(if kind == 0xdc { 2 } else { 4 })? as usize;
                self.array(size, depth)
            }
            0xde | 0xdf => {
                let size = self.unsigned(if kind == 0xde { 2 } else { 4 })? as usize;
                self.map(size, depth)
            }
            _ => bail!("unreviewed MessagePack value type"),
        }
    }
}

fn decode_frames(bytes: &[u8]) -> Result<Vec<Value>> {
    ensure!(bytes.len() <= MAX_MESSAGE, "SignalR frame limit exceeded");
    let mut offset = 0;
    let mut frames = Vec::new();
    while offset < bytes.len() {
        let mut size = 0usize;
        let mut shift = 0;
        loop {
            ensure!(offset < bytes.len() && shift < 35, "invalid SignalR length");
            let byte = bytes[offset];
            offset += 1;
            size |= usize::from(byte & 127) << shift;
            if byte & 128 == 0 {
                break;
            }
            shift += 7;
        }
        ensure!(
            size > 0 && size <= bytes.len() - offset,
            "incomplete SignalR message"
        );
        let mut decoder = Decoder {
            bytes: &bytes[offset..offset + size],
            at: 0,
        };
        let value = decoder.value(0)?;
        ensure!(decoder.at == size, "trailing MessagePack payload");
        frames.push(value);
        offset += size;
    }
    Ok(frames)
}

fn latest(items: &[Command], code: u64) -> Option<&[String]> {
    items
        .iter()
        .rev()
        .find(|x| x.code == code)
        .map(|x| x.args.as_slice())
}
fn native(text: &str) -> Result<u64> {
    text.parse::<u64>()
        .context("invalid nonnegative native integer")
}
fn continuation(items: &[Command], processed_free: u64) -> Result<Option<String>> {
    ensure!(
        !items.iter().any(|x| matches!(x.code, 110 | 111)),
        "Play'n GO native rejection"
    );
    if latest(items, 52).is_some_and(|args| args.get(1).is_some_and(|v| v == "0")) {
        return Ok(None);
    }
    if items
        .iter()
        .any(|x| x.code == 2 && x.args.get(..2) == Some(&["5".to_string(), "1".to_string()][..]))
    {
        return Ok(Some("2 6".into()));
    }
    if let Some(end) = latest(items, 3).filter(|a| a.len() >= 4) {
        if native(&end[3])? > 0 || processed_free > 0 {
            return Ok(Some(format!("7 {processed_free}")));
        }
        if native(&end[2])? > 0 || end[0] == "1" {
            return Ok(Some("4 0".into()));
        }
    }
    bail!("unrecognized native continuation; round retained")
}
#[derive(Debug)]
struct BetProfile {
    coins: u64,
    lines: u64,
    denomination: u64,
    cost: u64,
    scale: u64,
}

fn apply_ultra(source: &str, initial: &[Command], profile: &mut BetProfile) -> Result<()> {
    ensure!(
        latest(initial, 60)
            .and_then(|packet| packet.get(3))
            .is_some_and(|state| state == "0")
            && Regex::new(r"\bbetBooster:[A-Za-z_$][\w.$]*[,}]")?.is_match(source)
            && source.contains(".lines*this._betBooster.currentBetBoostFactor"),
        "Play'n GO Go Ultra was not offered"
    );
    let factor = Regex::new(r"[{,]betBoostFactor:(\d+(?:\.\d+)?)[,}]")?;
    let factors: BTreeSet<_> = factor
        .captures_iter(source)
        .filter_map(|matched| matched.get(1))
        .map(|matched| matched.as_str())
        .collect();
    ensure!(factors.len() == 1, "Play'n GO Go Ultra factor is ambiguous");
    let factor = crate::model::decimal(factors.first().unwrap())?;
    ensure!(
        factor > Decimal::ONE,
        "Play'n GO Go Ultra factor is not a booster"
    );
    let boosted = crate::model::exact_mul(Decimal::from(profile.lines), factor)?;
    ensure!(
        boosted.fract().is_zero(),
        "Play'n GO boosted lines are not integral"
    );
    profile.lines = boosted
        .to_u64()
        .context("Play'n GO boosted lines exceed native range")?;
    profile.cost = profile
        .lines
        .checked_mul(profile.coins)
        .and_then(|base| base.checked_mul(profile.denomination))
        .context("Play'n GO boosted cost exceeds native range")?;
    Ok(())
}

#[test]
fn go_ultra_quotes_integer_lines_from_the_reviewed_offer() {
    let source =
        "betBooster:q,{betBoostFactor:1.5},obj.lines*this._betBooster.currentBetBoostFactor";
    let initial = [Command {
        code: 60,
        args: vec!["".into(), "".into(), "".into(), "0".into()],
    }];
    let mut profile = BetProfile {
        coins: 1,
        lines: 20,
        denomination: 5,
        cost: 100,
        scale: 100,
    };
    apply_ultra(source, &initial, &mut profile).unwrap();
    assert_eq!((profile.lines, profile.cost), (30, 150));
    assert!(apply_ultra(source, &[], &mut profile).is_err());
}

fn profile(
    source: &str,
    initial: &[Command],
    xml: &str,
    configuration: &Value,
) -> Result<BetProfile> {
    let values = latest(initial, 54).context("native denominations missing")?;
    let count = usize::try_from(native(
        values.first().context("denomination count missing")?,
    )?)?;
    ensure!(
        count > 0 && count <= 4096 && values.len() > count,
        "native denomination count invalid"
    );
    let values = values[1..=count]
        .iter()
        .map(|v| native(v))
        .collect::<Result<Vec<_>>>()?;
    ensure!(values.iter().all(|v| *v > 0), "invalid denomination");
    let doc = roxmltree::Document::parse(xml).context("public denomination XML invalid")?;
    let mut display = doc
        .descendants()
        .filter(|n| n.has_tag_name("denom"))
        .map(|n| {
            n.attribute("Value")
                .context("denom Value missing")
                .map(str::to_owned)
        })
        .collect::<Result<Vec<_>>>()?;
    if display.is_empty() {
        let nodes = doc
            .descendants()
            .filter(|n| n.has_tag_name("Denominations"))
            .collect::<Vec<_>>();
        ensure!(
            nodes.len() == 1,
            "public denominations missing or ambiguous"
        );
        display = nodes[0]
            .text()
            .context("denomination values missing")?
            .split(',')
            .map(str::to_owned)
            .collect();
    }
    ensure!(
        display.len() == count,
        "native/display denomination pairing unproven"
    );
    let mut scale = None;
    for (value, display) in values.iter().zip(display.iter()) {
        let display = crate::model::decimal(display)?;
        ensure!(display > Decimal::ZERO, "nonpositive display denomination");
        let native_value = Decimal::from(*value);
        let ratio = native_value
            .checked_div(display)
            .context("currency scale division failed")?;
        ensure!(
            ratio.fract() == Decimal::ZERO
                && crate::model::exact_mul(ratio, display)? == native_value,
            "currency scale not exact"
        );
        let ratio = ratio
            .to_u64()
            .filter(|n| *n > 0)
            .context("currency scale invalid")?;
        ensure!(
            scale.is_none_or(|s| s == ratio),
            "inconsistent native currency scale"
        );
        scale = Some(ratio);
    }
    // The supported modern client layout binds the parameter pair to the game's bet component.
    // Inherited/legacy or partial overrides need a separate reviewed port, never guessed constants.
    let pairs = Regex::new(
        r"betMaxLines:([\w$.]+),betMaxCoins:([\w$.]+)|betMaxCoins:([\w$.]+),betMaxLines:([\w$.]+)",
    )?;
    let binding = Regex::new(
        r"objects\.bet,\{components:\[\{component:[\w.$]+,params:\{$|\bbet:[\w.$]+\.merge\([\w$]+,\{components:\[\{component:[\w.$]+,params:\{$",
    )?;
    let found = pairs
        .captures_iter(source)
        .filter(|c| {
            let at = c.get(0).unwrap().start();
            !String::from_utf8_lossy(&source.as_bytes()[at.saturating_sub(90)..at])
                .contains("super.defaultParams")
        })
        .last()
        .context("reviewed modern bet parameter pair missing")?;
    let matched = found.get(0).unwrap();
    let prefix = String::from_utf8_lossy(
        &source.as_bytes()[matched.start().saturating_sub(200)..matched.start()],
    );
    let mut bound = binding.is_match(&prefix);
    if !bound {
        let maps = Regex::new(r"\bbet:([\w$]+)(?:[,}])")?;
        for map in maps.captures_iter(&source[matched.end()..]) {
            let alias = map.get(1).unwrap().as_str();
            let assignment = Regex::new(&format!(
                r"(?:^|[^\w.$]){}=[\w.$]+\.merge\(",
                regex::escape(alias)
            ))?;
            if let Some(entry) = assignment.find_iter(&source[..matched.start()]).last() {
                let span = &source[entry.start()..matched.start()];
                if span.len() < 300
                    && span.contains("components:[{component:")
                    && span.contains("params:{")
                {
                    bound = true;
                    break;
                }
            }
        }
    }
    ensure!(bound, "bet parameters not bound to the game");
    let partial = Regex::new(
        r"\.merge\([^,]+,\{components:\[\{component:[\w.$]+,params:\{betMax(?:Lines|Coins):[\w$.]+\}",
    )?;
    ensure!(
        !partial.is_match(&source[matched.end()..]),
        "later partial bet override needs review"
    );
    let constant = |name: &str| -> Result<u64> {
        if name.bytes().all(|b| b.is_ascii_digit()) {
            return native(name);
        }
        let assignment = Regex::new(&format!(
            r"(?:^|[^\w.$]){}=(\d+)(?:[,;}}])",
            regex::escape(name)
        ))?;
        let mut constants = std::collections::BTreeSet::new();
        for c in assignment.captures_iter(source) {
            constants.insert(native(c.get(1).unwrap().as_str())?);
        }
        ensure!(constants.len() == 1, "bet constant missing or ambiguous");
        Ok(*constants.iter().next().unwrap())
    };
    let lines = constant(found.get(1).or_else(|| found.get(4)).unwrap().as_str())?;
    let mut coins = constant(found.get(2).or_else(|| found.get(3)).unwrap().as_str())?;
    let locks = Regex::new(r"get lock\(\)\{return ([\w.|]+)\}")?;
    let source_fixed = locks.captures_iter(source).any(|c| {
        let flags = c
            .get(1)
            .unwrap()
            .as_str()
            .split('|')
            .map(|v| v.rsplit('.').next().unwrap())
            .collect::<std::collections::BTreeSet<_>>();
        ["LINE", "COIN", "FIXED_BET"]
            .iter()
            .all(|flag| flags.contains(flag))
    }) || Regex::new(r"get betMode\(\)\{return [\w$.]+\.FIXED\}")?
        .is_match(source);
    let fixed = source_fixed || matches!(configuration["creditDisplay"].as_u64(), Some(2 | 3));
    if !fixed {
        ensure!(
            configuration["creditDisplay"] == 0,
            "unreviewed public bet mode"
        );
        let published_lines = configuration["lines"].as_u64();
        ensure!(
            published_lines == Some(lines)
                || (published_lines == Some(0) && source.contains("this._lines=this._maxLines")),
            "public/default line mapping unproven"
        );
        coins = 1;
    }
    ensure!(coins > 0 && lines > 0, "nonpositive native bet parameters");
    let denomination = *values.iter().min().unwrap();
    let cost = coins
        .checked_mul(lines)
        .and_then(|v| v.checked_mul(denomination))
        .context("native bet overflow")?;
    Ok(BetProfile {
        coins,
        lines,
        denomination,
        cost,
        scale: scale.unwrap(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use futures_util::{SinkExt, StreamExt};
    use serde_json::json;
    use tokio::{
        io::{AsyncReadExt, AsyncWriteExt},
        net::TcpListener,
    };
    #[test]
    fn signalr_known_vector_and_malformed_lengths() {
        assert_eq!(encode_frame(&json!([6])).unwrap(), vec![2, 0x91, 6]);
        assert_eq!(decode_frames(&[2, 0x91, 6]).unwrap(), vec![json!([6])]);
        for bytes in [
            &[2, 0x91][..],
            &[0x80][..],
            &[0xff, 0xff, 0xff, 0xff, 0x7f][..],
            &[1, 0xc1][..],
        ] {
            assert!(decode_frames(bytes).is_err());
        }
    }
    #[test]
    fn text_commands_keep_empty_and_percent_encoded_native_arguments() {
        let parsed = commands("d=200 12 \"PLAY\" \"\" \"GB\"\r\n2 3 \"a%20b\"").unwrap();
        assert_eq!(
            parsed,
            vec![
                Command {
                    code: 200,
                    args: vec!["12".into(), "PLAY".into(), "".into(), "GB".into()]
                },
                Command {
                    code: 2,
                    args: vec!["3".into(), "a b".into()]
                }
            ]
        );
        assert!(commands("2 \"unterminated").is_err());
        assert!(commands("no command").is_err());
    }
    #[test]
    fn closure_stops_and_feature_collect_is_not_guessed() {
        assert_eq!(
            continuation(&commands("3 0 4 4 0 1\n52 99984 0 0").unwrap(), 0).unwrap(),
            None
        );
        assert_eq!(
            continuation(&commands("2 5 1").unwrap(), 0).unwrap(),
            Some("2 6".into())
        );
        assert_eq!(
            continuation(&commands("2 5 0\n3 0 30 30 0 1").unwrap(), 0).unwrap(),
            Some("4 0".into())
        );
        assert_eq!(
            continuation(&commands("3 0 0 0 8 1").unwrap(), 0).unwrap(),
            Some("7 0".into())
        );
        assert!(continuation(&commands("111 failure\n52 1000 0 0").unwrap(), 0).is_err());
        assert!(continuation(&commands("2 4 1").unwrap(), 0).is_err());
    }
    #[test]
    fn source_bound_bet_and_exact_scale_are_required_before_entry() {
        let source = "get lock(){return q.LINE|q.COIN|q.FIXED_BET} q.merge(a.objects.bet,{components:[{component:C,params:{betMaxLines:20,betMaxCoins:1}}]})";
        let initial = vec![Command {
            code: 54,
            args: vec!["2".into(), "1".into(), "5".into(), "1".into()],
        }];
        let p = profile(
            source,
            &initial,
            "<root><Denominations>0.01,0.05</Denominations></root>",
            &json!({"creditDisplay":2}),
        )
        .unwrap();
        assert_eq!(
            (p.coins, p.lines, p.denomination, p.cost, p.scale),
            (1, 20, 1, 20, 100)
        );
        assert!(
            profile(
                "betMaxLines:20,betMaxCoins:1",
                &initial,
                "<root><Denominations>0.01,0.05</Denominations></root>",
                &json!({"creditDisplay":2})
            )
            .is_err()
        );
        assert!(
            profile(
                source,
                &initial,
                "<root><Denominations>0.01,0.03</Denominations></root>",
                &json!({"creditDisplay":2})
            )
            .is_err()
        );
        let unlocked = "this._lines=this._maxLines;q.merge(a.objects.bet,{components:[{component:C,params:{betMaxLines:20,betMaxCoins:5}}]})";
        assert_eq!(
            profile(
                unlocked,
                &initial,
                "<root><Denominations>0.01,0.05</Denominations></root>",
                &json!({"creditDisplay":0,"lines":0})
            )
            .unwrap()
            .coins,
            1
        );
    }
    #[test]
    fn reviewed_fixed_lock_preserves_coins_even_when_display_is_zero() {
        let source = "get lock(){return q.LINE|q.COIN|q.FIXED_BET}q.merge(a.objects.bet,{components:[{component:C,params:{betMaxLines:20,betMaxCoins:5}}]})";
        let initial = commands("54 1 1 1").unwrap();
        let p = profile(
            source,
            &initial,
            "<root><Denominations>0.01</Denominations></root>",
            &json!({"creditDisplay":0,"lines":20}),
        )
        .unwrap();
        assert_eq!((p.coins, p.lines, p.cost), (5, 20, 100));
    }
    #[test]
    fn signalr_commands_merge_native_frames_and_reject_unknown_messages() {
        let mut payload = vec![2, 0x91, 6];
        payload.extend(
            encode_frame(&json!([1, {}, null, "Commands", ["52 1000 0 0\r\n"], []])).unwrap(),
        );
        let parsed = decode_commands(&SocketPayload::Binary(payload)).unwrap();
        assert_eq!(parsed[0][0]["code"], 52);
        assert!(
            decode_commands(&SocketPayload::Binary(
                encode_frame(&json!([7, "closed"])).unwrap()
            ))
            .is_err()
        );
        assert!(decode_commands(&SocketPayload::Text("52 1000 0 0".into())).is_err());
        assert!(
            decode_handshake(&SocketPayload::Text("{\"error\":\"denied\"}\u{1e}".into())).is_err()
        );
        assert!(decode_handshake(&SocketPayload::Text("{}".into())).is_err());
    }
    #[test]
    fn final_native_payout_and_closed_wallet_both_required() {
        let final_commands = commands("3 0 4 4 0 1\n52 2499984 0 0").unwrap();
        assert_eq!(
            settle(2500000, 20, &final_commands, &final_commands).unwrap(),
            (4, 2499984)
        );
        let mismatch = commands("3 0 5 5 0 1\n52 2499984 0 0").unwrap();
        assert!(settle(2500000, 20, &mismatch, &mismatch).is_err());
        let open = commands("3 0 4 4 8 1\n52 2499984 0 0").unwrap();
        assert!(settle(2500000, 20, &open, &open).is_err());
        assert!(settle(2500000, 20, &commands("52 2499984 0 0").unwrap(), &[]).is_err());
    }
    #[tokio::test]
    async fn full_offline_native_session_saves_owner_before_one_paid_entry_and_collect() {
        use crate::{
            model::{CampaignPlan, InventorySnapshot, Job, RoundSpec},
            store::Store,
        };
        let directory = tempfile::tempdir().unwrap();
        let store = Store::open(directory.path()).unwrap();
        let inventory:InventorySnapshot=serde_json::from_value(json!({"id":"playngo-fixture","sources":[],"providers":[{"id":"playngo","name":"Play'n GO","ready":true,"campaign_eligible":true,"games":[{"id":"1001","name":"Wrappin' More Gold","ready":true,"modes":[{"key":"normal","type":"normal","label":"Normal"}]}]}]})).unwrap();
        store.install_inventory(&inventory).unwrap();
        let source = "desktop_Entry;get lock(){return q.LINE|q.COIN|q.FIXED_BET}q.merge(a.objects.bet,{components:[{component:C,params:{betMaxLines:20,betMaxCoins:1}}]})";
        let settings = json!({"gid":"wrappinmoregold","source_sha256":sha256(source.as_bytes())});
        let plan = CampaignPlan {
            coverage: None,
            schema_version: 1,
            id: "playngo-fixture-campaign".into(),
            inventory_id: inventory.id.clone(),
            jobs: vec![Job {
                provider: "playngo".into(),
                game: "1001".into(),
                mode: "normal".into(),
                samples: 1,
                settings: settings.clone(),
            }],
        };
        store.create_campaign(&plan).unwrap();
        let spec = RoundSpec {
            campaign_id: plan.id,
            inventory_id: inventory.id.clone(),
            job_index: 0,
            sample_index: 0,
            provider: "playngo".into(),
            game: "1001".into(),
            mode: "normal".into(),
            kind: ModeKind::Normal,
            settings: settings.clone(),
        };
        let round = store.create_round(&spec).unwrap();
        let mut ctx =
            RunContext::new(store.clone(), round.id.clone(), "playngo", 2, 20, None).unwrap();
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        ctx.route_to_fixture(&format!("http://{}", listener.local_addr().unwrap()))
            .unwrap();
        let server_store = store.clone();
        let server_round = round.id.clone();
        let server = tokio::spawn(async move {
            let xml = "<root><Denominations>0.01,0.05</Denominations></root>";
            let encoded = url::form_urlencoded::byte_serialize(xml.as_bytes()).collect::<String>();
            let config = json!({"creditDisplay":2,"resourceRoot":"https://cdn.playngonetwork.com/version/","gameURL":"games/slots/wrappinmoregold/wrappinmoregold_main.js","settings":format!("&settings={encoded}")});
            let replies = [
                (
                    "GET /released.playngonetwork.com/casino/ContainerLauncher?",
                    "practice productGroup: 2".to_string(),
                ),
                (
                    "GET /released.playngonetwork.com/games/getgamebygid/wrappinmoregold ",
                    json!({"gameId":1001}).to_string(),
                ),
                (
                    "GET /released.playngonetwork.com/configuration/prelaunchconfiguration?",
                    json!({"Server":SERVER}).to_string(),
                ),
                (
                    "POST /ascflyp.playngonetwork.com/ ",
                    "d=103 \"synthetic-first-session\"\r\n".to_string(),
                ),
                (
                    "POST /ascflyp.playngonetwork.com/ ",
                    "d=103 \"synthetic-owner\"\r\n101 1 \"DEMO\" \"\" \"ZZ\" \"\" \"\"\r\n"
                        .to_string(),
                ),
                (
                    "GET /released.playngonetwork.com/configuration/v2?",
                    config.to_string(),
                ),
                (
                    "GET /cdn.playngonetwork.com/version/games/wrappinmoregold/wrappinmoregold_desktop.bundle.js ",
                    source.to_string(),
                ),
            ];
            for (index, (path, body)) in replies.iter().enumerate() {
                let (mut stream, _) = listener.accept().await.unwrap();
                let mut headers = Vec::new();
                while !headers.ends_with(b"\r\n\r\n") {
                    let mut byte = [0];
                    stream.read_exact(&mut byte).await.unwrap();
                    headers.push(byte[0]);
                    assert!(headers.len() < 16000);
                }
                let headers = String::from_utf8(headers).unwrap();
                assert!(headers.starts_with(path), "unexpected fixture request");
                let length = headers
                    .lines()
                    .filter_map(|l| l.split_once(':'))
                    .find(|(k, _)| k.eq_ignore_ascii_case("content-length"))
                    .map(|(_, v)| v.trim().parse::<usize>().unwrap())
                    .unwrap_or(0);
                let mut request = vec![0; length];
                stream.read_exact(&mut request).await.unwrap();
                if index == 3 {
                    assert!(
                        String::from_utf8(request)
                            .unwrap()
                            .starts_with("d=1\r\n0\r\n103 12 ")
                    );
                } else if index == 4 {
                    assert!(
                        String::from_utf8(request)
                            .unwrap()
                            .starts_with("d=2\r\nsynthetic-first-session\r\n101 ")
                    );
                }
                let response = format!(
                    "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                );
                stream.write_all(response.as_bytes()).await.unwrap();
                stream.shutdown().await.unwrap();
            }
            let (stream, _) = listener.accept().await.unwrap();
            let mut socket = tokio_tungstenite::accept_async(stream).await.unwrap();
            let handshake = socket.next().await.unwrap().unwrap();
            assert_eq!(
                handshake.to_text().unwrap(),
                "{\"protocol\":\"messagepack\",\"version\":2}\u{1e}"
            );
            socket
                .send(tokio_tungstenite::tungstenite::Message::Text(
                    "{}\u{1e}".into(),
                ))
                .await
                .unwrap();
            // Literal fixtures generated independently with Python msgpack, not this codec.
            let init = "39960180c0a8436f6d6d616e647391d92831303420310d0a353420322031203520310d0a35322032353030303030203020300d0a3130390d0a90";
            let paid = "1d960180c0a8436f6d6d616e647391ad33203020342034203020310d0a90";
            let collect = "20960180c0a8436f6d6d616e647391b035322032343939393834203020300d0a90";
            for (index, reply) in [init, paid, collect].into_iter().enumerate() {
                let incoming = socket.next().await.unwrap().unwrap();
                let bytes = incoming.into_data();
                let frames = decode_frames(&bytes).unwrap();
                assert_eq!(frames[0][3], "ProcessPacket");
                let text = frames[0][4][0].as_str().unwrap();
                assert!(text.starts_with(&format!("d={}\r\nsynthetic-owner\r\n", index + 3)));
                if index == 0 {
                    assert!(text.contains("104 1001 0 %22"));
                } else if index == 1 {
                    assert!(text.ends_with("1 1 20 1 1\r\n"));
                    assert_eq!(
                        server_store.session(&server_round).unwrap().unwrap()["session_id"],
                        "synthetic-owner"
                    );
                    let pending = server_store.exchanges(&server_round).unwrap();
                    assert!(pending.last().unwrap().request.financial);
                    assert!(pending.last().unwrap().response.is_none());
                } else {
                    assert!(text.ends_with("4 0\r\n"));
                }
                let bytes = (0..reply.len())
                    .step_by(2)
                    .map(|n| u8::from_str_radix(&reply[n..n + 2], 16).unwrap())
                    .collect::<Vec<_>>();
                socket
                    .send(tokio_tungstenite::tungstenite::Message::Binary(
                        bytes.into(),
                    ))
                    .await
                    .unwrap();
            }
        });
        let game = &inventory.providers[0].games[0];
        let mut outcome = execute(&ctx, game, &game.modes[0], &settings)
            .await
            .unwrap();
        server.await.unwrap();
        assert!(outcome.verify().unwrap());
        assert_eq!(
            (&outcome.cost, &outcome.payout, &outcome.balance_after),
            (&"20".into(), &"4".into(), &"2499984".into())
        );
        let entries = store.exchanges(&round.id).unwrap();
        assert_eq!(
            entries
                .iter()
                .filter(|e| e.request.label == "normal")
                .count(),
            1
        );
        assert_eq!(entries.iter().filter(|e| e.request.financial).count(), 2);
        assert!(entries.iter().all(|e| e.response.is_some()));
    }
}
