use crate::model::{decimal, exact_mul, wallet_matches};
use crate::{
    context::RunContext,
    model::{Game, Mode, ModeKind, RoundOutcome, now_ms, sha256},
    store::Store,
};
use aes::{
    Aes256,
    cipher::{Block, BlockDecrypt, BlockEncrypt, KeyInit},
};
use anyhow::{Context, Result, bail, ensure};
use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{collections::BTreeMap, time::Duration};
use url::Url;
use uuid::Uuid;

const LAUNCHER: &str = "https://gamelauncherservice-stage.1x2networkhub.com/";
const UA: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36";
pub(crate) const MISSING_CLOSING_BALANCE: &str =
    "Iron Dog settled round has no native closing FUN balance";
pub(crate) const WALLET_DISCREPANCY: &str =
    "Iron Dog settled round has a native wallet discrepancy";

fn selection(kind: &ModeKind, key: &str) -> Option<MorphicMode> {
    match kind {
        ModeKind::Normal if key == "normal" => Some(MorphicMode::Normal),
        ModeKind::Purchase => key
            .strip_prefix("buy ")
            .filter(|s| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit()))
            .map(|id| MorphicMode::Purchase(id.into())),
        ModeKind::AnteBet => key
            .strip_prefix("ante ")
            .filter(|s| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit()))
            .map(|id| MorphicMode::Ante(id.into())),
        _ => None,
    }
}

pub fn supports(game: &Game, mode: &Mode) -> bool {
    matches!(game.id.as_str(), "90110" | "90140") && selection(&mode.kind, &mode.key).is_some()
}

fn correlation(text: &str, seed: u32) -> String {
    let mut a = 3735928559 ^ seed;
    let mut b = 1103547991 ^ seed;
    for unit in text.encode_utf16() {
        a = (a ^ u32::from(unit)).wrapping_mul(2654435761);
        b = (b ^ u32::from(unit)).wrapping_mul(1597334677);
    }
    a = (a ^ (a >> 16)).wrapping_mul(2246822507) ^ (b ^ (b >> 13)).wrapping_mul(3266489909);
    b = (b ^ (b >> 16)).wrapping_mul(2246822507) ^ (a ^ (a >> 13)).wrapping_mul(3266489909);
    format!("{a:08x}{b:08x}")
}

fn encrypt(key: &str, text: &[u8]) -> Result<String> {
    let aes = Aes256::new_from_slice(key.as_bytes())
        .map_err(|_| anyhow::anyhow!("invalid Iron Dog gateway key length"))?;
    let mut previous = *Uuid::new_v4().as_bytes();
    let mut encoded = previous.to_vec();
    let mut data = text.to_vec();
    let padding = 16 - data.len() % 16;
    data.resize(data.len() + padding, padding as u8);
    for chunk in data.chunks_exact(16) {
        let mut block = Block::<Aes256>::default();
        for (i, byte) in chunk.iter().enumerate() {
            block[i] = byte ^ previous[i];
        }
        aes.encrypt_block(&mut block);
        previous.copy_from_slice(&block);
        encoded.extend_from_slice(&block);
    }
    Ok(encoded.iter().map(|b| format!("{b:02x}")).collect())
}

fn decrypt(key: &str, text: &str) -> Result<Value> {
    ensure!(
        text.len() >= 64 && text.len() % 32 == 0 && text.bytes().all(|b| b.is_ascii_hexdigit()),
        "invalid Iron Dog encrypted response"
    );
    let bytes = (0..text.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&text[i..i + 2], 16))
        .collect::<std::result::Result<Vec<_>, _>>()?;
    let aes = Aes256::new_from_slice(key.as_bytes())
        .map_err(|_| anyhow::anyhow!("invalid Iron Dog gateway key length"))?;
    let mut plaintext = Vec::new();
    for (previous, current) in bytes.chunks_exact(16).zip(bytes.chunks_exact(16).skip(1)) {
        let mut block = Block::<Aes256>::clone_from_slice(current);
        aes.decrypt_block(&mut block);
        plaintext.extend(block.iter().zip(previous).map(|(a, b)| a ^ b));
    }
    let padding = usize::from(
        *plaintext
            .last()
            .context("empty Iron Dog gateway response")?,
    );
    ensure!(
        (1..=16).contains(&padding)
            && plaintext[plaintext.len() - padding..]
                .iter()
                .all(|&b| usize::from(b) == padding),
        "invalid Iron Dog gateway padding"
    );
    plaintext.truncate(plaintext.len() - padding);
    Ok(serde_json::from_slice(&plaintext)?)
}

