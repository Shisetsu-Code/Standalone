use crate::{
    context::{DecodedFrame, NativeSocket, RunContext, SocketPayload},
    model::{Game, Mode, ModeKind, RoundOutcome, WireRequest, WireResponse, decimal, now_ms},
};
use anyhow::{Context, Result, ensure};
use rust_decimal::Decimal;
use serde::Deserialize;
use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::OnceLock};
use url::Url;
use uuid::Uuid;

const ORIGIN: &str = "https://showcase.evo-games.com";

#[derive(Deserialize)]
struct Binding {
    table_id: String,
    game_type: String,
    client_version: String,
    config_version: String,
    modes: Vec<String>,
    #[serde(default)]
    v1_modes: BTreeMap<String, V1Mode>,
}

#[derive(Deserialize)]
struct V1Mode {
    bet_code: String,
    game: Value,
    factor: String,
    factor_field: Option<String>,
    asset: String,
    integrity: String,
    source_sha256: String,
    frontend_app: String,
    game_version: String,
    jungle_choice: Option<JungleChoice>,
    finn_choice: Option<FinnChoice>,
}

#[derive(Deserialize)]
struct FinnChoice {
    id: String,
    keys: u64,
}

impl FinnChoice {
    fn keys(&self, state: &Value) -> Result<u64> {
        let game = &state["game"];
        let menu = game["freeSpins"]
            .as_array()
            .context("Finn choice menu missing")?;
        for (id, keys) in [(self.id.as_str(), self.keys), ("randomwilds", 1)] {
            let mut matching = menu.iter().filter(|offer| offer["id"] == id);
            ensure!(
                matching
                    .next()
                    .is_some_and(|offer| offer["keysToUnlock"] == keys)
                    && matching.next().is_none(),
                "Finn choice threshold changed"
            );
        }
        game["totalKeys"]
            .as_u64()
            .context("Finn native key balance missing")
    }

    fn select(&self, state: &Value, allow_preparation: bool) -> Result<&str> {
        let keys = self.keys(state)?;
        ensure!(keys >= 1, "Finn did not open a reviewed choice");
        ensure!(
            keys >= self.keys || allow_preparation,
            "Finn requested choice became locked during play"
        );
        Ok(if keys >= self.keys {
            &self.id
        } else {
            "randomwilds"
        })
    }
}

#[derive(Deserialize)]
struct JungleChoice {
    animal: String,
    gamble: bool,
}

impl JungleChoice {
    fn continuation(&self, response: &Value, stage: usize) -> Result<Value> {
        ensure!(
            matches!(self.animal.as_str(), "3" | "4" | "5" | "6" | "7"),
            "unreviewed Jungle Spirit animal"
        );
        let animal = response["game"]
            .get("featuredAnimal")
            .context("Jungle Spirit animal state missing")?;
        let payload = match stage {
            0 if animal.is_null() => json!({"featureBuy":false,"animal":self.animal}),
            1 if animal["id"]
                .as_u64()
                .is_some_and(|id| id.to_string() == self.animal)
                || animal["id"].as_str() == Some(self.animal.as_str()) =>
            {
                json!({"featureBuy":false,"gamble":self.gamble})
            }
            _ => anyhow::bail!("Jungle Spirit did not acknowledge the reviewed decision sequence"),
        };
        Ok(json!({"continue":{"game":payload}}))
    }
}

impl V1Mode {
    fn asset_url(&self, launch: &super::netent_launch::DemoLaunch) -> Result<Url> {
        ensure!(
            launch.config["frontend_app"] == self.frontend_app
                && launch.config["game_version"] == self.game_version,
            "Horizon game release changed"
        );
        ensure!(
            self.asset.starts_with("ne")
                && self.asset.ends_with(".js")
                && self
                    .asset
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.')),
            "invalid Horizon source binding"
        );
        let path = format!("js/{}", self.asset);
        let sri = regex::Regex::new(&format!(
            r#""{}"\s*:\s*"{}""#,
            regex::escape(&path),
            regex::escape(&self.integrity)
        ))?;
        ensure!(
            sri.is_match(&launch.frontend_body),
            "Horizon client no longer advertises the reviewed source"
        );
        Ok(launch.frontend.join(&path)?)
    }
}

