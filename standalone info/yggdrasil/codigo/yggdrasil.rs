//! Source-bound Yggdrasil Jokerizer BASIC demo round.
use crate::{
    context::RunContext,
    model::{Game, Mode, ModeKind, RoundOutcome, decimal, wallet_matches},
};
use anyhow::{Context, Result, bail, ensure};
use rust_decimal::Decimal;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use url::Url;
use uuid::Uuid;

const SERVICE: &str = "https://demo.yggdrasilgaming.com/game.web/service";
const ORIGIN: &str = "https://staticdemo.yggdrasilgaming.com";
const GAME: &str = "7301";
const COST: Decimal = Decimal::ONE;
pub fn validate(game: &Game, mode: &Mode, settings: &Value) -> Result<()> {
    ensure!(
        game.id == GAME && mode.kind == ModeKind::Normal && mode.key == "BASIC",
        "only reviewed Yggdrasil Jokerizer BASIC is supported"
    );
    ensure!(
        settings.as_object().is_some_and(|o| o.len() == 3)
            && amount(&settings["coin"])? == decimal("0.1")?
            && amount(&settings["amount"])? == COST
            && amount(&settings["stake"])? == COST,
        "Yggdrasil binding differs from the published closed CSV row"
    );
    Ok(())
}
fn amount(value: &Value) -> Result<Decimal> {
    match value {
        Value::String(s) => decimal(s),
        Value::Number(n) => decimal(&n.to_string()),
        _ => bail!("native Yggdrasil amount missing"),
    }
}
fn common() -> BTreeMap<String, String> {
    BTreeMap::from([
        ("gameid".into(), GAME.into()),
        ("channel".into(), "pc".into()),
        ("currency".into(), "EUR".into()),
        ("lang".into(), "en".into()),
    ])
}
fn currency(data: &Value) -> Result<()> {
    for value in [data.get("currency"), data.get("currencyCode")]
        .into_iter()
        .flatten()
    {
        ensure!(value == "EUR", "native Yggdrasil currency mismatch");
    }
    Ok(())
}
fn current_stake(config: &Value, before: Decimal) -> Result<()> {
    let modes = config["bets"]["betModes"]
        .as_array()
        .context("native Yggdrasil bet modes missing")?;
    let offered: Vec<_> = modes.iter().filter(|m| m["name"] == "BASIC").collect();
    ensure!(
        offered.len() == 1,
        "native Yggdrasil BASIC mode missing or ambiguous"
    );
    let selected = offered[0];
    let types = selected.get("modeTypes").and_then(Value::as_array);
    ensure!(
        !types.is_some_and(|types| types.iter().any(|t| t == "BUY_BONUS" || t == "GOLDEN_BET")),
        "native Yggdrasil BASIC changed role"
    );
    let parsed;
    let bets = if let Some(text) = selected["bets"].as_str() {
        parsed = serde_json::from_str::<Value>(text)?;
        &parsed
    } else {
        &selected["bets"]
    };
    let bets = bets
        .as_array()
        .context("native Yggdrasil bet list missing")?;
    let mut found = false;
    for bet in bets {
        if bet["available"] == true
            && amount(&bet["coinValue"])? == decimal("0.1")?
            && amount(&bet["betAmount"])? == COST
        {
            found = true;
        }
    }
    ensure!(
        found && before >= COST,
        "published Yggdrasil normal stake unavailable"
    );
    Ok(())
}
fn wager<'a>(data: &'a Value, id: &Value) -> Result<&'a Value> {
    let wager = &data["wager"];
    ensure!(&wager["wagerid"] == id, "native Yggdrasil wager changed");
    ensure!(
        id.is_number() || id.as_str().is_some_and(|s| !s.is_empty()),
        "native Yggdrasil wager identity missing"
    );
    let bets = wager["bets"]
        .as_array()
        .filter(|b| !b.is_empty())
        .context("native Yggdrasil bets missing")?;
    ensure!(
        amount(&bets[0]["betamount"])? == COST,
        "native Yggdrasil paid stake changed"
    );
    // Every following debit belongs to the same paid root and must be free.
    for bet in &bets[1..] {
        ensure!(
            amount(&bet["betamount"])? == Decimal::ZERO,
            "unexpected additional Yggdrasil wager debit"
        );
    }
    if let Some(game) = wager.get("gameid") {
        ensure!(
            game == GAME || game.as_u64() == Some(7301),
            "native Yggdrasil game changed"
        );
    }
    currency(&data["resultBal"])?;
    Ok(wager)
}
fn continuation(data: &Value, id: &Value, previous: Option<u64>) -> Result<Option<(u64, String)>> {
    let wager = wager(data, id)?;
    if wager["status"] == "Finished" {
        return Ok(None);
    }
    ensure!(
        wager["status"].as_str().is_some_and(|s| !s.is_empty()),
        "native Yggdrasil wager state missing"
    );
    let last = wager["bets"].as_array().unwrap().last().unwrap();
    let step = last["step"]
        .as_u64()
        .context("native Yggdrasil continuation step missing")?;
    ensure!(
        previous.is_none_or(|old| step > old),
        "native Yggdrasil step did not advance"
    );
    let commands = last["betdata"]["cmds"]
        .as_array()
        .filter(|c| !c.is_empty())
        .context("native Yggdrasil continuation not offered")?;
    let command = commands[0]
        .as_str()
        .filter(|s| !s.is_empty())
        .context("native Yggdrasil continuation command invalid")?;
    let lower = command.to_ascii_lowercase();
    ensure!(
        lower != "basic"
            && !lower.contains("buy")
            && !lower.contains("golden")
            && !lower.contains("gamble"),
        "Yggdrasil offered command is outside normal continuation scope"
    );
    Ok(Some((step, command.to_owned())))
}
fn settlement(data: &Value, id: &Value, before: Decimal) -> Result<(Decimal, Decimal)> {
    let wager = wager(data, id)?;
    ensure!(
        wager["status"] == "Finished",
        "native Yggdrasil wager remains open"
    );
    let last = wager["bets"].as_array().unwrap().last().unwrap();
    let win = amount(&last["wonamount"])?;
    let after = amount(&data["resultBal"]["cash"])?;
    ensure!(
        wallet_matches(before, after, COST, win),
        "native Yggdrasil final award and wallet disagree"
    );
    Ok((win, after))
}
async fn request(
    ctx: &RunContext,
    method: &str,
    function: &str,
    fields: &BTreeMap<String, String>,
    token: Option<&str>,
    financial: bool,
) -> Result<Value> {
    if !cfg!(test) {
        tokio::time::sleep(std::time::Duration::from_millis(1200)).await;
    }
    let mut endpoint = Url::parse(SERVICE)?;
    endpoint.query_pairs_mut().append_pair("fn", function);
    let mut headers = BTreeMap::from([
        ("origin".into(), ORIGIN.into()),
        ("referer".into(), format!("{ORIGIN}/")),
    ]);
    if let Some(token) = token {
        headers.insert("authorization".into(), format!("Bearer {token}"));
        headers.insert("game-id".into(), GAME.into());
    }
    if financial {
        headers.insert("x-crid".into(), Uuid::new_v4().to_string());
    }
    let body = if method == "GET" {
        endpoint.query_pairs_mut().extend_pairs(fields);
        String::new()
    } else {
        headers.insert(
            "content-type".into(),
            "application/x-www-form-urlencoded".into(),
        );
        url::form_urlencoded::Serializer::new(String::new())
            .extend_pairs(fields)
            .finish()
    };
    let response = ctx
        .http(
            &format!("yggdrasil.{function}"),
            method,
            endpoint.as_str(),
            headers,
            body,
            financial,
        )
        .await?;
    ensure!(response.status == 200, "Yggdrasil HTTP {}", response.status);
    let reply: Value =
        serde_json::from_str(&response.body).context("invalid Yggdrasil native JSON")?;
    ensure!(
        reply["code"].as_i64() == Some(0),
        "Yggdrasil native command rejected"
    );
    reply
        .get("data")
        .cloned()
        .filter(|d| d.is_object())
        .context("native Yggdrasil data missing")
}
pub async fn execute(
    ctx: &RunContext,
    game: &Game,
    mode: &Mode,
    settings: &Value,
) -> Result<RoundOutcome> {
    validate(game, mode, settings)?;
    let limit = ctx.max_steps().min(60);
    ensure!(limit > 0, "Yggdrasil financial action budget is empty");
    let mut demo = common();
    demo.insert("org".into(), "Demo".into());
    demo.insert("license".into(), "mt".into());
    let config = request(ctx, "GET", "game", &demo, None, false).await?;
    demo.insert("userName".into(), "undefined".into());
    let auth = request(ctx, "POST", "authenticate", &demo, None, false).await?;
    currency(&auth["balance"])?;
    let before = amount(&auth["balance"]["cash"])?;
    current_stake(&config, before)?;
    let token = auth["token"]
        .as_str()
        .filter(|s| !s.is_empty())
        .context("fresh Yggdrasil demo token missing")?;
    ctx.save_session(&json!({"provider":"yggdrasil","game":GAME,"org":"Demo","service":SERVICE,"token":token,"currency":"EUR"}))?;
    let mut play = common();
    play.extend([
        ("channelID".into(), String::new()),
        ("channelSuffix".into(), String::new()),
        ("gameHistorySessionId".into(), "session".into()),
        ("gameHistoryTicketId".into(), "ticket".into()),
    ]);
    let mut entry = play.clone();
    entry.extend([
        ("amount".into(), "1.00".into()),
        ("coin".into(), "0.10".into()),
        ("cmd".into(), String::new()),
    ]);
    let mut data = request(ctx, "POST", "play", &entry, Some(token), true).await?;
    let id = data["wager"]["wagerid"].clone();
    let mut previous = None;
    for index in 0..limit {
        match continuation(&data, &id, previous)? {
            None => {
                let (win, after) = settlement(&data, &id, before)?;
                let round_id = id
                    .as_str()
                    .map(str::to_owned)
                    .unwrap_or_else(|| id.to_string());
                return Ok(RoundOutcome {
                    native_round_id: Some(round_id),
                    currency: "EUR".into(),
                    monetary_unit: "major".into(),
                    currency_source: if auth["balance"].get("currency").is_some()
                        || auth["balance"].get("currencyCode").is_some()
                    {
                        "native_response"
                    } else {
                        "public_binding"
                    }
                    .into(),
                    balance_before: before.normalize().to_string(),
                    balance_after: after.normalize().to_string(),
                    cost: COST.to_string(),
                    payout: win.normalize().to_string(),
                    native_closed: true,
                    checks: BTreeMap::from([
                        ("public_demo_authentication".into(), true),
                        ("published_current_quote".into(), true),
                        ("original_wager".into(), true),
                        ("native_final_award".into(), true),
                    ]),
                    native_data: json!({"family":"yggdrasil.service","game":GAME,"mode":"BASIC","steps":index+1,"coin":"0.1","amount":"1","status":"Finished"}),
                });
            }
            Some((step, command)) => {
                // The paid root already consumed one action. Always inspect
                // the current response before checking whether another send
                // fits: a terminal response at the limit is still verified.
                ensure!(
                    index + 1 < limit,
                    "Yggdrasil continuation limit; original wager retained"
                );
                previous = Some(step);
                let mut follow = play.clone();
                follow.extend([
                    (
                        "step".into(),
                        step.checked_add(1)
                            .context("native Yggdrasil step overflow")?
                            .to_string(),
                    ),
                    ("betid".into(), "1".into()),
                    ("cmd".into(), command),
                    (
                        "wagerid".into(),
                        id.as_str()
                            .map(str::to_owned)
                            .unwrap_or_else(|| id.to_string()),
                    ),
                    ("amount".into(), "0.00".into()),
                ]);
                data = request(ctx, "POST", "play", &follow, Some(token), true).await?;
            }
        }
    }
    bail!("Yggdrasil continuation limit; original wager retained")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::decimal;
    use serde_json::json;
    fn config() -> Value {
        json!({"bets":{"betModes":[{"name":"BASIC","modeTypes":["BASIC"],"bets":[{"coinValue":"0.1","betAmount":"1","available":true}]}]}})
    }
    fn terminal() -> Value {
        json!({"wager":{"wagerid":"synthetic-round","status":"Finished","bets":[{"betamount":"1","wonamount":"0.5","step":0}]},"resultBal":{"cash":"99.5"}})
    }
    #[test]
    fn current_offer_must_match_published_csv_price_and_role() {
        let before = decimal("100").unwrap();
        assert!(current_stake(&config(), before).is_ok());
        let mut changed = config();
        changed["bets"]["betModes"][0]["bets"][0]["betAmount"] = json!("2");
        assert!(current_stake(&changed, before).is_err());
        changed = config();
        changed["bets"]["betModes"][0]["modeTypes"] = json!(["BUY_BONUS"]);
        assert!(current_stake(&changed, before).is_err());
        assert!(current_stake(&config(), decimal("0.9").unwrap()).is_err());
    }
    #[test]
    fn exact_native_award_rejects_python_cent_tolerance_and_wrong_wager() {
        let before = decimal("100").unwrap();
        let id = json!("synthetic-round");
        assert_eq!(
            settlement(&terminal(), &id, before).unwrap(),
            (decimal("0.5").unwrap(), decimal("99.5").unwrap())
        );
        let mut data = terminal();
        data["resultBal"]["cash"] = json!("99.51");
        assert!(settlement(&data, &id, before).is_err());
        assert!(settlement(&terminal(), &json!("other-round"), before).is_err());
        data = terminal();
        data["wager"]["bets"][0]["betamount"] = json!("2");
        assert!(settlement(&data, &id, before).is_err());
    }
    #[test]
    fn continuation_requires_original_wager_new_native_step_and_offered_command() {
        let id = json!("synthetic-round");
        let mut data = terminal();
        assert_eq!(continuation(&data, &id, None).unwrap(), None);
        data["wager"]["status"] = json!("Pending");
        data["wager"]["bets"][0]["betdata"] = json!({"cmds":["freeSpin"]});
        assert_eq!(
            continuation(&data, &id, None).unwrap(),
            Some((0, "freeSpin".into()))
        );
        assert!(continuation(&data, &id, Some(0)).is_err());
        assert!(continuation(&data, &json!("different"), None).is_err());
        data["wager"]["bets"][0]["betdata"]["cmds"] = json!([]);
        assert!(continuation(&data, &id, None).is_err());
    }
    #[test]
    fn published_csv_has_exact_jokerizer_normal_binding() {
        let csv = include_str!("../../../provider-work/yggdrasil-export/yggdrasil-rounds.csv");
        assert!(csv.lines().any(|row|row=="7301,Jokerizer,normal,BASIC,0.1,1.0,1.0,0,Finished,,True,11000.0,10999.0,0.0,False,1,rounds,True"));
    }
    async fn offline_continuation_budget(max_steps: usize) {
        use crate::{
            model::{CampaignPlan, InventorySnapshot, Job, ModeKind, RoundSpec},
            store::Store,
        };
        use tokio::{
            io::{AsyncReadExt, AsyncWriteExt},
            net::TcpListener,
        };
        let directory = tempfile::tempdir().unwrap();
        let store = Store::open(directory.path()).unwrap();
        let inventory:InventorySnapshot=serde_json::from_value(json!({"id":"yggdrasil-fixture","sources":[],"providers":[{"id":"yggdrasil","name":"Yggdrasil","ready":true,"campaign_eligible":true,"games":[{"id":"7301","name":"Jokerizer","ready":true,"modes":[{"key":"BASIC","type":"normal","label":"BASIC"}]}]}]})).unwrap();
        store.install_inventory(&inventory).unwrap();
        let settings = json!({"coin":"0.1","amount":"1","stake":"1"});
        let plan = CampaignPlan {
            schema_version: 1,
            id: "yggdrasil-fixture-campaign".into(),
            inventory_id: inventory.id.clone(),
            coverage: None,
            jobs: vec![Job {
                provider: "yggdrasil".into(),
                game: "7301".into(),
                mode: "BASIC".into(),
                samples: 1,
                settings: settings.clone(),
            }],
        };
        store.create_campaign(&plan).unwrap();
        let round = store
            .create_round(&RoundSpec {
                campaign_id: plan.id,
                inventory_id: inventory.id.clone(),
                job_index: 0,
                sample_index: 0,
                provider: "yggdrasil".into(),
                game: "7301".into(),
                mode: "BASIC".into(),
                kind: ModeKind::Normal,
                settings: settings.clone(),
            })
            .unwrap();
        let mut ctx = RunContext::new(
            store.clone(),
            round.id.clone(),
            "yggdrasil",
            2,
            max_steps,
            None,
        )
        .unwrap();
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        ctx.route_to_fixture(&format!("http://{}", listener.local_addr().unwrap()))
            .unwrap();
        let server_store = store.clone();
        let server_round = round.id.clone();
        let server = tokio::spawn(async move {
            for index in 0..if max_steps == 1 { 3 } else { 4 } {
                let (mut stream, _) = listener.accept().await.unwrap();
                let mut header_bytes = Vec::new();
                while !header_bytes.ends_with(b"\r\n\r\n") {
                    let mut b = [0];
                    stream.read_exact(&mut b).await.unwrap();
                    header_bytes.push(b[0]);
                    assert!(header_bytes.len() < 16000);
                }
                let head = String::from_utf8(header_bytes).unwrap();
                let headers: std::collections::BTreeMap<_, _> = head
                    .lines()
                    .skip(1)
                    .filter_map(|l| l.split_once(':'))
                    .map(|(k, v)| (k.to_ascii_lowercase(), v.trim().to_owned()))
                    .collect();
                let length = headers
                    .get("content-length")
                    .map(|v| v.parse::<usize>().unwrap())
                    .unwrap_or(0);
                let mut bytes = vec![0; length];
                stream.read_exact(&mut bytes).await.unwrap();
                let form: url::form_urlencoded::Parse<'_> = url::form_urlencoded::parse(&bytes);
                let form: std::collections::BTreeMap<String, String> = form.into_owned().collect();
                assert_eq!(
                    headers.get("origin").unwrap(),
                    "https://staticdemo.yggdrasilgaming.com"
                );
                let body = match index {
                    0 => {
                        assert!(
                            head.starts_with("GET /demo.yggdrasilgaming.com/game.web/service?")
                        );
                        assert!(head.lines().next().unwrap().contains("fn=game"));
                        assert!(head.lines().next().unwrap().contains("org=Demo"));
                        config()
                    }
                    1 => {
                        assert!(head.starts_with(
                            "POST /demo.yggdrasilgaming.com/game.web/service?fn=authenticate "
                        ));
                        assert_eq!(form.get("org").unwrap(), "Demo");
                        assert_eq!(form.get("userName").unwrap(), "undefined");
                        assert!(
                            headers
                                .get("cookie")
                                .unwrap()
                                .contains("demo-cookie=synthetic")
                        );
                        json!({"balance":{"cash":"100","currency":"EUR"},"token":"synthetic-owner"})
                    }
                    2 | 3 => {
                        assert!(head.starts_with(
                            "POST /demo.yggdrasilgaming.com/game.web/service?fn=play "
                        ));
                        assert_eq!(
                            headers.get("authorization").unwrap(),
                            "Bearer synthetic-owner"
                        );
                        assert_eq!(headers.get("game-id").unwrap(), "7301");
                        assert!(uuid::Uuid::parse_str(headers.get("x-crid").unwrap()).is_ok());
                        assert_eq!(
                            server_store.session(&server_round).unwrap().unwrap()["token"],
                            "synthetic-owner"
                        );
                        let journal = server_store.exchanges(&server_round).unwrap();
                        assert!(journal.last().unwrap().request.financial);
                        assert!(journal.last().unwrap().response.is_none());
                        if index == 2 {
                            assert_eq!(form.get("amount").unwrap(), "1.00");
                            assert_eq!(form.get("coin").unwrap(), "0.10");
                            assert_eq!(form.get("cmd").unwrap(), "");
                            let mut data = terminal();
                            data["wager"]["status"] = json!("Pending");
                            data["wager"]["bets"][0]["wonamount"] = json!("0");
                            data["wager"]["bets"][0]["betdata"] = json!({"cmds":["freeSpin"]});
                            data["resultBal"]["cash"] = json!("99");
                            data
                        } else {
                            assert_eq!(form.get("amount").unwrap(), "0.00");
                            assert_eq!(form.get("cmd").unwrap(), "freeSpin");
                            assert_eq!(form.get("wagerid").unwrap(), "synthetic-round");
                            assert_eq!(form.get("step").unwrap(), "1");
                            assert!(!form.contains_key("coin"));
                            let mut data = terminal();
                            data["wager"]["bets"] = json!([{"betamount":"1","wonamount":"0","step":0},{"betamount":"0","wonamount":"0.5","step":1}]);
                            data
                        }
                    }
                    _ => unreachable!(),
                };
                let body = json!({"code":0,"data":body}).to_string();
                let cookie = if index == 0 {
                    "Set-Cookie: demo-cookie=synthetic; Path=/; Secure\r\n"
                } else {
                    ""
                };
                let reply = format!(
                    "HTTP/1.1 200 OK\r\n{cookie}Content-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                );
                stream.write_all(reply.as_bytes()).await.unwrap();
                stream.shutdown().await.unwrap();
            }
        });
        let game = &inventory.providers[0].games[0];
        let outcome = execute(&ctx, game, &game.modes[0], &settings).await;
        tokio::time::timeout(std::time::Duration::from_secs(5), server)
            .await
            .unwrap_or_else(|_| panic!("fixture did not receive all requests: {outcome:?}"))
            .unwrap();
        if max_steps == 1 {
            assert!(outcome.is_err());
            assert_eq!(
                store
                    .exchanges(&round.id)
                    .unwrap()
                    .iter()
                    .filter(|e| e.request.financial)
                    .count(),
                1,
                "the root consumes the only financial action allowed by the budget"
            );
            assert!(store.pending_provider("yggdrasil").unwrap().is_some());
            assert!(store.round(&round.id).unwrap().outcome.is_none());
            return;
        }
        let mut outcome = outcome.unwrap();
        assert!(outcome.verify().unwrap());
        assert_eq!(
            (
                outcome.cost.as_str(),
                outcome.payout.as_str(),
                outcome.balance_after.as_str()
            ),
            ("1", "0.5", "99.5")
        );
        assert_eq!(outcome.native_round_id.as_deref(), Some("synthetic-round"));
        assert_eq!(
            store
                .exchanges(&round.id)
                .unwrap()
                .iter()
                .filter(|x| x.request.financial)
                .count(),
            2
        );
        assert!(!outcome.native_data.to_string().contains("synthetic-owner"));
    }

    #[tokio::test]
    async fn full_offline_demo_keeps_owner_and_closes_zero_amount_native_continuation() {
        offline_continuation_budget(2).await;
    }

    #[tokio::test]
    async fn budget_one_keeps_open_wager_without_sending_a_second_action() {
        offline_continuation_budget(1).await;
    }
}