fn text<'a>(v: &'a Value, name: &str) -> Result<&'a str> {
    v[name]
        .as_str()
        .filter(|s| !s.is_empty())
        .with_context(|| format!("missing Iron Dog field {name}"))
}

struct Gateway<'a> {
    ctx: &'a RunContext,
    url: Url,
    headers: BTreeMap<String, String>,
    token: String,
}

impl Gateway<'_> {
    async fn command(&mut self, action: &str, payload: &Value, financial: bool) -> Result<Value> {
        tokio::time::sleep(Duration::from_secs(1)).await;
        let mut url = self.url.clone();
        url.query_pairs_mut().append_pair(
            "target",
            &format!("http://localhost:81/integratedslotsduck/services/v1/duck/{action}"),
        );
        let encrypted = encrypt(&self.token, &serde_json::to_vec(payload)?)?;
        let response = self
            .ctx
            .json(
                action,
                url.as_str(),
                &json!({"data":encrypted}),
                self.headers.clone(),
                financial,
            )
            .await?;
        let outer = decrypt(&self.token, text(&response["response"], "data")?)?;
        self.token = text(&outer, "token")?.to_owned();
        let native: Value = serde_json::from_str(text(&outer, "data")?)?;
        ensure!(
            native["success"] == true,
            "Iron Dog Morphic native command rejected"
        );
        Ok(native["payload"].clone())
    }
}

