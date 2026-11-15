//! Fresh FUN session and one reviewed normal round from collection_claude_extra.py.
use crate::{
    context::{DecodedFrame, NativeSocket, RunContext, SocketPayload},
    model::*,
};
use anyhow::{Context, Result, bail, ensure};
use rust_decimal::Decimal;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use url::Url;

const PROVIDER: &str = "hardfire-kalamba";
const GAME: &str = "9blazingcashpots50k";
const LAUNCH: &str = "https://kalamba.integration.demo.kalambagames.com/games/url/";
const ORIGIN: &str = "https://v.play.test.kl.luckycdn.net";

struct Launch {
    url: Url,
    origin: String,
    token: String,
    username: String,
}
struct Profile {
    before: Decimal,
    version: u64,
}

pub fn validate(game: &Game, mode: &Mode, settings: &Value) -> Result<()> {
    ensure!(
        game.id == GAME && mode.kind == ModeKind::Normal && mode.key == "normal",
        "Kalamba supports only the reviewed normal game"
    );
    ensure!(
        settings.is_null() || settings.as_object().is_some_and(|o| o.is_empty()),
        "Kalamba public binding has no overrides"
    );
    Ok(())
}
fn amount(value: &Value) -> Result<Decimal> {
    ensure!(
        value.is_number() || value.is_string(),
        "Kalamba native amount missing"
    );
    decimal(
        &value
            .as_str()
            .map(str::to_owned)
            .unwrap_or_else(|| value.to_string()),
    )
}
fn launch_binding(url: &Url) -> Result<Option<Launch>> {
    crate::context::validate_target(PROVIDER, url.as_str())?;
    ensure!(url.scheme() == "https", "Kalamba launch must use HTTPS");
    let mut query: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for (key, value) in url.query_pairs() {
        query
            .entry(key.into_owned())
            .or_default()
            .push(value.into_owned());
    }
    if !query.contains_key("token") {
        return Ok(None);
    }
    let path = match url.host_str() {
        Some("v.play.test.kl.luckycdn.net") => "/1.26.1/index.html",
        Some("v.games.test.kl.luckycdn.net") => "/games/128.8.0/index.html",
        // Official FUN launcher 302, retained in Actions 43324094682.
        Some("awscdn.test.kalamba.net") => "/index.html",
        _ => bail!("Kalamba unreviewed launch origin"),
    };
    ensure!(url.path() == path, "Kalamba launch client version changed");
    let one = |key: &str| -> Result<&str> {
        let values = query
            .get(key)
            .context("Kalamba missing demo launch field")?;
        ensure!(
            values.len() == 1 && !values[0].is_empty(),
            "Kalamba ambiguous demo launch field"
        );
        Ok(&values[0])
    };
    for (key, expected) in [
        ("gameCode", GAME),
        ("cageCode", "FUN"),
        ("playMode", "FUN"),
        ("operatorCode", "kalamba-demo"),
        ("currency", "EUR"),
    ] {
        ensure!(
            one(key)? == expected,
            "Kalamba demo launch identity mismatch"
        );
    }
    let token = one("token")?.to_owned();
    let username = one("username")?.to_owned();
    let mut api = crate::context::validate_target(PROVIDER, one("apiUrl")?)?;
    ensure!(
        api.scheme() == "wss" && api.path() == "/oryxreplica/" && api.query().is_none(),
        "Kalamba unreviewed WSS launch binding"
    );
    api.query_pairs_mut().extend_pairs([
        ("cageCode", "FUN"),
        ("gameCode", GAME),
        ("operatorCode", "kalamba-demo"),
        ("playMode", "FUN"),
        ("token", &token),
        ("username", &username),
    ]);
    Ok(Some(Launch {
        url: api,
        origin: if url.host_str() == Some("awscdn.test.kalamba.net") {
            // A browser at this reviewed document sends this origin. Server
            // acceptance must still be established by the actual WSS upgrade.
            url.origin().ascii_serialization()
        } else {
            ORIGIN.into()
        },
        token,
        username,
    }))
}
async fn bootstrap(ctx: &RunContext) -> Result<Launch> {
    let mut url = Url::parse(LAUNCH)?;
    url.query_pairs_mut().extend_pairs([
        ("gameCode", GAME),
        ("cageCode", "FUN"),
        ("currency", "EUR"),
    ]);
    for _ in 0..6 {
        if let Some(binding) = launch_binding(&url)? {
            return Ok(binding);
        }
        let response = ctx
            .http(
                "demo_launch",
                "GET",
                url.as_str(),
                BTreeMap::from([("user-agent".into(), "Mozilla/5.0".into())]),
                String::new(),
                false,
            )
            .await?;
        ensure!(
            matches!(response.status, 301 | 302 | 303 | 307 | 308),
            "Kalamba demo launch did not return a redirect"
        );
        let location = response
            .headers
            .get("location")
            .filter(|s| !s.is_empty())
            .context("Kalamba demo launch redirect missing")?;
        url = url.join(location)?;
    }
    bail!("Kalamba demo launch exceeded six steps")
}
fn profile(account: &Value, opened: &Value, initial: &Value) -> Result<Profile> {
    let state = &initial["data"]["gameState"];
    let config = &initial["data"]["additionalConfigData"];
    let before = amount(&initial["balance"])?;
    ensure!(
        opened["gameCode"] == GAME
            && account["currencyCode"] == "EUR"
            && state["gameId"] == GAME
            && state["roundNumber"] == 0
            && state["freeSpinCount"] == 0
            && state["stateTypeThisRound"] == "BaseGame"
            && state["stateTypeNextRound"] == "BaseGame"
            && config["availableMultipliersPerBaseBet"]["50"]
                .as_array()
                .is_some_and(|values| values.contains(&json!(4)))
            && amount(&config["maxAllowedOverallBetInCoins"])? >= Decimal::from(200)
            && before >= Decimal::from(200)
            && amount(&account["balance"])? == before,
        "Kalamba FUN session is not fresh, idle and bound to the offered fixed bet"
    );
    let version = initial["balanceVersion"]
        .as_u64()
        .context("Kalamba initial balance version missing")?;
    Ok(Profile { before, version })
}
fn settlement(profile: &Profile, receipt: &Value) -> Result<RoundOutcome> {
    let state = &receipt["data"]["gameState"];
    let payout = amount(&receipt["data"]["gameRoundResult"]["win"])?;
    let after = amount(&receipt["balance"])?;
    let cost = Decimal::from(200);
    ensure!(
        receipt["event"] == "SPIN_RESULT"
            && receipt["correlationSeqId"] == 1
            && receipt["balanceVersion"]
                .as_u64()
                .is_some_and(|v| v > profile.version)
            && state["gameId"] == GAME
            && state["roundNumber"] == 1
            && state["stateTypeThisRound"] == "BaseGame"
            && state["stateTypeNextRound"] == "BaseGame"
            && state["freeSpinCount"] == 0
            && amount(&state["totalBetFromCurrentGameCycle"])? == cost
            && amount(&state["totalWinFromCurrentGameCycle"])? == payout,
        "Kalamba native normal cycle remains open or has inconsistent identity/prize"
    );
    ensure!(
        exact_add(exact_sub(profile.before, cost)?, payout)? == after,
        "Kalamba independent native prize/wallet mismatch"
    );
    Ok(RoundOutcome {
        native_round_id: None,
        currency: "EUR".into(),
        monetary_unit: "native".into(),
        currency_source: "native_response".into(),
        balance_before: profile.before.to_string(),
        balance_after: after.to_string(),
        cost: cost.to_string(),
        payout: payout.to_string(),
        native_closed: true,
        checks: BTreeMap::from([
            ("native_offered_fixed_bet".into(), true),
            ("single_native_cycle".into(), true),
            ("native_sequence_and_version".into(), true),
            ("independent_native_prize".into(), true),
        ]),
        native_data: json!({"game":GAME,"round_number":1,"bet_selection":"reviewed_fixed_bet","base_bet":50,"multiplier":4,"receipt":receipt}),
    })
}
#[derive(Clone, Copy)]
enum Expected {
    Authenticate,
    Open,
    Spin,
}
#[derive(Default)]
struct Session {
    counter: u64,
}
impl Session {
    fn packet(
        &mut self,
        name: &str,
        client: u64,
        body: Value,
        action: bool,
        data_type: u64,
    ) -> Result<SocketPayload> {
        self.counter = self
            .counter
            .checked_add(1)
            .context("Kalamba message counter overflow")?;
        let mut header = json!({"cId":client,"dType":if action {2}else{data_type},"name":name,"mId":self.counter});
        if action {
            header["dId"] = json!(1);
        }
        Ok(SocketPayload::Text(serde_json::to_string(
            &json!({"header":header,"body":body}),
        )?))
    }
    async fn transact(
        &mut self,
        ctx: &RunContext,
        socket: &mut NativeSocket,
        label: &str,
        payload: SocketPayload,
        expected: Expected,
        financial: bool,
    ) -> Result<Value> {
        let mut opened = None;
        let mut initial = None;
        ctx.ws_codec_controlled(socket, label, payload, financial, None, |frame| {
            let text = match frame {
                SocketPayload::Text(s) => s,
                SocketPayload::Binary(_) => bail!("Kalamba expected native JSON text"),
            };
            let packet: Value =
                serde_json::from_str(text).context("Kalamba malformed native JSON")?;
            let header = &packet["header"];
            let body = &packet["body"];
            let name = header["name"]
                .as_str()
                .context("Kalamba native message name missing")?;
            if name == "Ping" {
                let reply = self.packet(
                    "Ping",
                    header["cId"].as_u64().unwrap_or(0),
                    json!({}),
                    false,
                    header["dType"].as_u64().unwrap_or(1),
                )?;
                return Ok(DecodedFrame {
                    values: Vec::new(),
                    replies: vec![reply],
                });
            }
            ensure!(
                header["code"] == 1 && body["event"] != "SPIN_ERROR",
                "Kalamba native request rejected"
            );
            let value = match expected {
                Expected::Authenticate if name == "Authenticate" => Some(body.clone()),
                Expected::Spin if name == "GameEvent" && body["event"] == "SPIN_RESULT" => {
                    Some(body.clone())
                }
                Expected::Open => {
                    if name == "OpenGame" {
                        ensure!(
                            opened.is_none(),
                            "Kalamba duplicate OpenGame acknowledgement"
                        );
                        opened = Some(body.clone());
                    }
                    if name == "GameEvent" && body["event"] == "OPEN_GAME" {
                        ensure!(initial.is_none(), "Kalamba duplicate OPEN_GAME state");
                        initial = Some(body.clone());
                    }
                    if let (Some(opened), Some(initial)) = (&opened, &initial) {
                        Some(json!({"opened":opened,"initial":initial}))
                    } else {
                        None
                    }
                }
                _ => None,
            };
            Ok(DecodedFrame {
                values: value.into_iter().collect(),
                replies: Vec::new(),
            })
        })
        .await
    }
}
pub async fn execute(
    ctx: &RunContext,
    game: &Game,
    mode: &Mode,
    settings: &Value,
) -> Result<RoundOutcome> {
    validate(game, mode, settings)?;
    let launch = bootstrap(ctx).await?;
    let mut socket = ctx
        .websocket(
            launch.url.as_str(),
            &launch.origin,
            None,
            BTreeMap::from([("User-Agent".into(), "Mozilla/5.0".into())]),
        )
        .await?;
    let mut session = Session::default();
    let auth=session.packet("Authenticate",1,json!({"cageCode":"FUN","clientType":3,"languageCode":"ENG","playMode":2,"reconnect":false,"token":launch.token,"version":"128.8.0"}),false,1)?;
    let account = session
        .transact(
            ctx,
            &mut socket,
            "authenticate",
            auth,
            Expected::Authenticate,
            false,
        )
        .await?;
    let open = session.packet("OpenGame", 2, json!({"gameCode":GAME}), false, 1)?;
    let initialized = session
        .transact(ctx, &mut socket, "open_game", open, Expected::Open, false)
        .await?;
    let profile = profile(&account, &initialized["opened"], &initialized["initial"])?;
    ctx.save_session(&json!({"provider":PROVIDER,"game":GAME,"demo":"FUN","currency":"EUR","token":launch.token,"username":launch.username,"websocket_url":launch.url.as_str(),"origin":launch.origin,
        "account":account,"initialization":initialized,"bet_selection":"reviewed_fixed_bet","base_bet":50,"multiplier":4}))?;
    let action = session.packet(
        "GameAction",
        3,
        json!({"data":{"bet":{"baseBet":50,"betMultiplier":4}},"seqId":1,"action":"SPIN"}),
        true,
        2,
    )?;
    let receipt = session
        .transact(ctx, &mut socket, "normal", action, Expected::Spin, true)
        .await?;
    // Continuations are not specified in this normal-only contract. If the
    // provider opens a feature, keep this exact session and attempt for review.
    settlement(&profile, &receipt)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn launch() -> Url {
        let mut url = Url::parse("https://v.play.test.kl.luckycdn.net/1.26.1/index.html").unwrap();
        url.query_pairs_mut().extend_pairs([
            ("gameCode", GAME),
            ("cageCode", "FUN"),
            ("playMode", "FUN"),
            ("operatorCode", "kalamba-demo"),
            ("currency", "EUR"),
            ("token", "synthetic-token"),
            ("username", "synthetic-user"),
            (
                "apiUrl",
                "wss://gameserver-api-2.test.twmc8fvg.click/oryxreplica/",
            ),
        ]);
        url
    }
    fn initial() -> Value {
        json!({"balance":10000,"balanceVersion":0,"event":"OPEN_GAME","data":{
            "gameState":{"gameId":GAME,"roundNumber":0,"freeSpinCount":0,"stateTypeThisRound":"BaseGame","stateTypeNextRound":"BaseGame"},
            "additionalConfigData":{"availableMultipliersPerBaseBet":{"50":[1,2,4]},"maxAllowedOverallBetInCoins":500}}})
    }
    fn account() -> Value {
        json!({"currencyCode":"EUR","balance":10000})
    }
    fn opened() -> Value {
        json!({"gameCode":GAME})
    }
    fn receipt() -> Value {
        json!({"balance":9800,"balanceVersion":1,"correlationSeqId":1,"event":"SPIN_RESULT","data":{
            "gameState":{"gameId":GAME,"roundNumber":1,"freeSpinCount":0,"stateTypeThisRound":"BaseGame","stateTypeNextRound":"BaseGame","totalBetFromCurrentGameCycle":200,"totalWinFromCurrentGameCycle":0},
            "gameRoundResult":{"win":0}}})
    }
    #[test]
    fn launch_requires_exact_fun_binding_and_reviewed_test_shard() {
        let binding = launch_binding(&launch()).unwrap().unwrap();
        assert_eq!(binding.token, "synthetic-token");
        assert_eq!(binding.username, "synthetic-user");
        assert_eq!(
            binding.url.host_str(),
            Some("gameserver-api-2.test.twmc8fvg.click")
        );
        let mut duplicate = launch();
        duplicate.query_pairs_mut().append_pair("token", "second");
        assert!(launch_binding(&duplicate).is_err());
        for changed in [
            launch().as_str().replace("cageCode=FUN", "cageCode=REAL"),
            launch().as_str().replace("9blazingcashpots50k", "other"),
            launch()
                .as_str()
                .replace("test.twmc8fvg.click", "prod.twmc8fvg.click"),
            launch().as_str().replace("1.26.1", "1.26.2"),
            launch().as_str().replace(
                "v.play.test.kl.luckycdn.net",
                "v.play.test.kl.luckycdn.net.evil.test",
            ),
        ] {
            assert!(
                launch_binding(&Url::parse(&changed).unwrap()).is_err(),
                "{changed}"
            );
        }
        assert!(
            launch_binding(&Url::parse(LAUNCH).unwrap())
                .unwrap()
                .is_none()
        );
        assert!(
            launch_binding(
                &Url::parse("https://gameserver-api-2.test.twmc8fvg.click/oryxreplica/").unwrap()
            )
            .is_err()
        );
    }
    #[test]
    fn observed_fun_cdn_redirect_uses_its_own_origin_without_widening_identity() {
        // Structure of the official launcher 302 retained by Actions 43324094682.
        // Tokens and username below are synthetic; the endpoint and controls are public.
        let mut url = launch();
        url.set_host(Some("awscdn.test.kalamba.net")).unwrap();
        url.set_path("/index.html");
        let bound = launch_binding(&url).unwrap().unwrap();
        assert_eq!(bound.origin, "https://awscdn.test.kalamba.net");
        assert_eq!(
            bound.url.host_str(),
            Some("gameserver-api-2.test.twmc8fvg.click")
        );
        let mut wrong = url.clone();
        wrong.set_path("/unreviewed.html");
        assert!(launch_binding(&wrong).is_err());
        let mut wrong = url.clone();
        wrong.set_host(Some("awscdn.prod.kalamba.net")).unwrap();
        assert!(launch_binding(&wrong).is_err());
        let wrong = Url::parse(&url.as_str().replace("cageCode=FUN", "cageCode=REAL")).unwrap();
        assert!(launch_binding(&wrong).is_err());
        assert_eq!(launch_binding(&launch()).unwrap().unwrap().origin, ORIGIN);
    }
    #[test]
    fn quote_requires_fresh_account_and_native_offered_fixed_bet() {
        let p = profile(&account(), &opened(), &initial()).unwrap();
        assert_eq!(p.before, Decimal::from(10000));
        for (path, value) in [
            ("/data/gameState/roundNumber", json!(1)),
            ("/data/gameState/freeSpinCount", json!(1)),
            (
                "/data/additionalConfigData/availableMultipliersPerBaseBet/50",
                json!([1, 2]),
            ),
            ("/balance", json!(9999)),
        ] {
            let mut changed = initial();
            *changed.pointer_mut(path).unwrap() = value;
            assert!(profile(&account(), &opened(), &changed).is_err());
        }
        assert!(
            profile(
                &json!({"currencyCode":"USD","balance":10000}),
                &opened(),
                &initial()
            )
            .is_err()
        );
    }
    #[test]
    fn loss_requires_native_closure_sequence_and_independent_prize() {
        let p = profile(&account(), &opened(), &initial()).unwrap();
        let mut result = settlement(&p, &receipt()).unwrap();
        assert!(result.verify().unwrap());
        assert_eq!(result.payout, "0");
        assert_eq!(result.cost, "200");
        assert_eq!(result.balance_after, "9800");
        for (path, value) in [
            ("/correlationSeqId", json!(2)),
            ("/balanceVersion", json!(0)),
            ("/balance", json!(9801)),
            ("/data/gameState/stateTypeNextRound", json!("FreeSpins")),
            ("/data/gameRoundResult/win", json!(-1)),
            ("/data/gameState/totalWinFromCurrentGameCycle", json!(1)),
        ] {
            let mut changed = receipt();
            *changed.pointer_mut(path).unwrap() = value;
            assert!(settlement(&p, &changed).is_err(), "{path}");
        }
    }
    fn fixture_context() -> (tempfile::TempDir, RunContext, Game, Mode) {
        let dir = tempfile::tempdir().unwrap();
        let store = crate::store::Store::open(dir.path()).unwrap();
        let inventory:InventorySnapshot=serde_json::from_value(json!({"id":"kalamba-fixture","sources":[],"providers":[{"id":PROVIDER,"name":"Kalamba","ready":true,"campaign_eligible":true,"games":[{"id":GAME,"name":GAME,"ready":true,"modes":[{"key":"normal","type":"normal","label":"Normal"}]}]}]})).unwrap();
        store.install_inventory(&inventory).unwrap();
        let game = inventory.providers[0].games[0].clone();
        let mode = game.modes[0].clone();
        store
            .create_campaign(&CampaignPlan {
                schema_version: 1,
                id: "fixture".into(),
                inventory_id: inventory.id.clone(),
                coverage: None,
                jobs: vec![Job {
                    provider: PROVIDER.into(),
                    game: GAME.into(),
                    mode: "normal".into(),
                    samples: 1,
                    settings: Value::Null,
                }],
            })
            .unwrap();
        let round = store
            .create_round(&RoundSpec {
                campaign_id: "fixture".into(),
                inventory_id: inventory.id,
                job_index: 0,
                sample_index: 0,
                provider: PROVIDER.into(),
                game: GAME.into(),
                mode: "normal".into(),
                kind: ModeKind::Normal,
                settings: Value::Null,
            })
            .unwrap();
        let ctx = RunContext::new(store, round.id, PROVIDER, 3, 100, None).unwrap();
        (dir, ctx, game, mode)
    }
    #[allow(clippy::result_large_err)] // Tungstenite's handshake callback fixes this error type.
    async fn server_fixture(
        ctx: &RunContext,
        terminal: Value,
    ) -> (String, tokio::task::JoinHandle<()>) {
        use futures_util::{SinkExt, StreamExt};
        use tokio::{
            io::{AsyncReadExt, AsyncWriteExt},
            net::TcpListener,
            time::{Duration, timeout},
        };
        use tokio_tungstenite::tungstenite::Message;
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let origin = format!("http://{}", listener.local_addr().unwrap());
        let store = ctx.store.clone();
        let round = ctx.round_id.clone();
        let server = tokio::spawn(async move {
            let (mut http, _) = timeout(Duration::from_secs(5), listener.accept())
                .await
                .unwrap()
                .unwrap();
            let mut bytes = Vec::new();
            while !bytes.windows(4).any(|w| w == b"\r\n\r\n") {
                let mut part = [0; 4096];
                let len = http.read(&mut part).await.unwrap();
                assert!(len > 0);
                bytes.extend_from_slice(&part[..len]);
            }
            let request = String::from_utf8(bytes).unwrap();
            assert!(request.starts_with("GET /kalamba.integration.demo.kalambagames.com/games/url/?gameCode=9blazingcashpots50k&cageCode=FUN&currency=EUR "));
            let mut observed = launch();
            observed.set_host(Some("awscdn.test.kalamba.net")).unwrap();
            observed.set_path("/index.html");
            http.write_all(format!("HTTP/1.1 302 Found\r\nLocation: {observed}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").as_bytes()).await.unwrap();
            drop(http);
            let (tcp, _) = timeout(Duration::from_secs(5), listener.accept())
                .await
                .unwrap()
                .unwrap();
            let mut ws = tokio_tungstenite::accept_hdr_async(
                tcp,
                |req: &tokio_tungstenite::tungstenite::handshake::server::Request, response| {
                    assert_eq!(req.headers()["origin"], "https://awscdn.test.kalamba.net");
                    assert_eq!(req.headers()["user-agent"], "Mozilla/5.0");
                    assert!(
                        req.uri()
                            .path()
                            .starts_with("/gameserver-api-2.test.twmc8fvg.click/oryxreplica/")
                    );
                    Ok(response)
                },
            )
            .await
            .unwrap();
            let auth: Value =
                serde_json::from_str(&ws.next().await.unwrap().unwrap().into_text().unwrap())
                    .unwrap();
            assert_eq!(auth["header"]["mId"], 1);
            assert_eq!(auth["header"]["name"], "Authenticate");
            assert_eq!(auth["body"]["token"], "synthetic-token");
            assert_eq!(auth["body"]["playMode"], 2);
            ws.send(Message::Text(
                json!({"header":{"name":"Ping","cId":7,"dType":1},"body":{}})
                    .to_string()
                    .into(),
            ))
            .await
            .unwrap();
            let ping: Value =
                serde_json::from_str(&ws.next().await.unwrap().unwrap().into_text().unwrap())
                    .unwrap();
            assert_eq!(ping["header"]["name"], "Ping");
            assert_eq!(ping["header"]["mId"], 2);
            assert_eq!(ping["header"]["cId"], 7);
            ws.send(Message::Text(
                json!({"header":{"name":"Authenticate","code":1},"body":account()})
                    .to_string()
                    .into(),
            ))
            .await
            .unwrap();
            let open: Value =
                serde_json::from_str(&ws.next().await.unwrap().unwrap().into_text().unwrap())
                    .unwrap();
            assert_eq!(open["header"]["mId"], 3);
            assert_eq!(open["header"]["name"], "OpenGame");
            for packet in [
                json!({"header":{"name":"GameEvent","code":1},"body":initial()}),
                json!({"header":{"name":"OpenGame","code":1},"body":opened()}),
            ] {
                ws.send(Message::Text(packet.to_string().into()))
                    .await
                    .unwrap();
            }
            let spin: Value =
                serde_json::from_str(&ws.next().await.unwrap().unwrap().into_text().unwrap())
                    .unwrap();
            assert_eq!(
                spin,
                json!({"header":{"name":"GameAction","cId":3,"dType":2,"dId":1,"mId":4},"body":{"data":{"bet":{"baseBet":50,"betMultiplier":4}},"seqId":1,"action":"SPIN"}})
            );
            let owner = store.session(&round).unwrap().unwrap();
            assert_eq!(owner["token"], "synthetic-token");
            assert_eq!(owner["game"], GAME);
            assert_eq!(owner["origin"], "https://awscdn.test.kalamba.net");
            let exchanges = store.exchanges(&round).unwrap();
            assert_eq!(exchanges.iter().filter(|e| e.request.financial).count(), 1);
            assert!(
                exchanges.last().unwrap().request.financial
                    && exchanges.last().unwrap().response.is_none()
            );
            ws.send(Message::Text(
                json!({"header":{"name":"Ping"},"body":{}})
                    .to_string()
                    .into(),
            ))
            .await
            .unwrap();
            let ping: Value =
                serde_json::from_str(&ws.next().await.unwrap().unwrap().into_text().unwrap())
                    .unwrap();
            assert_eq!(ping["header"]["mId"], 5);
            let exchanges = store.exchanges(&round).unwrap();
            assert_eq!(
                exchanges.last().unwrap().frames.last().unwrap().kind,
                "sent_control_text"
            );
            ws.send(Message::Text(
                json!({"header":{"name":"GameEvent","code":1},"body":terminal})
                    .to_string()
                    .into(),
            ))
            .await
            .unwrap();
        });
        (origin, server)
    }
    #[tokio::test]
    async fn fresh_fun_owner_and_control_replies_precede_one_spin() {
        let (_dir, mut ctx, game, mode) = fixture_context();
        let (origin, server) = server_fixture(&ctx, receipt()).await;
        ctx.route_to_fixture(&origin).unwrap();
        let outcome = execute(&ctx, &game, &mode, &json!({})).await;
        assert!(outcome.is_ok(), "{outcome:?}");
        server.await.unwrap();
        let row = ctx
            .store
            .complete(&ctx.round_id, &outcome.unwrap())
            .unwrap();
        assert_eq!(row.status, RoundStatus::Verified);
        let exchanges = ctx.store.exchanges(&ctx.round_id).unwrap();
        assert_eq!(exchanges.len(), 5);
        assert_eq!(exchanges.iter().filter(|e| e.request.financial).count(), 1);
        assert_eq!(
            exchanges
                .iter()
                .flat_map(|e| &e.frames)
                .filter(|f| f.kind == "sent_control_text")
                .count(),
            2
        );
    }
    #[tokio::test]
    async fn unknown_feature_keeps_original_owner_without_a_second_paid_entry() {
        let (_dir, mut ctx, game, mode) = fixture_context();
        let mut terminal = receipt();
        terminal["data"]["gameState"]["stateTypeNextRound"] = json!("FreeSpins");
        let (origin, server) = server_fixture(&ctx, terminal).await;
        ctx.route_to_fixture(&origin).unwrap();
        assert!(execute(&ctx, &game, &mode, &json!({})).await.is_err());
        server.await.unwrap();
        assert!(ctx.store.pending_provider(PROVIDER).unwrap().is_some());
        assert!(ctx.store.round(&ctx.round_id).unwrap().outcome.is_none());
        assert_eq!(
            ctx.store.session(&ctx.round_id).unwrap().unwrap()["token"],
            "synthetic-token"
        );
        assert_eq!(
            ctx.store
                .exchanges(&ctx.round_id)
                .unwrap()
                .iter()
                .filter(|e| e.request.financial)
                .count(),
            1
        );
    }
}