fn binding(game: &str) -> Option<&'static Binding> {
    static BINDINGS: OnceLock<BTreeMap<String, Binding>> = OnceLock::new();
    BINDINGS
        .get_or_init(|| {
            serde_json::from_slice(include_bytes!("../../bindings/netent-horizon.json"))
                .expect("reviewed NetEnt Horizon contracts")
        })
        .get(game)
}

pub fn supports(game: &Game, mode: &Mode) -> bool {
    matches!(
        mode.kind,
        ModeKind::Normal
            | ModeKind::Purchase
            | ModeKind::Variant
            | ModeKind::AnteBet
            | ModeKind::Booster
    ) && binding(&game.id).is_some_and(|row| row.modes.contains(&mode.key))
}

pub(crate) fn requires_progression(game: &Game, mode: &Mode) -> bool {
    binding(&game.id)
        .and_then(|entry| entry.v1_modes.get(&mode.key))
        .is_some_and(|mode| mode.finn_choice.is_some())
}

fn socket_url(config: &Value, binding: &Binding, wallet: &str) -> Result<Url> {
    ensure!(
        wallet.starts_with("demo-")
            && config["userType"] == 0
            && config["table_id"] == binding.table_id
            && config["game_provider"] == "netent"
            && config["game_engine"] == "slots",
        "invalid Horizon demo config"
    );
    let path = config["wsUrl"]
        .as_str()
        .filter(|url| url.starts_with("/public/horizon?"))
        .context("unexpected Horizon socket template")?;
    let mut url = Url::parse("wss://showcase.evo-games.com")?.join(path)?;
    let parts: Vec<_> = url.query_pairs().collect();
    let query: BTreeMap<_, _> = parts
        .iter()
        .map(|(k, v)| (k.as_ref(), v.as_ref()))
        .collect();
    ensure!(
        parts.len() == 3
            && query.get("tableId").copied() == Some(binding.table_id.as_str())
            && query.get("gameType").copied() == Some(binding.game_type.as_str())
            && query.get("EVOSESSIONID").is_some_and(|s| !s.is_empty()
                && s.len() <= 4096
                && !s.chars().any(char::is_control))
            && url.fragment().is_none(),
        "Horizon socket game or session differs from its launch"
    );
    let first = Uuid::new_v4().simple().to_string();
    let second = Uuid::new_v4().simple().to_string();
    let instance = format!("{}-{}-{}", &first[..6], &first[6..22], &second[..16]);
    url.query_pairs_mut()
        .append_pair("balanceId", wallet)
        .append_pair("instance", &instance)
        .append_pair("client_version", &binding.client_version);
    Ok(url)
}

fn money(value: &Value) -> Result<Decimal> {
    if let Some(text) = value.as_str() {
        decimal(text)
    } else {
        decimal(&value.to_string())
    }
}

fn settled_payout(wire: &Value) -> Result<Decimal> {
    ensure!(wire.is_number(), "Horizon terminal payout missing");
    let printed = wire.to_string();
    // A few native totals are serialized with more digits than Decimal can
    // store. They are accepted only on the configured cent precision lattice.
    let native = money(wire).or_else(|_| {
        printed
            .parse::<Decimal>()
            .context("invalid Horizon terminal payout")
    })?;
    let cents = native.round_dp(2);
    let mantissa = printed.split(['e', 'E']).next().unwrap_or_default();
    ensure!(
        native >= Decimal::ZERO
            && (native - cents).abs() < Decimal::new(1, 24)
            && (!cents.is_zero() || !mantissa.bytes().any(|b| matches!(b, b'1'..=b'9'))),
        "Horizon terminal payout differs from reported currency precision"
    );
    Ok(cents)
}