pub async fn execute(ctx: &RunContext, game: &Game, mode: &Mode) -> Result<RoundOutcome> {
    ensure!(
        supports(game, mode),
        "Iron Dog reviewed game or mode unavailable"
    );
    let gid = game.id.parse::<u64>()?;
    let demo_id = match gid {
        90110 => "182733",
        90140 => "182743",
        _ => bail!("Iron Dog public demo link unavailable"),
    };
    let entry = ctx.get("public_demo_link", &format!("https://nogs-gl-stage.nyxmalta.com/game/?clienttype=flash&nogscurrency=EUR&nogslang=es_ES&nogsmode=demo&nogsoperatorid=961&nogsgameid={demo_id}")).await?;
    ensure!(
        matches!(entry.status, 301 | 302 | 303 | 307 | 308),
        "Iron Dog public demo link did not redirect"
    );
    let redirect = Url::parse(
        entry
            .headers
            .get("location")
            .context("missing Iron Dog redirect")?,
    )?;
    ensure!(
        redirect.origin().ascii_serialization() == "https://ogs-gcm-eu-stage.nyxop.net"
            && redirect.path() == "/gcm/gcm-launcher/launcher.html",
        "unexpected Iron Dog public demo redirect"
    );
    let mut profile: BTreeMap<String, String> = redirect.query_pairs().into_owned().collect();
    ensure!(
        profile.get("mode").is_some_and(|mode| mode == "demo")
            && profile
                .get("sessionid")
                .is_some_and(|sid| sid.starts_with("Free:"))
            && profile.get("gameid") == Some(&game.id),
        "Iron Dog redirect did not confirm this demo"
    );
    let base = profile
        .remove("gameUrl")
        .context("missing Iron Dog launcher base")?;
    let base_url = Url::parse(&base)?;
    ensure!(
        base_url.origin().ascii_serialization() == "https://gamelauncher-stage.1x2networkhub.com"
            && base_url.path() == "/playGame.html",
        "unexpected Iron Dog launcher base"
    );
    let base_fields: BTreeMap<String, String> = base_url.query_pairs().into_owned().collect();
    let client_id = base_fields
        .get("clientID")
        .context("missing Iron Dog public client ID")?
        .parse::<u64>()?;
    let mut query_fields = base_fields.clone();
    query_fields.extend(profile.clone());
    query_fields.insert("realwinloss".into(), "n".into());
    let query = url::form_urlencoded::Serializer::new(String::new())
        .extend_pairs(&query_fields)
        .finish();
    let seed = format!("{query}|{}|{}", now_ms(), Uuid::new_v4());
    let hash = format!("{}{}", correlation(&seed, 0), correlation(&seed, 1));
    let device = profile
        .get("device")
        .context("missing Iron Dog demo device")?
        .clone();
    let query_encoded = url::form_urlencoded::byte_serialize(query.as_bytes()).collect::<String>();
    profile.extend(base_fields);
    profile.extend([
        ("gameUrl".into(), base),
        ("playmode".into(), "demo".into()),
        ("loggedin".into(), "true".into()),
        ("gameName".into(), game.id.clone()),
        ("NYX_GCM_ENV".into(), "stage".into()),
        ("NYX_GCM_DEVICE".into(), device),
        (
            "NYX_GCM_PARAMS".into(),
            format!("/playGame.html?{query_encoded}"),
        ),
        ("userAgent".into(), UA.into()),
    ]);
    let params: Vec<_> = profile
        .into_iter()
        .map(|(key, value)| json!({"key":key,"value":value}))
        .collect();
    let launch = ctx
        .json(
            "public_fun_launcher",
            LAUNCHER,
            &json!({"clientID":client_id,"hash":hash,"payload":params,"userAgent":UA}),
            BTreeMap::from([(
                "origin".into(),
                "https://gamelauncher-stage.1x2networkhub.com".into(),
            )]),
            false,
        )
        .await?;
    let binding = validate_launch(&launch, gid)?;
    ensure!(binding.morphic, "Iron Dog game requires a different engine");
    let mut p = launch["data"]["parameters"].clone();
    if let Some(extras) = launch["data"]["extras"].as_array() {
        for extra in extras {
            let key = text(extra, "key")?;
            if matches!(
                key,
                "sessionID"
                    | "operatorID"
                    | "operatorBrandID"
                    | "installID"
                    | "accountID"
                    | "extInstallID"
                    | "jurisdiction"
            ) {
                p[key] = extra["value"].clone();
            }
        }
    }
    let url = Url::parse(&binding.gateway)?;
    let origin = if url.host_str() == Some("gp-stage.1x2hubeurope.com") {
        "https://cdn-stage.1x2networkhub.com"
    } else {
        "https://cdn.desertorchidhub.com"
    };
    let mut headers = BTreeMap::from([
        ("origin".into(), origin.into()),
        ("referer".into(), format!("{origin}/")),
        ("user-agent".into(), UA.into()),
        ("accept-language".into(), "es-ES,es;q=0.9,en;q=0.8".into()),
        ("x-do-not-track".into(), "9d9f33c4d440".into()),
        ("x-csrf-token".into(), game.id.clone()),
    ]);
    let init = ctx
        .http(
            "gateway_init",
            "POST",
            url.join("init")?.as_str(),
            {
                let mut init_headers = headers.clone();
                init_headers.insert("content-length".into(), "0".into());
                init_headers
            },
            String::new(),
            false,
        )
        .await?;
    ensure!(
        init.status == 201,
        "Iron Dog gateway init returned HTTP {}",
        init.status
    );
    let native: Value = serde_json::from_str(&init.body)?;
    headers.insert("x-requested-with".into(), text(&native, "sid")?.into());
    headers.insert("x-requested-type".into(), "application/json".into());
    let mut gateway = Gateway {
        ctx,
        url,
        headers,
        token: text(&native, "token")?.into(),
    };
    let mut setup_req = json!({"realMode":false,"sessionID":text(&p,"sessionID")?,"operatorID":integer(&p["operatorID"])?,
        "operatorBrandID":integer(&p["operatorBrandID"])?,"installID":integer(&p["installID"])?,
        "accountID":p["accountID"],"gameID":gid,"jurisdiction":p["jurisdiction"].as_str().filter(|s| !s.is_empty()).unwrap_or("com")});
    if !p["extInstallID"].is_null() {
        setup_req["extInstallID"] = p["extInstallID"].clone();
    }
    let setup = gateway.command("setup", &setup_req, false).await?;
    let quote = quote_morphic(
        &setup,
        gid,
        &selection(&mode.kind, &mode.key).context("Iron Dog selector missing")?,
    )?;
    let before = optional_amount(&setup["account"]["balance"])?
        .context("Iron Dog demo does not publish the initial FUN wallet")?;
    ensure!(
        before >= decimal(&quote.cost_currency)?,
        "insufficient fictional demo funds"
    );
    let account = &setup["account"];
    identity(&account["accountID"])?;
    identity(&account["engineSessionID"])?;
    ctx.save_session(&json!({"provider":"irondog","game":gid,"account":account,"gateway":gateway.url.as_str(),"sid":native["sid"],"token":gateway.token,"currency":"FUN"}))?;
    let common = json!({"realMode":false,"gameID":gid,"operatorID":setup_req["operatorID"],"operatorBrandID":setup_req["operatorBrandID"],
        "jurisdiction":setup_req["jurisdiction"],"accountID":account["accountID"],"engineSessionID":account["engineSessionID"],"stake":quote.stake_unit});
    let mut steps = Vec::new();
    for index in 0..ctx.max_steps().min(500) {
        let mut payload = common.clone();
        if (index == 0 || quote.repeat_modifiers)
            && let Some(modifiers) = quote.modifiers.as_object()
        {
            payload
                .as_object_mut()
                .context("invalid Iron Dog spin payload")?
                .extend(modifiers.clone());
        }
        let step = gateway.command("spin", &payload, true).await?;
        let done = step["bet"]["settled"]
            .as_bool()
            .context("Iron Dog settlement marker missing")?;
        steps.push(step);
        if done {
            let receipt = reconcile_morphic(&setup, &steps, &quote)?;
            match receipt.wallet_matches {
                Some(true) => {}
                Some(false) => bail!(WALLET_DISCREPANCY),
                None => bail!(MISSING_CLOSING_BALANCE),
            }
            return Ok(RoundOutcome {
                native_round_id: Some(receipt.native_round_id),
                currency: "FUN".into(),
                currency_source: "native_response".into(),
                monetary_unit: "major".into(),
                balance_before: receipt
                    .balance_before
                    .context("missing FUN opening balance")?,
                balance_after: receipt
                    .balance_after
                    .context("missing FUN closing balance")?,
                cost: receipt.cost,
                payout: receipt.payout,
                native_closed: true,
                checks: BTreeMap::from([
                    ("morphic_fun_owner".into(), true),
                    ("native_offer".into(), true),
                ]),
                native_data: json!({"steps":steps.len()}),
            });
        }
        ensure!(
            steps
                .last()
                .and_then(|s| s.pointer("/state/phase"))
                .and_then(Value::as_array)
                .is_some_and(|a| !a.is_empty()
                    && a.iter()
                        .all(|p| matches!(p.as_str(), Some("BASE" | "HOLD_AND_WIN")))),
            "Iron Dog native phase requires a different control"
        );
    }
    bail!("Iron Dog continuation limit reached")
}

