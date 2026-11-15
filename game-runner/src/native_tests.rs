//! Synthetic offline protocol fixtures: no requests leave loopback.
use crate::{
    adapters::NativeExecutor, context::RunContext, engine::Executor, model::*, store::Store,
};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    sync::{Arc, Mutex},
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
};

#[derive(Debug)]
struct Request {
    path: String,
    headers: BTreeMap<String, String>,
    body: String,
    owner_present: bool,
    response_status: u16,
}
struct Reply {
    status: u16,
    body: String,
    location: Option<String>,
    set_cookies: Vec<String>,
    expected_headers: BTreeMap<String, String>,
    expected_cookies: Option<BTreeMap<String, String>>,
}
impl Reply {
    fn set_cookies(mut self, values: &[&str]) -> Self {
        self.set_cookies = values.iter().map(|s| (*s).to_owned()).collect();
        self
    }
    fn require_header(mut self, name: &str, value: &str) -> Self {
        self.expected_headers
            .insert(name.to_ascii_lowercase(), value.into());
        self
    }
    fn require_cookies(mut self, values: &[(&str, &str)]) -> Self {
        self.expected_cookies = Some(
            values
                .iter()
                .map(|(k, v)| ((*k).to_owned(), (*v).to_owned()))
                .collect(),
        );
        self
    }
}
fn ok(body: impl Into<String>) -> Reply {
    Reply {
        status: 200,
        body: body.into(),
        location: None,
        set_cookies: vec![],
        expected_headers: BTreeMap::new(),
        expected_cookies: None,
    }
}
fn cookies(headers: &BTreeMap<String, String>) -> BTreeMap<String, String> {
    headers
        .get("cookie")
        .into_iter()
        .flat_map(|s| s.split(';'))
        .map(|s| {
            let (name, value) = s.trim().split_once('=').expect("invalid fixture cookie");
            (name.to_owned(), value.to_owned())
        })
        .collect()
}
async fn server(
    store: Store,
    round: String,
    replies: Vec<Reply>,
) -> (
    String,
    Arc<Mutex<Vec<Request>>>,
    tokio::task::JoinHandle<()>,
) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let origin = format!("http://{}", listener.local_addr().unwrap());
    let requests = Arc::new(Mutex::new(Vec::new()));
    let saved = requests.clone();
    let task = tokio::spawn(async move {
        for reply in replies {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut buffer = Vec::new();
            let head_end = loop {
                let mut chunk = [0u8; 4096];
                let n = socket.read(&mut chunk).await.unwrap();
                assert!(n > 0, "fixture EOF reading headers");
                buffer.extend_from_slice(&chunk[..n]);
                if let Some(i) = buffer.windows(4).position(|w| w == b"\r\n\r\n") {
                    break i + 4;
                }
            };
            let head = std::str::from_utf8(&buffer[..head_end]).unwrap();
            let path = head
                .lines()
                .next()
                .unwrap()
                .split_whitespace()
                .nth(1)
                .unwrap()
                .to_owned();
            let headers: BTreeMap<String, String> = head
                .lines()
                .skip(1)
                .filter_map(|l| {
                    let (k, v) = l.split_once(':')?;
                    Some((k.to_ascii_lowercase(), v.trim().to_owned()))
                })
                .collect();
            let length = headers
                .get("content-length")
                .map_or(0, |s| s.parse::<usize>().unwrap());
            while buffer.len() < head_end + length {
                let mut chunk = [0u8; 4096];
                let n = socket.read(&mut chunk).await.unwrap();
                assert!(n > 0, "fixture EOF reading body");
                buffer.extend_from_slice(&chunk[..n]);
            }
            let body = String::from_utf8(buffer[head_end..head_end + length].to_vec()).unwrap();
            let owner_present = store.session(&round).unwrap().is_some();
            let accepted = reply
                .expected_headers
                .iter()
                .all(|(k, v)| headers.get(k) == Some(v))
                && reply
                    .expected_cookies
                    .as_ref()
                    .is_none_or(|expected| &cookies(&headers) == expected);
            // Model an origin that refuses calls without its generated HTTP session.
            // A failed expectation is an actual 403 response through RunContext,
            // rather than a server-side assertion that leaves the client hanging.
            let reply = if accepted {
                reply
            } else {
                Reply {
                    status: 403,
                    ..ok("fixture: HTTP session not established")
                }
            };
            saved.lock().unwrap().push(Request {
                path,
                headers,
                body,
                owner_present,
                response_status: reply.status,
            });
            let location = reply
                .location
                .map(|s| format!("Location: {s}\r\n"))
                .unwrap_or_default();
            let set_cookies: String = reply
                .set_cookies
                .iter()
                .map(|s| format!("Set-Cookie: {s}\r\n"))
                .collect();
            let response = format!(
                "HTTP/1.1 {} {}\r\nContent-Length: {}\r\nConnection: close\r\n{}{}\r\n{}",
                reply.status,
                match reply.status {
                    302 => "Found",
                    403 => "Forbidden",
                    _ => "OK",
                },
                reply.body.len(),
                location,
                set_cookies,
                reply.body
            );
            socket.write_all(response.as_bytes()).await.unwrap();
            socket.shutdown().await.unwrap();
            if !accepted {
                break;
            }
        }
    });
    (origin, requests, task)
}
fn setup(
    provider: &str,
    game_id: &str,
    mode_key: &str,
    kind: ModeKind,
) -> (tempfile::TempDir, Store, Game, Mode, String) {
    let dir = tempfile::tempdir().unwrap();
    let store = Store::open(dir.path()).unwrap();
    let mode = Mode {
        key: mode_key.into(),
        kind,
        label: mode_key.into(),
        ready: true,
        requires_prerequisites: Value::Null,
        execution_source: None,
    };
    let game = Game {
        id: game_id.into(),
        name: "Synthetic offline fixture".into(),
        ready: true,
        block_reason: String::new(),
        modes: vec![mode.clone()],
    };
    let inventory = InventorySnapshot {
        id: "fixture-inventory".into(),
        sources: vec![],
        providers: vec![ProviderInventory {
            id: provider.into(),
            name: provider.into(),
            ready: true,
            campaign_eligible: true,
            protocol: Value::Null,
            games: vec![game.clone()],
        }],
    };
    store.install_inventory(&inventory).unwrap();
    let settings = Value::Null;
    store
        .create_campaign(&CampaignPlan {
            schema_version: 1,
            id: "fixture-campaign".into(),
            inventory_id: inventory.id.clone(),
            coverage: None,
            jobs: vec![Job {
                provider: provider.into(),
                game: game_id.into(),
                mode: mode_key.into(),
                samples: 1,
                settings: settings.clone(),
            }],
        })
        .unwrap();
    let record = store
        .create_round(&RoundSpec {
            campaign_id: "fixture-campaign".into(),
            inventory_id: inventory.id,
            job_index: 0,
            sample_index: 0,
            provider: provider.into(),
            game: game_id.into(),
            mode: mode_key.into(),
            kind,
            settings,
        })
        .unwrap();
    (dir, store, game, mode, record.id)
}
const HACKSAW_SESSION_COOKIES: [(&str, &str); 2] = [
    ("hs_launch", "authenticated-fixture"),
    ("hs_session", "session-fixture"),
];
fn hacksaw_replies(bonus: bool) -> Vec<Reply> {
    let mut replies = vec![
        ok(r#"{"version":"1.0.0"}"#)
            .set_cookies(&["cdn_only=static-fixture; Path=/; Secure; HttpOnly"])
            .require_cookies(&[]),
        ok(r#"{"statusCode":0}"#)
            .set_cookies(&[
                "hs_launch=issued-fixture; Path=/api/play; Secure; HttpOnly",
                "hs_private=path-fixture; Path=/unused; Secure; HttpOnly",
            ])
            .require_cookies(&[])
            .require_header("content-type", "application/json"),
        ok(json!({"statusCode":0,"gameId":2405,"name":"Demo","roundId":0,"roundStatus":null,"sessionUuid":"offline-fixture","accountBalance":{"balance":1000,"currencyCode":"EUR"},"betLevels":[10,20],"bonusGames":[{"bonusGameId":"bonus","betCostMultiplier":10}]}).to_string())
            .set_cookies(&[
                "hs_launch=authenticated-fixture; Path=/api/play; Secure; HttpOnly",
                "hs_session=session-fixture; Path=/api/play; Secure; HttpOnly",
            ])
            .require_cookies(&[("hs_launch", "issued-fixture")])
            .require_header("content-type", "application/json"),
    ];
    if bonus {
        replies.push(ok(json!({"statusCode":0,"round":{"roundId":"offline-r","status":"wfwpc","possibleActions":[],"events":[]},"accountBalance":{"balance":900,"currencyCode":"EUR"}}).to_string()));
        replies.push(ok(json!({"statusCode":0,"round":{"roundId":"offline-r","status":"completed","possibleActions":[],"events":[{"wa":25}]},"accountBalance":{"balance":925,"currencyCode":"EUR"}}).to_string()));
    } else {
        replies.push(ok(json!({"statusCode":0,"round":{"roundId":"offline-r","status":"completed","possibleActions":[],"events":[{"wa":3}]},"accountBalance":{"balance":993,"currencyCode":"EUR"}}).to_string()));
    }
    replies
        .into_iter()
        .enumerate()
        .map(|(index, reply)| {
            if index >= 3 {
                reply
                    .require_cookies(&HACKSAW_SESSION_COOKIES)
                    .require_header("content-type", "application/json")
            } else {
                reply
            }
        })
        .collect()
}
async fn run_hacksaw(bonus: bool) {
    let (_dir, store, game, mode, id) = setup(
        "hacksaw",
        "2405",
        if bonus { "bonus" } else { "normal" },
        if bonus {
            ModeKind::Purchase
        } else {
            ModeKind::Normal
        },
    );
    let (origin, requests, task) = server(store.clone(), id.clone(), hacksaw_replies(bonus)).await;
    let mut ctx = RunContext::new(store.clone(), id.clone(), "hacksaw", 5, 20, None).unwrap();
    ctx.route_to_fixture(&origin).unwrap();
    let outcome = NativeExecutor
        .execute(&ctx, "hacksaw", &game, &mode, &Value::Null)
        .await
        .unwrap();
    assert_eq!(outcome.cost, if bonus { "100" } else { "10" });
    assert_eq!(outcome.payout, if bonus { "25" } else { "3" });
    let result = store.complete(&id, &outcome).unwrap();
    assert_eq!(result.status, RoundStatus::Verified);
    assert_eq!(result.spec.kind, mode.kind);
    task.await.unwrap();
    let req = requests.lock().unwrap();
    assert_eq!(req.len(), if bonus { 5 } else { 4 });
    assert_eq!(
        req[0].path,
        "/static-live.hacksawgaming.com/2405/version.json"
    );
    assert!(req[1].path.ends_with("/partnerSettings"));
    assert!(req[2].path.ends_with("/authenticate"));
    assert!(req[3].path.ends_with("/bet"));
    assert!(cookies(&req[0].headers).is_empty());
    // A host-only cookie from static-live must not bleed to rgs-demo.
    assert!(cookies(&req[1].headers).is_empty());
    assert_eq!(
        cookies(&req[2].headers),
        BTreeMap::from([("hs_launch".into(), "issued-fixture".into())])
    );
    let expected_cookies: BTreeMap<String, String> = HACKSAW_SESSION_COOKIES
        .map(|(k, v)| (k.to_owned(), v.to_owned()))
        .into_iter()
        .collect();
    for request in &req[3..] {
        assert_eq!(cookies(&request.headers), expected_cookies);
        assert_eq!(request.response_status, 200);
    }
    let entry: Value = serde_json::from_str(&req[3].body).unwrap();
    assert!(req[3].owner_present);
    assert_eq!(entry["bets"].as_array().unwrap().len(), 1);
    assert_eq!(entry["bets"][0]["betAmount"], "10");
    if bonus {
        assert_eq!(entry["bets"][0]["buyBonus"], "bonus");
        let continuation: Value = serde_json::from_str(&req[4].body).unwrap();
        assert!(req[4].owner_present);
        assert_eq!(continuation["roundId"], "offline-r");
        assert_eq!(
            continuation["continueInstructions"]["action"],
            "win_presentation_complete"
        );
        assert!(continuation.get("bets").is_none());
    }
    let exchanges = store.exchanges(&id).unwrap();
    assert_eq!(exchanges.len(), req.len());
    assert_eq!(
        exchanges.iter().filter(|e| e.request.financial).count(),
        if bonus { 2 } else { 1 }
    );
    assert!(exchanges.iter().all(|e| e.response.is_some()));
    assert_eq!(
        exchanges[1].response.as_ref().unwrap().set_cookies,
        [
            "hs_launch=issued-fixture; Path=/api/play; Secure; HttpOnly",
            "hs_private=path-fixture; Path=/unused; Secure; HttpOnly",
        ]
    );
    assert_eq!(
        exchanges[2].response.as_ref().unwrap().set_cookies,
        [
            "hs_launch=authenticated-fixture; Path=/api/play; Secure; HttpOnly",
            "hs_session=session-fixture; Path=/api/play; Secure; HttpOnly",
        ]
    );
}
#[tokio::test]
async fn hacksaw_normal_synthetic_offline() {
    run_hacksaw(false).await
}
#[tokio::test]
async fn hacksaw_purchase_continues_same_root_offline() {
    run_hacksaw(true).await
}
#[tokio::test]
async fn hacksaw_missing_http_session_is_403_before_a_bet() {
    let mut replies = hacksaw_replies(false);
    replies[1]
        .set_cookies
        .retain(|s| !s.starts_with("hs_launch="));
    missing_http_session_is_blocked("hacksaw", "2405", replies, 3).await;
}

const PRAGMATIC_SESSION_COOKIES: [(&str, &str); 2] = [
    ("pg_launch", "authenticated-fixture"),
    ("pg_session", "session-fixture"),
];
fn pragmatic_replies(win: &str, final_balance: &str) -> Vec<Reply> {
    vec![
        Reply {
            status: 302,
            location: Some(
                "https://demogamesfree.pragmaticplay.net/gs2c/play?mgckey=synthetic-public-test"
                    .into(),
            ),
            ..ok("")
        }
        .set_cookies(&[
            "pg_launch=issued-fixture; Path=/gs2c; Secure; HttpOnly",
            "pg_private=path-fixture; Path=/unused; Secure; HttpOnly",
        ])
        .require_cookies(&[]),
        ok(
            r#"<script src="https://demogamesfree-s.pragmaticplay.net/gs2c/common/fixture/bootstrap.js"></script><script>const config={"gameService":"/gs2c/gameService"};</script>"#,
        )
        .set_cookies(&[
            "pg_launch=authenticated-fixture; Path=/gs2c; Secure; HttpOnly",
            "pg_session=session-fixture; Path=/gs2c; Secure; HttpOnly",
        ])
        .require_cookies(&[("pg_launch", "issued-fixture")]),
        ok("UHT_REVISION={common:'123'};")
            .set_cookies(&["cdn_only=static-fixture; Path=/; Secure; HttpOnly"])
            .require_cookies(&[]),
        ok(
            "balance=100.00&currency=USD&sc=0.01,0.10&l=20&bl=0&bls=20,40&purInit=%5B%7Bbet%3A100%7D%2C%7Bbet%3A200%7D%5D&purInit_e=1,1&na=s",
        ),
        ok("currency=USD&na=s&fs=1&fsmax=1&tw=0"),
        ok(format!("currency=USD&na=c&tw={win}")),
        ok(format!(
            "currency=USD&na=s&tw={win}&balance={final_balance}"
        )),
    ]
    .into_iter()
    .enumerate()
    .map(|(index, reply)| {
        if index >= 3 {
            reply
                .require_cookies(&PRAGMATIC_SESSION_COOKIES)
                .require_header("content-type", "application/x-www-form-urlencoded")
        } else {
            reply
        }
    })
    .collect()
}
fn form(body: &str) -> BTreeMap<String, String> {
    url::form_urlencoded::parse(body.as_bytes())
        .map(|(k, v)| (k.into_owned(), v.into_owned()))
        .collect()
}
async fn run_pragmatic(
    mode_key: &str,
    kind: ModeKind,
    cost: &str,
    win: &str,
    balance: &str,
    max_steps: usize,
) {
    let (_dir, store, game, mode, id) = setup("pragmatic", "vsfixture", mode_key, kind);
    let (origin, requests, task) =
        server(store.clone(), id.clone(), pragmatic_replies(win, balance)).await;
    let mut ctx =
        RunContext::new(store.clone(), id.clone(), "pragmatic", 5, max_steps, None).unwrap();
    ctx.route_to_fixture(&origin).unwrap();
    let outcome = NativeExecutor
        .execute(&ctx, "pragmatic", &game, &mode, &Value::Null)
        .await
        .unwrap();
    assert_eq!(decimal(&outcome.cost).unwrap(), decimal(cost).unwrap());
    assert_eq!(decimal(&outcome.payout).unwrap(), decimal(win).unwrap());
    let result = store.complete(&id, &outcome).unwrap();
    assert_eq!(result.status, RoundStatus::Verified);
    assert_eq!(result.spec.kind, kind);
    task.await.unwrap();
    let req = requests.lock().unwrap();
    assert_eq!(req.len(), 7);
    assert!(req[0].path.contains("/gs2c/openGame.do?"));
    assert!(
        req[1]
            .path
            .contains("/gs2c/play?mgckey=synthetic-public-test")
    );
    assert_eq!(
        req[2].path,
        "/demogamesfree-s.pragmaticplay.net/gs2c/common/fixture/bootstrap.js"
    );
    assert!(cookies(&req[0].headers).is_empty());
    assert_eq!(
        cookies(&req[1].headers),
        BTreeMap::from([("pg_launch".into(), "issued-fixture".into())])
    );
    // Native session cookies stay at the demo origin, not the script CDN.
    assert!(cookies(&req[2].headers).is_empty());
    let expected_cookies: BTreeMap<String, String> = PRAGMATIC_SESSION_COOKIES
        .map(|(k, v)| (k.to_owned(), v.to_owned()))
        .into_iter()
        .collect();
    for request in &req[3..] {
        assert_eq!(cookies(&request.headers), expected_cookies);
        assert_eq!(request.response_status, 200);
    }
    let init = form(&req[3].body);
    let entry = form(&req[4].body);
    let free = form(&req[5].body);
    let collect = form(&req[6].body);
    assert_eq!(init.get("action").unwrap(), "doInit");
    assert_eq!(entry.get("action").unwrap(), "doSpin");
    assert_eq!(free.get("action").unwrap(), "doSpin");
    assert_eq!(collect.get("action").unwrap(), "doCollect");
    for (request, index, counter) in [
        (&init, "1", "1"),
        (&entry, "2", "3"),
        (&free, "3", "5"),
        (&collect, "4", "7"),
    ] {
        assert_eq!(request.get("index").unwrap(), index);
        assert_eq!(request.get("counter").unwrap(), counter);
        assert_eq!(request.get("symbol").unwrap(), "vsfixture");
    }
    assert!(!req[3].owner_present);
    assert!(req[4..].iter().all(|r| r.owner_present));
    for request in [&entry, &free] {
        assert_eq!(request.get("c").unwrap(), "0.01");
        assert_eq!(request.get("l").unwrap(), "20");
        assert_eq!(
            request.get("bl").unwrap(),
            if mode_key == "bl-1" { "1" } else { "0" }
        );
        assert_eq!(request.get("mgckey").unwrap(), "synthetic-public-test");
        assert_eq!(request.get("cver").unwrap(), "123");
    }
    if mode_key == "pur-0" {
        assert_eq!(entry.get("pur").unwrap(), "0");
    } else {
        assert!(!entry.contains_key("pur"));
    }
    assert!(!free.contains_key("pur"));
    assert!(!collect.contains_key("pur"));
    let exchanges = store.exchanges(&id).unwrap();
    assert_eq!(exchanges.len(), req.len());
    assert_eq!(exchanges.iter().filter(|e| e.request.financial).count(), 3);
    assert!(exchanges.iter().all(|e| e.response.is_some()));
    assert_eq!(
        exchanges[0].response.as_ref().unwrap().set_cookies,
        [
            "pg_launch=issued-fixture; Path=/gs2c; Secure; HttpOnly",
            "pg_private=path-fixture; Path=/unused; Secure; HttpOnly",
        ]
    );
    assert_eq!(
        exchanges[1].response.as_ref().unwrap().set_cookies,
        [
            "pg_launch=authenticated-fixture; Path=/gs2c; Secure; HttpOnly",
            "pg_session=session-fixture; Path=/gs2c; Secure; HttpOnly",
        ]
    );
}
#[tokio::test]
async fn pragmatic_normal_synthetic_offline() {
    run_pragmatic("normal", ModeKind::Normal, "0.20", "0.50", "100.30", 20).await
}
#[tokio::test]
async fn pragmatic_purchase_free_spin_and_collect_offline() {
    run_pragmatic("pur-0", ModeKind::Purchase, "1.00", "2.00", "101.00", 20).await
}
#[tokio::test]
async fn pragmatic_bet_level_free_spin_and_collect_offline() {
    run_pragmatic("bl-1", ModeKind::Variant, "0.40", "0.60", "100.20", 20).await
}
#[tokio::test]
async fn pragmatic_bonus_closes_on_the_last_allowed_continuation() {
    run_pragmatic("pur-0", ModeKind::Purchase, "1.00", "2.00", "101.00", 2).await
}
#[tokio::test]
async fn pragmatic_missing_redirect_cookie_is_403_before_initialization() {
    let mut replies = pragmatic_replies("0.50", "100.30");
    replies[0]
        .set_cookies
        .retain(|s| !s.starts_with("pg_launch="));
    missing_http_session_is_blocked("pragmatic", "vsfixture", replies, 2).await;
}
async fn missing_http_session_is_blocked(
    provider: &str,
    game_id: &str,
    replies: Vec<Reply>,
    expected_requests: usize,
) {
    let (_dir, store, game, mode, id) = setup(provider, game_id, "normal", ModeKind::Normal);
    let (origin, requests, task) = server(store.clone(), id.clone(), replies).await;
    let mut ctx = RunContext::new(store.clone(), id.clone(), provider, 5, 20, None).unwrap();
    ctx.route_to_fixture(&origin).unwrap();
    let error = NativeExecutor
        .execute(&ctx, provider, &game, &mode, &Value::Null)
        .await
        .unwrap_err();
    assert!(error.to_string().contains("403"));
    task.await.unwrap();
    let req = requests.lock().unwrap();
    assert_eq!(req.len(), expected_requests);
    assert_eq!(req.last().unwrap().response_status, 403);
    assert!(req.iter().all(|r| !r.owner_present));
    let exchanges = store.exchanges(&id).unwrap();
    assert_eq!(exchanges.len(), expected_requests);
    assert!(exchanges.iter().all(|e| !e.request.financial));
    let rejected = exchanges.last().unwrap().response.as_ref().unwrap();
    assert_eq!(rejected.status, 403);
    assert_eq!(rejected.body, "fixture: HTTP session not established");
    assert_eq!(store.round(&id).unwrap().status, RoundStatus::Blocked);
    assert!(store.provider_hold(provider).unwrap().is_some());
}