fn quote(initial: &Value, mode: &str, reviewed: Option<&V1Mode>) -> Result<(Value, Decimal)> {
    ensure!(
        initial["nextAction"] == "spin",
        "Horizon demo already has an open round"
    );
    let offers = initial["stakeIncrements"]
        .as_array()
        .context("Horizon stake menu missing")?;
    let mut minimum = None;
    for wire in offers {
        ensure!(wire.is_number(), "Horizon stake must be numeric");
        let amount = money(wire)?;
        ensure!(amount > Decimal::ZERO, "invalid Horizon stake");
        if minimum
            .as_ref()
            .is_none_or(|(current, _)| amount < *current)
        {
            minimum = Some((amount, wire));
        }
    }
    let (stake, wire) = minimum.context("empty Horizon stake menu")?;
    let mut play = json!({"stake":wire,"betCode":mode});
    let protocol = &initial["protocolVersion"];
    let v1 = protocol.is_null() || protocol == 1;
    let factor = if let Some(reviewed) = reviewed {
        ensure!(
            v1 && initial["game"]["featureBuyEnabled"] == true,
            "Horizon source-reviewed v1 mode is disabled"
        );
        let factor = decimal(&reviewed.factor)?;
        if let Some(field) = &reviewed.factor_field {
            let value = field
                .split('.')
                .try_fold(&initial["game"], |object, key| object.get(key))
                .context("Horizon v1 native mode price missing")?;
            ensure!(
                money(value)? == factor,
                "Horizon v1 native mode price changed"
            );
        }
        play["betCode"] = json!(reviewed.bet_code);
        play["game"] = reviewed.game.clone();
        factor
    } else if protocol == 2 {
        ensure!(
            mode == "Spin" || initial["featuresEnabled"] == true,
            "Horizon feature is disabled"
        );
        money(&initial["costFactors"][mode])?
    } else {
        ensure!(
            v1 && mode == "Spin",
            "Horizon mode requires its reviewed protocol"
        );
        Decimal::ONE
    };
    ensure!(
        factor > Decimal::ZERO,
        "nonpositive Horizon native mode factor"
    );
    let cost = stake.checked_mul(factor).context("Horizon cost overflow")?;
    Ok((play, cost))
}

struct Ledger<'a> {
    wallet: &'a str,
    table: &'a str,
    currency: &'a str,
    current: Option<(u64, Decimal)>,
    opening: Option<Decimal>,
    debit: Option<Decimal>,
    ping_at: u128,
}

impl Ledger<'_> {
    fn decode(&mut self, frame: &SocketPayload) -> Result<(Value, Vec<SocketPayload>)> {
        let SocketPayload::Text(text) = frame else {
            anyhow::bail!("unexpected binary Horizon frame")
        };
        let packet: Value = serde_json::from_str(text)?;
        let body = &packet["payload"];
        match body["type"].as_str() {
            Some("connection.kickout" | "SlotsError" | "error" | "Error") => {
                anyhow::bail!("Horizon rejected the native action")
            }
            Some("balanceUpdated") => {
                let args = &body["args"];
                ensure!(
                    args["tableId"] == self.table && args["currencyCode"] == self.currency,
                    "Horizon wallet context changed"
                );
                let mut wallets = args["balances"]
                    .as_array()
                    .context("Horizon wallet list missing")?
                    .iter()
                    .filter(|v| v["id"].as_str().is_some_and(|id| id.starts_with("demo-")));
                let wallet = wallets.next().context("Horizon demo wallet missing")?;
                ensure!(
                    wallet["id"] == self.wallet && wallets.next().is_none(),
                    "Horizon demo wallet identity changed"
                );
                let version = wallet["version"]
                    .as_u64()
                    .context("Horizon wallet version missing")?;
                let amount = money(&wallet["amount"])?;
                ensure!(
                    amount >= Decimal::ZERO
                        && self
                            .current
                            .is_none_or(|(prior, last)| version > prior
                                || (version == prior && amount == last)),
                    "Horizon wallet update is out of order"
                );
                self.current = Some((version, amount));
                if self.debit.is_none() && self.opening.is_some_and(|opening| opening != amount) {
                    self.debit = Some(amount);
                }
            }
            _ => {}
        }
        let now = now_ms() as u128;
        let replies = if now >= self.ping_at {
            self.ping_at = now + 5000;
            vec![SocketPayload::Text(
                json!({"recipient":"ping-pong","payload":{
                "id":short_id(),"type":"metrics.ping","args":{"t":now}}})
                .to_string(),
            )]
        } else {
            Vec::new()
        };
        Ok((packet, replies))
    }

    fn balance(&self) -> Option<Decimal> {
        self.current.map(|(_, amount)| amount)
    }
}

fn short_id() -> String {
    Uuid::new_v4().simple().to_string()[..10].to_owned()
}

async fn call(
    ctx: &RunContext,
    socket: &mut NativeSocket,
    ledger: &mut Ledger<'_>,
    label: &str,
    details: Value,
) -> Result<Value> {
    let id = Uuid::new_v4().to_string();
    let packet = json!({"id":id,"recipient":"rng-slots","payload":{"id":short_id(),"type":"SlotsCall","details":details}});
    ctx.ws_codec_controlled(
        socket,
        label,
        SocketPayload::Text(packet.to_string()),
        true,
        None,
        |frame| {
            let (packet, replies) = ledger.decode(frame)?;
            let body = &packet["payload"];
            let mut values = Vec::new();
            if body["type"] == "SlotsResult" && packet["replyTo"] == id {
                let result = &body["details"]["params"];
                ensure!(result.is_object(), "Horizon result payload missing");
                values.push(result.clone());
            }
            Ok(DecodedFrame { values, replies })
        },
    )
    .await
}