fn amount(value: &Value) -> Result<Decimal> {
    let text = match value {
        Value::String(text) => text.clone(),
        Value::Number(number) => number.to_string(),
        _ => bail!("Iron Dog native amount missing"),
    };
    decimal(&text)
}

fn optional_amount(value: &Value) -> Result<Option<Decimal>> {
    if value.is_null() {
        Ok(None)
    } else {
        amount(value).map(Some)
    }
}

fn integer(value: &Value) -> Result<u64> {
    match value {
        Value::Number(number) => number.as_u64().context("Iron Dog integer required"),
        Value::String(text) if !text.is_empty() && text.bytes().all(|b| b.is_ascii_digit()) => {
            text.parse().context("Iron Dog integer outside range")
        }
        _ => bail!("Iron Dog integer required"),
    }
}

fn identity(value: &Value) -> Result<String> {
    match value {
        Value::String(text) if !text.trim().is_empty() => Ok(text.clone()),
        Value::Number(number) if number.as_u64().is_some() => Ok(number.to_string()),
        _ => bail!("Iron Dog native round identity missing"),
    }
}

#[derive(Debug, Serialize)]
pub struct GatewayBinding {
    pub game_id: u64,
    pub gateway: String,
    pub guest_path: String,
    pub morphic: bool,
}

