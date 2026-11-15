//! One fresh public Six Feet Under normal round, with durable native transport.
use crate::{
    context::{NativeSocket, RunContext, SocketPayload},
    model::{Game, Mode, ModeKind, RoundOutcome, decimal, wallet_matches},
};
use anyhow::{Context, Result, bail, ensure};
use regex::Regex;
use rust_decimal::Decimal;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use url::Url;
use uuid::Uuid;

const PROTOCOL: &str = "@nolimitcity/game-communication@0.4.1";
const STATIC: &str = "https://demo.nolimitcdn.com";
const OPEN: &str = "https://demo.nolimitcity.com/EjsFrontWeb/fs";
const MAX_DECODED: usize = 16 * 1024 * 1024;

pub fn validate(game: &Game, mode: &Mode, _settings: &Value) -> Result<()> {
    ensure!(
        game.id == "SixFeetUnder",
        "Nolimit game has no reviewed Rust continuation binding"
    );
    ensure!(
        mode.kind == ModeKind::Normal && mode.key == "normal",
        "only reviewed Nolimit normal mode is supported"
    );
    Ok(())
}

fn amount(value: &Value) -> Result<Decimal> {
    let raw = match value {
        Value::String(s) => s.clone(),
        Value::Number(n) => n.to_string(),
        _ => bail!("missing native money"),
    };
    let result = decimal(&raw)?;
    ensure!(result >= Decimal::ZERO, "negative native money");
    Ok(result)
}

fn rc4_hex(key: &str, text: &str) -> Result<String> {
    use std::fmt::Write;
    ensure!(!key.is_empty(), "missing native transport key");
    let key = key.as_bytes();
    let mut state = [0u8; 256];
    for (i, value) in state.iter_mut().enumerate() {
        *value = i as u8;
    }
    let mut j = 0usize;
    for i in 0..256 {
        j = (j + state[i] as usize + key[i % key.len()] as usize) % 256;
        state.swap(i, j);
    }
    let (mut i, mut j) = (0usize, 0usize);
    let mut result = String::with_capacity(text.len() * 2);
    for value in text.bytes() {
        i = (i + 1) % 256;
        j = (j + state[i] as usize) % 256;
        state.swap(i, j);
        let encoded = value ^ state[(state[i] as usize + state[j] as usize) % 256];
        write!(&mut result, "{encoded:02x}")?;
    }
    Ok(result)
}

fn lzw_decode(text: &str) -> Result<String> {
    let Some(encoded) = text.strip_prefix("lzw:") else {
        return Ok(text.into());
    };
    let codes = encoded.encode_utf16().collect::<Vec<_>>();
    let first = *codes.first().context("empty native compressed frame")?;
    let mut previous = vec![first];
    let mut output = previous.clone();
    let mut table: Vec<Vec<u16>> = Vec::new();
    for code in codes.into_iter().skip(1) {
        let entry = if code < 256 {
            vec![code]
        } else {
            let index = code as usize - 256;
            if let Some(entry) = table.get(index) {
                entry.clone()
            } else {
                ensure!(
                    index == table.len(),
                    "invalid native compression dictionary reference"
                );
                let mut entry = previous.clone();
                entry.push(previous[0]);
                entry
            }
        };
        ensure!(
            output.len() + entry.len() <= MAX_DECODED,
            "decoded native frame exceeds retained-body limit"
        );
        output.extend_from_slice(&entry);
        let mut next = previous;
        next.push(entry[0]);
        table.push(next);
        previous = entry;
    }
    String::from_utf16(&output).context("invalid native compressed text")
}

fn decode_frame(text: &str) -> Result<Value> {
    let decoded = lzw_decode(text)?;
    ensure!(
        decoded.len() <= MAX_DECODED,
        "decoded native frame exceeds retained-body limit"
    );
    let value: Value = serde_json::from_str(&decoded).context("invalid native frame JSON")?;
    ensure!(value.is_object(), "native frame is not an object");
    Ok(value)
}