pub async fn execute(
    ctx: &RunContext,
    game: &Game,
    mode: &Mode,
    budget: u64,
) -> Result<RoundOutcome> {
    let binding = binding(&game.id).context("unreviewed Horizon game")?;
    let launch = super::netent_launch::open_config(
        ctx,
        &game.id,
        &binding.table_id,
        "horizon",
        &binding.config_version,
    )
    .await?;
    let selector = binding.v1_modes.get(&mode.key);
    if let Some(reviewer) = selector {
        let url = reviewer.asset_url(&launch)?;
        let source = ctx
            .get("netent_horizon_reviewed_source", url.as_str())
            .await?;
        ensure!(
            source.status == 200
                && crate::model::sha256(source.body.as_bytes()) == reviewer.source_sha256,
            "Horizon reviewed bundle changed or is unavailable"
        );
    }
    let wallet = &launch.wallet;
    let url = socket_url(&launch.config, binding, wallet)?;
    ensure!(
        launch.config["currencyDecimals"] == 2,
        "Horizon currency precision changed"
    );
    let currency = launch.config["currencyCode"]
        .as_str()
        .filter(|c| c.len() == 3 && c.bytes().all(|b| b.is_ascii_uppercase()))
        .context("Horizon currency missing")?;
    let mut ledger = Ledger {
        wallet,
        table: &binding.table_id,
        currency,
        current: None,
        opening: None,
        debit: None,
        ping_at: 0,
    };
    let mut socket = ctx
        .websocket(url.as_str(), ORIGIN, None, BTreeMap::new())
        .await?;
    let app = json!({"id":Uuid::new_v4().to_string(),"recipient":"horizon","payload":{"type":"AppInfo","recipient":"rng-slots"}});
    let mut initial = None;
    let setup = ctx
        .ws_codec_controlled(
            &mut socket,
            "netent_horizon_app_info",
            SocketPayload::Text(app.to_string()),
            false,
            None,
            |frame| {
                let (packet, replies) = ledger.decode(frame)?;
                let body = &packet["payload"];
                if body["type"] == "SlotsResult"
                    && body["details"]["params"]["stakeIncrements"].is_array()
                {
                    initial = Some(body["details"]["params"].clone());
                }
                let values = if ledger.balance().is_some() {
                    initial.take().into_iter().collect()
                } else {
                    Vec::new()
                };
                Ok(DecodedFrame { values, replies })
            },
        )
        .await?;
    let (play, cost) = quote(&setup, &mode.key, selector)?;
    let finn = selector.and_then(|reviewed| reviewed.finn_choice.as_ref());
    ensure!(
        finn.is_none() || (1..=100).contains(&budget),
        "Finn prerequisite budget is missing or invalid"
    );
    ctx.save_session(
        &json!({"socket":url.as_str(),"demo_wallet":wallet,"table_id":binding.table_id}),
    )?;
    let mut keys = finn
        .map(|choice| choice.keys(&setup))
        .transpose()?
        .unwrap_or(0);
    let mut previous = setup["gameRoundId"].as_str().map(str::to_owned);
    let mut preparations = Vec::new();
    let mut remaining_steps = ctx.max_steps();
    loop {
        if let Some(choice) = finn {
            ensure!(
                keys >= choice.keys || (preparations.len() as u64) < budget,
                "Finn prerequisite budget exhausted after {} closed purchases",
                preparations.len()
            );
        }
        let request = HorizonPlay {
            details: &play,
            cost,
            previous: previous.as_deref(),
            selector,
            allow_preparation: finn.is_some_and(|choice| keys < choice.keys),
        };
        let (mut outcome, terminal) =
            settle_round(ctx, &mut socket, &mut ledger, request, &mut remaining_steps).await?;
        let Some(wanted) = finn else {
            return Ok(outcome);
        };
        if outcome.native_data["selection"] == wanted.id {
            outcome.native_data["preparation_rounds"] = json!(preparations);
            return Ok(outcome);
        }
        // Persist each closed root before another paid command, including when
        // the campaign stops later on a locked choice or a transport problem.
        let receipt =
            json!({"operation":"buy_bonus","purpose":"finn_key_progression","outcome":outcome});
        let ordinal = ctx.store.start_exchange(
            &ctx.round_id,
            &WireRequest {
                label: "netent_finn_preparation_receipt".into(),
                transport: "journal".into(),
                method: "RECORD".into(),
                url: String::new(),
                headers: BTreeMap::new(),
                body: String::new(),
                financial: false,
            },
        )?;
        ctx.store.finish_exchange(
            &ctx.round_id,
            ordinal,
            &WireResponse {
                status: 0,
                headers: BTreeMap::from([("x-evidencia-transport".into(), "journal".into())]),
                body: receipt.to_string(),
                set_cookies: Vec::new(),
            },
        )?;
        preparations.push(receipt);
        previous = outcome.native_round_id.take();
        let next = terminal["game"]["totalKeys"]
            .as_u64()
            .context("Finn closing key balance missing")?;
        ensure!(
            next > keys,
            "Finn closed preparation without key progression"
        );
        keys = next;
    }
}