pub fn validate_launch(launch: &Value, expected_game: u64) -> Result<GatewayBinding> {
    let parameters = &launch["data"]["parameters"];
    ensure!(
        integer(&parameters["gameID"])? == expected_game,
        "Iron Dog launch game changed"
    );
    ensure!(
        matches!(parameters["playMode"].as_str(), Some("fun" | "demo")),
        "Iron Dog fresh public fun launch required"
    );
    let path = Url::parse(
        parameters["path"]
            .as_str()
            .context("Iron Dog launch path missing")?,
    )?;
    ensure!(
        path.scheme() == "https"
            && matches!(
                path.host_str(),
                Some("gp.sociumhubeurope.com" | "gp-stage.1x2hubeurope.com")
            )
            && path.path() == "/f1x2games/"
            && path.query().is_none()
            && path.fragment().is_none()
            && path.username().is_empty()
            && path.password().is_none()
            && path.port().is_none_or(|p| p == 443),
        "Iron Dog native demo gateway is not the documented authority"
    );
    Ok(GatewayBinding {
        game_id: expected_game,
        gateway: path.join("/gateway/")?.into(),
        guest_path: path.join("getGuestID.jsp")?.into(),
        morphic: launch["data"]["gamePath"]
            .as_str()
            .is_some_and(|p| p.starts_with("games/")),
    })
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "type", content = "id", rename_all = "snake_case")]
pub enum MorphicMode {
    Normal,
    Purchase(String),
    Ante(String),
}

#[derive(Debug, Serialize)]
pub struct MorphicQuote {
    pub game_id: u64,
    pub stake_unit: Value,
    pub stake_currency: Decimal,
    pub cost_unit: String,
    pub cost_currency: String,
    pub modifiers: Value,
    pub repeat_modifiers: bool,
}

/// Uses only current native offers. Cost in currency is the chosen denomination
/// times the native multiplier, avoiding rounded division of unit values.
pub fn quote_morphic(setup: &Value, game: u64, mode: &MorphicMode) -> Result<MorphicQuote> {
    ensure!(
        setup["account"]["real"] == false
            && setup["account"]["currency"] == "FUN"
            && integer(&setup["account"]["gameID"])? == game,
        "Iron Dog Morphic setup is not the requested FUN game"
    );
    ensure!(
        setup["bet"]["settled"] != false,
        "Iron Dog setup has an open native round"
    );
    let values = setup["config"]["betValues"]
        .as_array()
        .context("Iron Dog betValues missing")?;
    let mut minimum: Option<(Decimal, Decimal, &Value)> = None;
    for value in values {
        let unit = amount(&value["unit"])?;
        let currency = amount(&value["currency"])?;
        ensure!(
            unit > Decimal::ZERO && currency > Decimal::ZERO,
            "Iron Dog zero native denomination"
        );
        if minimum.as_ref().is_none_or(|previous| unit < previous.0) {
            minimum = Some((unit, currency, value));
        }
    }
    let (unit, currency, value) = minimum.context("Iron Dog native denomination list empty")?;
    let mut multiplier = Decimal::ONE;
    let mut modifiers = json!({});
    let mut repeat = false;
    match mode {
        MorphicMode::Normal => {}
        MorphicMode::Purchase(id) => {
            let option = &setup["config"]["betFeatures"]["buyIn"]["options"][id];
            ensure!(
                option["enabled"] == true,
                "Iron Dog purchase is not enabled"
            );
            multiplier = amount(&option["timesStake"])?;
            ensure!(
                multiplier > Decimal::ZERO,
                "Iron Dog purchase multiplier must be positive"
            );
            let cost = exact_mul(unit, multiplier)?;
            ensure!(
                cost >= amount(&option["minStake"]["unit"])?
                    && cost <= amount(&option["maxStake"]["unit"])?,
                "Iron Dog purchase outside native bounds"
            );
            modifiers =
                json!({"buyInId":id,"buyInCost":serde_json::from_str::<Value>(&cost.to_string())?});
        }
        MorphicMode::Ante(id) => {
            ensure!(
                !id.is_empty() && !id.contains(','),
                "Iron Dog only a single native ante is documented"
            );
            let option = &setup["config"]["anteBets"][id];
            multiplier = amount(&option["multiplier"])?;
            ensure!(
                multiplier > Decimal::ZERO,
                "Iron Dog ante multiplier must be positive"
            );
            modifiers = json!({"anteBets":[id],"totalStake":
                serde_json::from_str::<Value>(&exact_mul(unit,multiplier)?.to_string())?});
            repeat = true;
        }
    }
    Ok(MorphicQuote {
        game_id: game,
        stake_unit: value["unit"].clone(),
        stake_currency: currency,
        cost_unit: exact_mul(unit, multiplier)?.to_string(),
        cost_currency: exact_mul(currency, multiplier)?.to_string(),
        modifiers,
        repeat_modifiers: repeat,
    })
}