fn minimum_bet(init: &Value) -> Result<Decimal> {
    ensure!(
        init["init"] == "ok" && init["game"]["nextMode"] == "NORMAL",
        "not a fresh idle demo"
    );
    ensure!(
        init["game"]["isRestoreState"] != true,
        "existing native round cannot become a new entry"
    );
    ensure!(
        init["currency"]["code"] == "EUR"
            && init["gameClientConfiguration"]["operator"] == "FANPAGE_DEMO",
        "native public demo and currency not established"
    );
    let levels = &init["betLevels"];
    // An explicitly empty available list must never fall back to disabled prices.
    let available = if levels.get("availableBetLevels").is_some() {
        &levels["availableBetLevels"]
    } else {
        &levels["betLevels"]
    };
    let bet = available
        .as_array()
        .context("missing published normal bet levels")?
        .iter()
        .map(amount)
        .collect::<Result<Vec<_>>>()?
        .into_iter()
        .min()
        .context("empty published normal bet levels")?;
    ensure!(
        bet > Decimal::ZERO && bet.trunc_with_scale(2) == bet,
        "normal price is not a positive native cent amount"
    );
    ensure!(
        amount(&init["balance"])? >= bet,
        "insufficient fictitious balance"
    );
    Ok(bet)
}

fn continuation(game: &Value) -> Result<Option<Value>> {
    let mode = game["nextMode"]
        .as_str()
        .context("native next mode missing")?;
    if mode == "NORMAL" {
        return Ok(None);
    }
    if mode == "EXTRA_SPIN" {
        // SixFeetUnder's reviewed string contract: decline the optional paid spin.
        amount(&game["extraSpinCost"])?;
        return Ok(Some(
            json!({"type":"zeroBet","bet":"0.00","playerInteraction":{"playExtraSpin":"no"}}),
        ));
    }
    if mode == "GAMBLE" {
        return Ok(Some(
            json!({"type":"gambleBet","bet":"0.00","playerInteraction":{"gambleCollected":true}}),
        ));
    }
    let choice = ["PICK", "SELECT", "CHOICE", "EXTRA", "GAMBLE"]
        .iter()
        .any(|part| mode.contains(part));
    let known_free = ["FREESPIN", "RESPIN", "AVALANCHE"]
        .iter()
        .any(|part| mode.contains(part));
    ensure!(
        !choice && known_free,
        "unreviewed native continuation; original round retained"
    );
    Ok(Some(json!({"type":"zeroBet","bet":"0.00"})))
}

fn settle(before: Decimal, cost: Decimal, last: &Value, balance: &Value) -> Result<RoundOutcome> {
    ensure!(
        last["game"]["nextMode"] == "NORMAL",
        "native round is not closed"
    );
    let native_win = amount(&last["game"]["accumulatedRoundWin"])?;
    let after = amount(&balance["balance"])?;
    if !balance["currency"]["code"].is_null() {
        ensure!(
            balance["currency"]["code"] == "EUR",
            "native final currency changed"
        );
    }
    ensure!(
        cost > Decimal::ZERO
            && before.trunc_with_scale(2) == before
            && cost.trunc_with_scale(2) == cost,
        "native cent settlement precondition failed"
    );
    // The reviewed provider rule truncates final balance to two decimals. When
    // opening balance and stake are exact cents, this independently determines
    // credited win from native accumulatedRoundWin without using wallet delta.
    let payout = native_win.trunc_with_scale(2);
    ensure!(
        wallet_matches(before, after, cost, payout),
        "native wallet and independently settled payout differ"
    );
    Ok(RoundOutcome {
        native_round_id: None,
        currency: "EUR".into(),
        monetary_unit: "native".into(),
        currency_source: "native_response".into(),
        balance_before: before.to_string(),
        balance_after: after.to_string(),
        cost: cost.to_string(),
        payout: payout.to_string(),
        native_closed: true,
        checks: BTreeMap::from([
            ("fresh_demo_and_currency".into(), true),
            ("native_offer".into(), true),
            ("native_settlement_rule".into(), true),
        ]),
        native_data: json!({"native_payout_unrounded":native_win.to_string(),"settlement_rule":"truncate_final_balance_2dp","closed_response":last,"balance_response":balance}),
    })
}