struct HorizonPlay<'a> {
    details: &'a Value,
    cost: Decimal,
    previous: Option<&'a str>,
    selector: Option<&'a V1Mode>,
    allow_preparation: bool,
}

async fn settle_round(
    ctx: &RunContext,
    socket: &mut NativeSocket,
    ledger: &mut Ledger<'_>,
    request: HorizonPlay<'_>,
    remaining: &mut usize,
) -> Result<(RoundOutcome, Value)> {
    let HorizonPlay {
        details: play,
        cost,
        previous,
        selector,
        allow_preparation,
    } = request;
    let before = ledger.balance().context("Horizon opening credit missing")?;
    ensure!(before >= cost, "insufficient Horizon demo credit");
    ensure!(*remaining > 0, "Horizon action budget exhausted");
    *remaining -= 1;
    ledger.opening = Some(before);
    ledger.debit = None;
    let mut terminal = call(
        ctx,
        socket,
        ledger,
        "netent_horizon_play",
        json!({"play":play}),
    )
    .await?;
    let round = terminal["gameRoundId"]
        .as_str()
        .filter(|v| !v.is_empty())
        .context("Horizon round identifier missing")?
        .to_owned();
    ensure!(
        Some(round.as_str()) != previous,
        "Horizon round identifier did not advance"
    );
    let choice = selector.and_then(|reviewed| reviewed.jungle_choice.as_ref());
    let finn = selector.and_then(|reviewed| reviewed.finn_choice.as_ref());
    let mut selection = None;
    let mut decision_stage = 0;
    for _ in 1..ctx.max_steps().min(500) {
        if terminal["nextAction"] == "spin" {
            break;
        }
        let details = match terminal["nextAction"].as_str() {
            Some("respin" | "freespin" | "featureexecution" | "jackpotpayout") => {
                json!({"continue":{}})
            }
            Some("userdecision") if choice.is_some() => {
                let wire = choice.unwrap().continuation(&terminal, decision_stage)?;
                decision_stage += 1;
                wire
            }
            Some("userdecision") if finn.is_some() && selection.is_none() => {
                let selected = finn.unwrap().select(&terminal, allow_preparation)?;
                selection = Some(selected);
                json!({"continue":{"game":{"select":selected}}})
            }
            _ => anyhow::bail!("Horizon continuation requires an unreviewed choice"),
        };
        ensure!(*remaining > 0, "Horizon action budget exhausted");
        *remaining -= 1;
        terminal = call(ctx, socket, ledger, "netent_horizon_continue", details).await?;
        ensure!(
            terminal["gameRoundId"] == round,
            "Horizon changed round during continuation"
        );
    }
    ensure!(
        choice.is_none() || decision_stage == 2,
        "Jungle Spirit did not complete both requested decisions"
    );
    ensure!(
        finn.is_none() || selection.is_some(),
        "Finn did not execute the requested decision sequence"
    );
    ensure!(
        terminal["nextAction"] == "spin"
            && (terminal["wins"]["pending"].is_null()
                || money(&terminal["wins"]["pending"])? == Decimal::ZERO),
        "Horizon round closure not acknowledged"
    );
    let reported = &terminal["wins"]["total"];
    let win = settled_payout(reported)?;
    let expected = before
        .checked_sub(cost)
        .and_then(|v| v.checked_add(win))
        .context("Horizon amount overflow")?;
    if ledger.balance() != Some(expected) {
        ctx.ws_exchange(
            socket,
            "netent_horizon_wallet_close",
            None,
            true,
            None,
            |frame| {
                let (_, replies) = ledger.decode(frame)?;
                Ok(DecodedFrame {
                    values: if ledger.balance() == Some(expected) {
                        vec![json!(true)]
                    } else {
                        Vec::new()
                    },
                    replies,
                })
            },
        )
        .await?;
    }
    let debit = ledger
        .debit
        .context("Horizon did not report a separate debit")?;
    let after = ledger.balance().context("Horizon closing wallet missing")?;
    ensure!(
        win >= Decimal::ZERO && before.checked_sub(debit) == Some(cost) && after == expected,
        "Horizon independent debit, payout and balance do not reconcile"
    );
    let mut native_data =
        json!({"play":play,"debit_balance":debit.to_string(),"reported_payout":reported});
    if let Some(selected) = selection {
        native_data["selection"] = json!(selected);
        native_data["closing_keys"] = terminal["game"]["totalKeys"].clone();
    }
    let outcome = RoundOutcome {
        native_round_id: Some(round),
        currency: ledger.currency.into(),
        currency_source: "native_response".into(),
        monetary_unit: "major".into(),
        balance_before: before.to_string(),
        balance_after: after.to_string(),
        cost: cost.to_string(),
        payout: win.to_string(),
        native_closed: true,
        checks: BTreeMap::from([
            ("demo_wallet".into(), true),
            ("independent_debit".into(), true),
        ]),
        native_data,
    };
    Ok((outcome, terminal))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn netent_horizon_finn_requires_native_unlock_before_selecting_target() {
        let profile = binding("finn-and-the-candy-spin").unwrap();
        assert_eq!(profile.v1_modes.len(), 4);
        let wanted = profile.v1_modes["FeatureBuy:select=symboltransform"]
            .finn_choice
            .as_ref()
            .unwrap();
        let mut state = json!({"game":{"totalKeys":15,"freeSpins":[
            {"id":"randomwilds","keysToUnlock":1},{"id":"symboltransform","keysToUnlock":16}]}});
        assert_eq!(wanted.select(&state, true).unwrap(), "randomwilds");
        assert!(wanted.select(&state, false).is_err());
        state["game"]["totalKeys"] = json!(16);
        assert_eq!(wanted.select(&state, false).unwrap(), "symboltransform");
        state["game"]["freeSpins"][1]["keysToUnlock"] = json!(15);
        assert!(wanted.select(&state, true).is_err());
    }

    #[test]
    fn netent_horizon_jungle_decisions_follow_same_animal_in_order() {
        let profile = binding("jungle-spirit-megaways").unwrap();
        assert_eq!(profile.v1_modes.len(), 10);
        let choice = profile.v1_modes["FeatureBuy:Cobra:Gamble"]
            .jungle_choice
            .as_ref()
            .unwrap();
        assert_eq!(
            choice
                .continuation(&json!({"game":{"featuredAnimal":null}}), 0)
                .unwrap(),
            json!({"continue":{"game":{"featureBuy":false,"animal":"7"}}})
        );
        assert!(
            choice
                .continuation(&json!({"game":{"featuredAnimal":{"id":3}}}), 1)
                .is_err()
        );
        let acknowledged = json!({"game":{"featuredAnimal":{"id":7}}});
        assert_eq!(
            choice.continuation(&acknowledged, 1).unwrap(),
            json!({"continue":{"game":{"featureBuy":false,"gamble":true}}})
        );
        assert!(choice.continuation(&acknowledged, 2).is_err());
    }

    #[test]
    fn netent_horizon_payout_accepts_only_sub_cent_serialization_noise() {
        let payout = |raw: &str| settled_payout(&serde_json::from_str(raw).unwrap());
        assert_eq!(
            payout("39.74000000000000000000000000000001").unwrap(),
            Decimal::new(3974, 2)
        );
        assert_eq!(
            payout("0.8199999999999999999999999999999999").unwrap(),
            Decimal::new(82, 2)
        );
        assert!(payout("0.82001").is_err());
        assert!(payout("0.00000000000000000000000000000001").is_err());
    }

    #[test]
    fn netent_horizon_socket_uses_only_the_new_demo_launch() {
        let binding = binding("101-candies").unwrap();
        let mut config = json!({"userType":0,"table_id":binding.table_id,"game_provider":"netent","game_engine":"slots",
            "wsUrl":format!("/public/horizon?tableId={}&gameType={}&EVOSESSIONID=fixture", binding.table_id, binding.game_type)});
        let socket = socket_url(&config, binding, "demo-test").unwrap();
        let query: BTreeMap<_, _> = socket.query_pairs().into_owned().collect();
        assert_eq!(query["EVOSESSIONID"], "fixture");
        assert_eq!(query["balanceId"], "demo-test");
        assert_eq!(
            query["instance"]
                .split('-')
                .map(str::len)
                .collect::<Vec<_>>(),
            [6, 16, 16]
        );
        config["wsUrl"] =
            json!("/public/horizon?tableId=wrong&gameType=wrong&EVOSESSIONID=fixture");
        assert!(socket_url(&config, binding, "demo-test").is_err());
    }

    #[test]
    fn netent_horizon_mode_quote_comes_from_reviewed_live_offer() {
        let mut setup = json!({"nextAction":"spin","stakeIncrements":[0.4,0.2],"protocolVersion":2,
            "featuresEnabled":true,"costFactors":{"Spin":1,"FeatureBuy":83.5}});
        let (play, cost) = quote(&setup, "FeatureBuy", None).unwrap();
        assert_eq!(play, json!({"stake":0.2,"betCode":"FeatureBuy"}));
        assert_eq!(cost, Decimal::new(167, 1));
        assert!(quote(&setup, "FeatureBuy2", None).is_err());
        setup["featuresEnabled"] = json!(false);
        assert!(quote(&setup, "FeatureBuy", None).is_err());
    }

    #[test]
    fn netent_horizon_v1_binds_release_and_nested_selector() {
        let reviewed = &binding("buckshot-wilds").unwrap().v1_modes["Spin:BonusBet"];
        let mut launch = super::super::netent_launch::DemoLaunch {
            config: json!({"frontend_app":reviewed.frontend_app,"game_version":reviewed.game_version}),
            wallet: "demo-test".into(),
            frontend: Url::parse("https://showcase.evo-games.com/frontend/evo/r2/").unwrap(),
            frontend_body: format!(r#""js/{}": "{}""#, reviewed.asset, reviewed.integrity),
        };
        assert!(reviewed.asset_url(&launch).is_ok());
        launch.frontend_body.clear();
        assert!(reviewed.asset_url(&launch).is_err());
        let mut setup = json!({"nextAction":"spin","stakeIncrements":[0.4,0.2],
            "game":{"featureBuyEnabled":true,"bonusBetCostFactor":2.5}});
        let (play, cost) = quote(&setup, "Spin:BonusBet", Some(reviewed)).unwrap();
        assert_eq!(
            play,
            json!({"stake":0.2,"betCode":"Spin","game":{"bonusBet":true,"featureBuy":false}})
        );
        assert_eq!(cost, Decimal::new(5, 1));
        setup["game"]["bonusBetCostFactor"] = json!(3);
        assert!(quote(&setup, "Spin:BonusBet", Some(reviewed)).is_err());
    }

    #[test]
    fn netent_horizon_wallet_requires_independent_update_for_exact_owner() {
        let mut ledger = Ledger {
            wallet: "demo-test",
            table: "table",
            currency: "USD",
            current: None,
            opening: Some(Decimal::from(100)),
            debit: None,
            ping_at: u128::MAX,
        };
        let frame = |id: &str, version: u64, amount: u64| {
            SocketPayload::Text(json!({"payload":{
            "type":"balanceUpdated","args":{"tableId":"table","currencyCode":"USD","balances":[{"id":id,"version":version,"amount":amount}]}}}).to_string())
        };
        assert!(ledger.decode(&frame("demo-wrong", 1, 80)).is_err());
        ledger.decode(&frame("demo-test", 1, 100)).unwrap();
        assert!(ledger.debit.is_none());
        ledger.decode(&frame("demo-test", 2, 80)).unwrap();
        ledger.decode(&frame("demo-test", 3, 90)).unwrap();
        assert_eq!(ledger.debit, Some(Decimal::from(80)));
        assert_eq!(ledger.balance(), Some(Decimal::from(90)));
        assert!(ledger.decode(&frame("demo-test", 2, 80)).is_err());
    }
}