/// Partial native receipt. `wallet_matches=None` is intentionally different
/// from true: published FUN sessions sometimes omit their initial/final wallet.
#[derive(Debug, Serialize)]
pub struct NativeReceipt {
    pub native_round_id: String,
    pub cost: String,
    pub payout: String,
    pub balance_before: Option<String>,
    pub balance_after: Option<String>,
    pub wallet_matches: Option<bool>,
    pub native_closed: bool,
    pub final_currency_observed: bool,
}

fn receipt(
    root: String,
    before: Option<Decimal>,
    after: Option<Decimal>,
    cost: Decimal,
    payout: Decimal,
    currency_seen: bool,
) -> NativeReceipt {
    NativeReceipt {
        native_round_id: root,
        cost: cost.to_string(),
        payout: payout.to_string(),
        balance_before: before.map(|v| v.to_string()),
        balance_after: after.map(|v| v.to_string()),
        wallet_matches: before
            .zip(after)
            .map(|(b, a)| wallet_matches(b, a, cost, payout)),
        native_closed: true,
        final_currency_observed: currency_seen,
    }
}

/// Morphic award is read exactly once from the final cumulative state.win.
/// Do not add cumulative values from continuation replies a second time.
pub fn reconcile_morphic(
    setup: &Value,
    steps: &[Value],
    quote: &MorphicQuote,
) -> Result<NativeReceipt> {
    ensure!(!steps.is_empty(), "Iron Dog Morphic steps missing");
    ensure!(
        setup["account"]["real"] == false
            && setup["account"]["currency"] == "FUN"
            && integer(&setup["account"]["gameID"])? == quote.game_id,
        "Iron Dog Morphic demo owner missing"
    );
    let mut root: Option<String> = None;
    for (index, step) in steps.iter().enumerate() {
        let bet = &step["bet"];
        let id = identity(bet.get("betRecordID").unwrap_or(&bet["id"]))?;
        ensure!(
            root.as_ref().is_none_or(|root| *root == id),
            "Iron Dog Morphic round identity changed"
        );
        root = Some(id);
        ensure!(
            bet["settled"].as_bool() == Some(index + 1 == steps.len()),
            "Iron Dog Morphic intermediate/final settled marker differs"
        );
        if let Some(currency) = step["account"].get("currency") {
            ensure!(currency == "FUN", "Iron Dog Morphic currency changed");
        }
        if let Some(real) = step["account"].get("real") {
            ensure!(real == false, "Iron Dog Morphic demo identity changed");
        }
        if let Some(game_id) = step["account"].get("gameID") {
            ensure!(
                integer(game_id)? == quote.game_id,
                "Iron Dog Morphic account game changed"
            );
        }
        // _irondog_morphic carries these exact initial account values in
        // every spin's common payload. Replies may omit them; an explicit
        // contradictory echo cannot silently replace that same owner.
        for field in ["accountID", "engineSessionID"] {
            if let Some(actual) = step["account"].get(field) {
                let expected = setup["account"]
                    .get(field)
                    .filter(|value| !value.is_null())
                    .with_context(|| format!("Iron Dog Morphic initial {field} missing"))?;
                ensure!(
                    actual == expected,
                    "Iron Dog Morphic native account/session owner changed"
                );
            }
        }
    }
    let final_step = steps
        .last()
        .context("Iron Dog Morphic final step missing")?;
    let first_bet = &steps[0]["bet"];
    ensure!(
        amount(&first_bet["stake"]["unit"])? == amount(&quote.stake_unit)?
            && amount(&first_bet["stake"]["currency"])? == quote.stake_currency,
        "Iron Dog native stake differs from the quote"
    );
    let charged = if let Some(buy_id) = quote.modifiers.get("buyInId") {
        ensure!(
            first_bet.get("buyInId") == Some(buy_id),
            "Iron Dog native purchase differs from the quote"
        );
        &first_bet["buyInCost"]
    } else {
        let expected_ante = quote.modifiers.get("anteBets").and_then(Value::as_array);
        let actual_ante = first_bet["anteBets"]
            .as_array()
            .context("Iron Dog native ante echo missing")?;
        ensure!(
            expected_ante.map_or(actual_ante.is_empty(), |ante| ante == actual_ante)
                && first_bet["buyInId"].is_null()
                && first_bet["buyInCost"].is_null(),
            "Iron Dog native mode differs from the quote"
        );
        &first_bet["totalStake"]
    };
    ensure!(
        amount(&charged["unit"])? == decimal(&quote.cost_unit)?
            && amount(&charged["currency"])? == decimal(&quote.cost_currency)?,
        "Iron Dog native cost differs from the quote"
    );
    let win = &final_step["state"]["win"];
    let payout = if win.get("total").is_some_and(Value::is_object) {
        amount(&win["total"]["currency"])?
    } else {
        amount(&win["currency"])?
    };
    let cost = decimal(&quote.cost_currency)?;
    ensure!(
        cost > Decimal::ZERO,
        "Iron Dog Morphic cost must be positive"
    );
    Ok(receipt(
        root.context("Iron Dog Morphic root missing")?,
        optional_amount(&setup["account"]["balance"])?,
        optional_amount(&final_step["bet"]["balance"])?,
        cost,
        payout,
        final_step["account"]["currency"] == "FUN",
    ))
}