struct Client<'a> {
    ctx: &'a RunContext,
    socket: NativeSocket,
    key: String,
    version: String,
    prefix: String,
    number: u64,
    remember: Value,
}
impl Client<'_> {
    async fn call(&mut self, kind: &str, content: Value, financial: bool) -> Result<Value> {
        ensure!(
            matches!(kind, "init" | "normal" | "balance"),
            "unreviewed native request"
        );
        let id = format!("{}-{}", self.prefix, self.number);
        self.number = self
            .number
            .checked_add(1)
            .context("native request counter overflow")?;
        let mut request =
            json!({"type":kind,"content":content,"protocol":PROTOCOL,"id":id,"data":self.remember});
        if kind == "init" {
            request["gameClientVersion"] = json!(self.version);
        }
        let payload = rc4_hex(&self.key, &serde_json::to_string(&request)?)?;
        let remember = &mut self.remember;
        let response = self
            .ctx
            .ws_codec(
                &mut self.socket,
                kind,
                SocketPayload::Text(payload),
                financial,
                Some(&id),
                |frame| {
                    let SocketPayload::Text(text) = frame else {
                        bail!("unexpected native binary frame");
                    };
                    let response = decode_frame(text)?;
                    // Native keys can rotate in an unsolicited frame. RunContext
                    // has durably retained that frame before this callback and
                    // still correlates the returned response by request id.
                    if let Some(key) = response["extPlayerKey"].as_str().filter(|s| !s.is_empty()) {
                        remember["extPlayerKey"] = json!(key);
                    }
                    Ok(vec![response])
                },
            )
            .await?;
        ensure!(
            response["error"].is_null()
                || response["error"] == false
                || response["error"] == 0
                || response["error"] == "",
            "native provider rejected request"
        );
        Ok(response)
    }
}