fn matches_stake_fields(request: &Value, quote: &MorphicQuote, first: bool) -> bool {
    amount(&request["stake"]).ok() == amount(&quote.stake_unit).ok()
        && request.get("force").is_none()
        && ["buyInId", "buyInCost", "anteBets", "totalStake"]
            .iter()
            .all(|key| {
                let expected = if first || quote.repeat_modifiers {
                    quote.modifiers.get(key)
                } else {
                    None
                };
                request.get(key) == expected
            })
}

/// Audit a saved Morphic round without opening a session or changing its status.
pub(crate) fn audit_saved_round(store: &Store, round_id: &str) -> Result<NativeReceipt> {
    let round = store.round(round_id)?;
    ensure!(
        round.spec.provider == "irondog" && matches!(round.spec.game.as_str(), "90110" | "90140"),
        "expected a supported Iron Dog Morphic round"
    );
    let mode = selection(&round.spec.kind, &round.spec.mode)
        .context("unreviewed Iron Dog saved selector")?;
    let game = round.spec.game.parse()?;
    let exchanges = store.exchanges(round_id)?;
    let start = exchanges
        .iter()
        .position(|x| x.request.label == "gateway_init")
        .context("Iron Dog gateway initialization missing")?;
    let mut exchanges = exchanges[start..].iter();
    let mut read = |label: &str, financial: bool, status: u16| -> Result<(Value, Value)> {
        let row = exchanges
            .next()
            .context("Iron Dog saved exchange missing")?;
        let response = row
            .response
            .as_ref()
            .context("Iron Dog saved response missing")?;
        ensure!(
            row.request.label == label
                && row.request.financial == financial
                && row.request.method == "POST"
                && row.error.is_none()
                && response.status == status,
            "unexpected Iron Dog saved exchange"
        );
        ensure!(
            sha256(&serde_json::to_vec(&row.request)?) == row.request_sha256
                && row.response_sha256.as_deref()
                    == Some(sha256(&serde_json::to_vec(response)?).as_str()),
            "Iron Dog saved exchange hash differs"
        );
        let request = if label == "gateway_init" {
            Value::Null
        } else {
            serde_json::from_str(&row.request.body)?
        };
        Ok((request, serde_json::from_str(&response.body)?))
    };
    let (_, init) = read("gateway_init", false, 201)?;
    let mut token = text(&init, "token")?.to_owned();
    let mut decode = |request: Value, response: Value| -> Result<(Value, Value)> {
        let request = decrypt(&token, text(&request, "data")?)?;
        let envelope = decrypt(&token, text(&response["response"], "data")?)?;
        let native: Value = serde_json::from_str(text(&envelope, "data")?)?;
        ensure!(native["success"] == true, "saved Iron Dog command rejected");
        token = text(&envelope, "token")?.to_owned();
        Ok((request, native["payload"].clone()))
    };
    let (request, response) = read("setup", false, 200)?;
    let (setup_request, setup) = decode(request, response)?;
    ensure!(
        setup_request["realMode"] == false && integer(&setup_request["gameID"])? == game,
        "saved Iron Dog setup does not match the requested demo"
    );
    let quote = quote_morphic(&setup, game, &mode)?;
    let mut steps = Vec::new();
    loop {
        let (request, response) = read("spin", true, 200)?;
        let (request, response) = decode(request, response)?;
        ensure!(
            request["realMode"] == false
                && integer(&request["gameID"])? == game
                && request["accountID"] == setup["account"]["accountID"]
                && request["engineSessionID"] == setup["account"]["engineSessionID"]
                && matches_stake_fields(&request, &quote, steps.is_empty()),
            "saved Iron Dog spin does not match the reviewed mode"
        );
        let settled = response["bet"]["settled"]
            .as_bool()
            .context("saved Iron Dog closure marker missing")?;
        steps.push(response);
        if settled {
            break;
        }
    }
    ensure!(
        exchanges.next().is_none(),
        "extra exchanges after saved Iron Dog closure"
    );
    reconcile_morphic(&setup, &steps, &quote)
}

#[cfg(test)]
mod transport_tests {
    use super::*;

    #[test]
    fn gateway_round_trips_aes256_and_rejects_invalid_envelopes() {
        let key = "0123456789abcdef0123456789abcdef";
        let message = json!({"success":true,"payload":{"gameID":90110}});
        let ciphertext = encrypt(key, &serde_json::to_vec(&message).unwrap()).unwrap();
        assert_eq!(decrypt(key, &ciphertext).unwrap(), message);
        assert!(decrypt("wrong length", &ciphertext).is_err());
        assert!(decrypt(key, "abc").is_err());
    }

    #[test]
    fn settled_round_must_echo_the_quoted_native_stake_and_cost() {
        let setup = json!({"account":{"real":false,"currency":"FUN","gameID":90110,"balance":5000},
            "config":{"betValues":[{"unit":10,"currency":0.1}]}});
        let quote = quote_morphic(&setup, 90110, &MorphicMode::Normal).unwrap();
        let mut closed = json!({"bet":{"betRecordID":"round-1","settled":true,"balance":null,
            "stake":{"unit":10,"currency":0.1},"totalStake":{"unit":10,"currency":0.1},
            "anteBets":[],"buyInId":null,"buyInCost":null},"state":{"win":{"total":{"currency":0}}}});
        let receipt = reconcile_morphic(&setup, &[closed.clone()], &quote).unwrap();
        assert!(receipt.native_closed);
        assert_eq!(receipt.wallet_matches, None);
        closed["bet"]["totalStake"]["unit"] = json!(20);
        assert!(reconcile_morphic(&setup, &[closed], &quote).is_err());
    }

    #[test]
    fn morphic_purchase_uses_the_purchase_cost_not_the_base_stake() {
        let setup = json!({"account":{"real":false,"currency":"FUN","gameID":90140,"balance":5000},
            "config":{"betValues":[{"unit":20,"currency":0.2}],"betFeatures":{"buyIn":{"options":{
                "0":{"enabled":true,"timesStake":60,"minStake":{"unit":1200},"maxStake":{"unit":10000}}}}}}});
        let quote = quote_morphic(&setup, 90140, &MorphicMode::Purchase("0".into())).unwrap();
        let wire = json!({"stake":20,"buyInId":"0","buyInCost":1200});
        assert!(matches_stake_fields(&wire, &quote, true));
        assert!(!matches_stake_fields(&wire, &quote, false));
        assert!(matches_stake_fields(&json!({"stake":20}), &quote, false));
        assert!(!matches_stake_fields(
            &json!({"stake":20,"force":true}),
            &quote,
            false
        ));
        let mut closed = json!({"bet":{"betRecordID":"round-1","settled":true,"balance":null,
            "stake":{"unit":20,"currency":0.2},"totalStake":{"unit":20,"currency":0.2},
            "anteBets":[],"buyInId":"0","buyInCost":{"unit":1200,"currency":12}},
            "state":{"win":{"total":{"currency":2.5}}}});
        let receipt = reconcile_morphic(&setup, &[closed.clone()], &quote).unwrap();
        assert_eq!(decimal(&receipt.cost).unwrap(), Decimal::from(12));
        assert_eq!(decimal(&receipt.payout).unwrap(), Decimal::new(25, 1));
        closed["bet"]["buyInId"] = json!("1");
        assert!(reconcile_morphic(&setup, &[closed], &quote).is_err());
    }
}