pub async fn execute(
    ctx: &RunContext,
    game: &Game,
    mode: &Mode,
    settings: &Value,
) -> Result<RoundOutcome> {
    validate(game, mode, settings)?;
    let info = ctx
        .get("version", &format!("{STATIC}/games/{}/info.json", game.id))
        .await?;
    ensure!(info.status == 200, "public game version unavailable");
    let info: Value = serde_json::from_str(&info.body)?;
    let version = info["version"]
        .as_str()
        .context("public client version missing")?;
    ensure!(
        Regex::new(r"^[0-9]+(?:\.[0-9]+){1,3}(?:[-+.][A-Za-z0-9][A-Za-z0-9.-]*)?$")?
            .is_match(version),
        "unrecognized public version"
    );
    let form = url::form_urlencoded::Serializer::new(String::new())
        .append_pair("action", "open_game")
        .append_pair("clientString", "FANPAGE_DEMO")
        .append_pair("language", "en")
        .append_pair("gameCodeString", &format!("{}@desktop", game.id))
        .finish();
    let launch = ctx
        .http(
            "launcher",
            "POST",
            OPEN,
            BTreeMap::from([(
                "content-type".into(),
                "application/x-www-form-urlencoded".into(),
            )]),
            form,
            false,
        )
        .await?;
    ensure!(launch.status == 200, "public demo launch unavailable");
    let launch: Value = serde_json::from_str(&launch.body)?;
    ensure!(
        launch["url"] == "https://demo.nolimitcity.com/EjsGameWeb/gs",
        "unrecognized native public demo launch"
    );
    let key = launch["key"]
        .as_str()
        .filter(|s| {
            !s.is_empty()
                && s.bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        })
        .context("invalid native demo key")?;
    let mut ws_url = Url::parse("wss://demo.nolimitcity.com/EjsGameWeb/ws/game")?;
    ws_url.query_pairs_mut().append_pair("data", key);
    let socket = ctx
        .websocket(ws_url.as_str(), STATIC, None, BTreeMap::new())
        .await?;
    let mut client = Client {
        ctx,
        socket,
        key: key.into(),
        version: version.into(),
        prefix: Uuid::new_v4().simple().to_string()[..10].into(),
        number: 0,
        remember: json!({}),
    };
    let init = client.call("init", json!({"type":"init"}), false).await?;
    let bet = minimum_bet(&init)?;
    ensure!(
        init["gameInfo"]["displayName"] == game.name,
        "native game display identity differs from inventory"
    );
    let before = amount(&init["balance"])?;
    ensure!(
        before.trunc_with_scale(2) == before,
        "native balance has unreviewed precision"
    );
    ctx.save_session(&json!({"provider":"nolimit","game":game.id,"version":version,"transport_key":key,"request_prefix":client.prefix,"initial_request_number":client.number,"initial_remember":client.remember,"currency":"EUR","operator":"FANPAGE_DEMO"}))?;
    let mut request = json!({"type":"normalBet","bet":bet.to_string()});
    if init["allowedFeatureBets"].is_object() {
        let cap = init["game"]["playedCapMode"]
            .as_str()
            .context("native default cap mode missing")?;
        ensure!(
            init["allowedGameModes"]
                .as_array()
                .is_some_and(|modes| modes.iter().any(|m| m == cap)),
            "native default cap mode not offered"
        );
        request["playerInteraction"] = json!({"gameMode":cap});
    }
    let mut response = client.call("normal", request, true).await?;
    let mut responses = vec![response.clone()];
    for _ in 0..ctx.max_steps() {
        let Some(next) = continuation(&response["game"])? else {
            break;
        };
        response = client.call("normal", next, true).await?;
        responses.push(response.clone());
    }
    ensure!(
        response["game"]["nextMode"] == "NORMAL",
        "native continuation budget exhausted; original owner retained"
    );
    let balance = client
        .call(
            "balance",
            json!({"type":"balance","bet":bet.to_string()}),
            false,
        )
        .await?;
    let mut outcome = settle(before, bet, &response, &balance)?;
    outcome.native_data["version"] = json!(version);
    outcome.native_data["initialization"] = init;
    outcome.native_data["responses"] = json!(responses);
    Ok(outcome)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::decimal;
    use serde_json::json;

    #[tokio::test]
    async fn asynchronous_key_renewal_is_remembered_without_accepting_uncorrelated_response() {
        use crate::{
            model::{CampaignPlan, InventorySnapshot, Job, RoundSpec},
            store::Store,
        };
        use futures_util::{SinkExt, StreamExt};
        use tokio::net::TcpListener;
        use tokio_tungstenite::tungstenite::Message;
        let directory = tempfile::tempdir().unwrap();
        let store = Store::open(directory.path()).unwrap();
        let inventory:InventorySnapshot=serde_json::from_value(json!({"id":"nolimit-key-fixture","sources":[],"providers":[{"id":"nolimit","name":"Nolimit","ready":true,"campaign_eligible":true,"games":[{"id":"SixFeetUnder","name":"Six Feet Under","ready":true,"modes":[{"key":"normal","type":"normal","label":"Normal"}]}]}]})).unwrap();
        store.install_inventory(&inventory).unwrap();
        let plan = CampaignPlan {
            schema_version: 1,
            id: "key-renewal-fixture".into(),
            inventory_id: inventory.id.clone(),
            coverage: None,
            jobs: vec![Job {
                provider: "nolimit".into(),
                game: "SixFeetUnder".into(),
                mode: "normal".into(),
                samples: 1,
                settings: Value::Null,
            }],
        };
        store.create_campaign(&plan).unwrap();
        let round = store
            .create_round(&RoundSpec {
                campaign_id: plan.id,
                inventory_id: inventory.id,
                job_index: 0,
                sample_index: 0,
                provider: "nolimit".into(),
                game: "SixFeetUnder".into(),
                mode: "normal".into(),
                kind: ModeKind::Normal,
                settings: Value::Null,
            })
            .unwrap();
        let mut ctx =
            RunContext::new(store.clone(), round.id.clone(), "nolimit", 2, 10, None).unwrap();
        ctx.save_session(&json!({"transport_key":"synthetic-key","request_prefix":"fixture"}))
            .unwrap();
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        ctx.route_to_fixture(&format!("http://{}", listener.local_addr().unwrap()))
            .unwrap();
        let server = tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
            for (number, key) in [(0, "synthetic-old"), (1, "synthetic-renewed")] {
                let incoming = ws.next().await.unwrap().unwrap();
                let content = if number == 0 {
                    json!({"type":"normalBet","bet":"0.20"})
                } else {
                    json!({"type":"zeroBet","bet":"0.00"})
                };
                let request = json!({"type":"normal","content":content,"protocol":PROTOCOL,"id":format!("fixture-{number}"),"data":{"extPlayerKey":key}});
                assert_eq!(
                    incoming.to_text().unwrap(),
                    rc4_hex("synthetic-key", &serde_json::to_string(&request).unwrap()).unwrap(),
                    "continuation must carry the latest native key"
                );
                if number == 0 {
                    ws.send(Message::Text(json!({"id":"unrelated-frame","extPlayerKey":"synthetic-renewed","game":{"nextMode":"NORMAL","accumulatedRoundWin":999}}).to_string().into())).await.unwrap();
                }
                ws.send(Message::Text(json!({"id":format!("fixture-{number}"),"game":{"nextMode":if number==0 {"FREESPIN"}else{"NORMAL"},"accumulatedRoundWin":0}}).to_string().into())).await.unwrap();
            }
        });
        let socket = ctx
            .websocket(
                "wss://demo.nolimitcity.com/EjsGameWeb/ws/game?data=abcd",
                STATIC,
                None,
                BTreeMap::new(),
            )
            .await
            .unwrap();
        let mut client = Client {
            ctx: &ctx,
            socket,
            key: "synthetic-key".into(),
            version: "1.0".into(),
            prefix: "fixture".into(),
            number: 0,
            remember: json!({"extPlayerKey":"synthetic-old"}),
        };
        let response = client
            .call("normal", json!({"type":"normalBet","bet":"0.20"}), true)
            .await
            .unwrap();
        assert_eq!(response["id"], "fixture-0");
        assert_eq!(response["game"]["nextMode"], "FREESPIN");
        assert_eq!(client.remember["extPlayerKey"], "synthetic-renewed");
        assert_eq!(
            client
                .call("normal", json!({"type":"zeroBet","bet":"0.00"}), true)
                .await
                .unwrap()["id"],
            "fixture-1"
        );
        server.await.unwrap();
        let exchanges = store.exchanges(&round.id).unwrap();
        assert_eq!(exchanges.iter().filter(|e| e.request.financial).count(), 2);
        let paid = exchanges.iter().find(|e| e.request.financial).unwrap();
        assert_eq!(paid.frames.len(), 2);
    }

    #[test]
    fn wire_cipher_matches_published_rc4_vector_and_lzw_roundtrip() {
        assert_eq!(rc4_hex("Key", "Plaintext").unwrap(), "bbf316e8d940af0ad3");
        assert!(rc4_hex("", "x").is_err());
        assert_eq!(
            decode_frame(r#"{"id":"request-1","balance":"10.00"}"#).unwrap()["id"],
            "request-1"
        );
        // A literal-only compressed JSON fixture exercises the real wire decoder.
        assert_eq!(decode_frame(r#"lzw:{"init":"ok"}"#).unwrap()["init"], "ok");
        assert_eq!(lzw_decode("lzw:ABA\u{100}").unwrap(), "ABAAB");
        assert!(lzw_decode("lzw:A\u{200}").is_err());
        assert!(decode_frame("lzw:").is_err());
        assert!(decode_frame("not json").is_err());
    }

    #[test]
    fn published_six_feet_initialization_matches_reviewed_normal_minimum() {
        let rows: Value = serde_json::from_str(include_str!(
            "../../../demo-dashboard/nolimit/batches/1-100/inventory.json"
        ))
        .unwrap();
        let game = rows
            .as_array()
            .unwrap()
            .iter()
            .find(|g| g["code"] == "SixFeetUnder")
            .unwrap();
        assert_eq!(
            minimum_bet(&game["init"]).unwrap(),
            decimal("0.20").unwrap()
        );
        assert_eq!(continuation(&game["init"]["game"]).unwrap(), None);
    }

    #[test]
    fn normal_price_uses_available_offer_and_never_empty_list_fallback() {
        let mut init = json!({"init":"ok","currency":{"code":"EUR"},"gameClientConfiguration":{"operator":"FANPAGE_DEMO"},"game":{"nextMode":"NORMAL","isRestoreState":false},"balance":"10000.00","betLevels":{"bet":"1.00","availableBetLevels":["0.40","0.20"],"betLevels":["0.10","0.20"]}});
        assert_eq!(minimum_bet(&init).unwrap(), decimal("0.20").unwrap());
        init["betLevels"]["availableBetLevels"] = json!([]);
        assert!(minimum_bet(&init).is_err());
        init["betLevels"]["availableBetLevels"] = json!(["0.20"]);
        init["game"]["isRestoreState"] = json!(true);
        assert!(minimum_bet(&init).is_err());
        init["game"]["isRestoreState"] = json!(false);
        init["gameClientConfiguration"]["operator"] = json!("REAL");
        assert!(minimum_bet(&init).is_err());
    }

    #[test]
    fn continuation_declines_optional_paid_extra_and_rejects_unknown_choice() {
        assert_eq!(continuation(&json!({"nextMode":"NORMAL"})).unwrap(), None);
        assert_eq!(
            continuation(&json!({"nextMode":"FREESPIN","freespinsLeft":2})).unwrap(),
            Some(json!({"type":"zeroBet","bet":"0.00"}))
        );
        assert_eq!(
            continuation(
                &json!({"nextMode":"EXTRA_SPIN","extraSpinCost":2,"accumulatedRoundWin":3})
            )
            .unwrap(),
            Some(json!({"type":"zeroBet","bet":"0.00","playerInteraction":{"playExtraSpin":"no"}}))
        );
        assert_eq!(
            continuation(&json!({"nextMode":"GAMBLE"})).unwrap(),
            Some(
                json!({"type":"gambleBet","bet":"0.00","playerInteraction":{"gambleCollected":true}})
            )
        );
        assert!(continuation(&json!({"nextMode":"FREESPIN_PICK"})).is_err());
        assert!(continuation(&json!({"nextMode":"NEW_UNKNOWN_PHASE"})).is_err());
    }

    #[test]
    fn settlement_uses_final_native_total_once_and_independent_balance() {
        let last =
            json!({"game":{"nextMode":"NORMAL","accumulatedRoundWin":"4.44","spinWin":"0.36"}});
        let mut result = settle(
            decimal("10000").unwrap(),
            decimal("16").unwrap(),
            &last,
            &json!({"balance":"9988.44"}),
        )
        .unwrap();
        assert_eq!(result.payout, "4.44");
        assert!(result.verify().unwrap());
        assert!(
            settle(
                decimal("10000").unwrap(),
                decimal("16").unwrap(),
                &last,
                &json!({"balance":"9988.45"})
            )
            .is_err()
        );
        assert!(
            settle(
                decimal("10000").unwrap(),
                decimal("16").unwrap(),
                &json!({"game":{"nextMode":"FREESPIN","accumulatedRoundWin":"4.44"}}),
                &json!({"balance":"9988.44"})
            )
            .is_err()
        );
    }

    #[test]
    fn fractional_native_win_obeys_documented_truncation_without_balance_inference() {
        let mut result = settle(
            decimal("10000.00").unwrap(),
            decimal("54.00").unwrap(),
            &json!({"game":{"nextMode":"NORMAL","accumulatedRoundWin":"58.996"}}),
            &json!({"balance":"10004.99"}),
        )
        .unwrap();
        assert_eq!(result.payout, "58.99");
        assert_eq!(result.native_data["native_payout_unrounded"], "58.996");
        assert!(result.verify().unwrap());
        assert!(
            settle(
                decimal("10000.001").unwrap(),
                decimal("54.00").unwrap(),
                &json!({"game":{"nextMode":"NORMAL","accumulatedRoundWin":"58.996"}}),
                &json!({"balance":"10004.99"})
            )
            .is_err()
        );
    }
}
