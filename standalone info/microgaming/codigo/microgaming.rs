//! A single fresh 3rd Base practice round, using the published HTTP contract.
//! Source: bet-collector/collection_claude_extra.py and microgaming-bindings.json.
use crate::{context::RunContext, model::*};
use anyhow::{Context, Result, ensure};
use rust_decimal::Decimal;
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use uuid::Uuid;

const GAME: &str = "3rd-base";
const MODULE: u64 = 11194;
const CLIENT: u64 = 50300;
const PRODUCT: u64 = 37241;
const API: &str = "https://api8888.maf-114.xyz/base";
const ORIGIN: &str = "https://luckyshow.contdelivery.com";
const USER_AGENT: &str =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:159.0) Gecko/20100101 Firefox/159.0";

struct Profile {
    token: String,
    currency: String,
    before: Decimal,
    stake: Decimal,
    raw_stake: Value,
}

pub fn validate(game: &Game, mode: &Mode, settings: &Value) -> Result<()> {
    ensure!(
        game.id == GAME && mode.kind == ModeKind::Normal && mode.key == "normal",
        "Microgaming supports only the reviewed 3rd Base normal entry"
    );
    ensure!(
        settings.is_null() || settings.as_object().is_some_and(|o| o.is_empty()),
        "Microgaming public binding has no overrides"
    );
    Ok(())
}

fn amount(value: &Value) -> Result<Decimal> {
    ensure!(
        value.is_number() || value.is_string(),
        "Microgaming native amount missing"
    );
    decimal(
        &value
            .as_str()
            .map(str::to_owned)
            .unwrap_or_else(|| value.to_string()),
    )
}

fn token(practice: &Value) -> Result<&str> {
    practice["tokens"]["userToken"]
        .as_str()
        .filter(|s| !s.is_empty() && *s != "[REDACTED]" && s.bytes().all(|b| b.is_ascii_graphic()))
        .context("Microgaming fresh practice token missing")
}

fn currency_codes(object: &Value, codes: &mut BTreeSet<String>) -> Result<()> {
    // No default currency is documented in the published wrapper. Only literal
    // native currency codes in the account/context can authorize a paid entry.
    // Unknown shapes remain archived for review, never interpreted as EUR.
    for field in [
        "currencyCode",
        "currencyIsoCode",
        "accountCurrencyCode",
        "currency",
    ] {
        let Some(value) = object.get(field).filter(|v| !v.is_null()) else {
            continue;
        };
        let code = if field == "currency" && value.is_object() {
            &value["code"]
        } else {
            value
        };
        let code = code
            .as_str()
            .filter(|s| {
                (3..=12).contains(&s.len())
                    && s.bytes()
                        .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit())
            })
            .context("Microgaming native currency code has an unreviewed shape")?;
        codes.insert(code.into());
    }
    Ok(())
}

fn profile(practice: &Value, initial: &Value) -> Result<Profile> {
    let token = token(practice)?.to_owned();
    let before = amount(&practice["account"]["balance"]["totalInAccountCurrency"])?;
    let context = &initial["context"];
    let game = &initial["gameResponse"];
    let (raw_stake, stake) = selected_bet(&game["financials"]["availableBetLimits"])?;
    ensure!(
        game["summary"]["isComplete"] == true
            && context["isReadOnly"] == true
            && context["game"]["transactionNumber"] == -1
            && stake > Decimal::ZERO
            && stake <= before
            && amount(&context["balances"]["totalInAccountCurrency"])? == before,
        "Microgaming practice session is not fresh and idle"
    );
    let mut codes = BTreeSet::new();
    for object in [
        &practice["account"],
        &practice["account"]["core"],
        &practice["account"]["balance"],
        context,
        &context["balances"],
    ] {
        currency_codes(object, &mut codes)?;
    }
    ensure!(
        codes.len() == 1,
        "Microgaming requires one explicit consistent native account currency before spin"
    );
    let currency = codes
        .into_iter()
        .next()
        .context("Microgaming account currency missing")?;
    Ok(Profile {
        token,
        currency,
        before,
        stake,
        raw_stake,
    })
}

fn selected_bet(menu: &Value) -> Result<(Value, Decimal)> {
    let default = &menu["defaultBet"];
    if !default.is_object() {
        return Ok((default.clone(), amount(default)?));
    }
    let minimum = amount(&menu["minBet"])?;
    let available = menu["availableBets"]
        .as_array()
        .context("Microgaming total bet menu missing")?;
    ensure!(
        minimum > Decimal::ZERO
            && available
                .iter()
                .any(|v| amount(v).is_ok_and(|v| v == minimum)),
        "Microgaming minimum total bet not offered"
    );
    ensure!(
        menu["betMultiplierDictatedByPaylines"] == false,
        "Microgaming paylines need a reviewed selector"
    );
    let coins = menu["minCoinsPerLineOrWay"]
        .as_u64()
        .filter(|v| *v > 0)
        .context("Microgaming minimum coins missing")?;
    let multipliers = menu["betMultipliers"]
        .as_array()
        .context("Microgaming multiplier menu missing")?;
    let sizes = menu["coinSizes"]
        .as_array()
        .context("Microgaming coin menu missing")?;
    for multiplier in multipliers {
        let multiplier = multiplier
            .as_u64()
            .filter(|v| *v > 0)
            .context("invalid Microgaming multiplier")?;
        for size in sizes {
            let size_amount = amount(size)?;
            if size_amount > Decimal::ZERO
                && exact_mul(
                    exact_mul(Decimal::from(coins), Decimal::from(multiplier))?,
                    size_amount,
                )? == minimum
            {
                return Ok((
                    json!({"betMultiplier":multiplier,"numCoinsPerLineOrWay":coins,"coinSize":size}),
                    minimum,
                ));
            }
        }
    }
    anyhow::bail!("Microgaming minimum has no matching wager parameters")
}

fn settlement(profile: &Profile, receipt: &Value) -> Result<RoundOutcome> {
    let context = &receipt["context"];
    let financials = &context["financials"];
    let response = &receipt["gameResponse"];
    ensure!(
        response["summary"]["isComplete"] == true
            && response["command"]["name"] == "Spin"
            && context["isReadOnly"] == false
            && context["game"]["transactionNumber"] == 1,
        "Microgaming native transaction remains open or is not the single expected Spin"
    );
    let cost = amount(&financials["totalTransactionBetAmount"])?;
    let payout = amount(&financials["totalTransactionPayoutAmount"])?;
    let after = amount(&context["balances"]["totalInAccountCurrency"])?;
    ensure!(
        cost == profile.stake
            && cost == amount(&financials["betAmount"])?
            && payout == amount(&financials["payoutAmount"])?,
        "Microgaming native debit or prize echoes disagree"
    );
    ensure!(
        exact_add(exact_sub(profile.before, cost)?, payout)? == after,
        "Microgaming native payout/wallet mismatch"
    );
    let mut codes = BTreeSet::new();
    currency_codes(context, &mut codes)?;
    currency_codes(&context["balances"], &mut codes)?;
    ensure!(
        codes.iter().all(|code| code == &profile.currency),
        "Microgaming native currency changed"
    );
    Ok(RoundOutcome {
        // The published contract has a transaction counter within the fresh
        // owner, not a globally unique round ID. Preserve that distinction.
        native_round_id: None,
        currency: profile.currency.clone(),
        monetary_unit: "native".into(),
        currency_source: "native_response".into(),
        balance_before: profile.before.to_string(),
        balance_after: after.to_string(),
        cost: cost.to_string(),
        payout: payout.to_string(),
        native_closed: true,
        checks: BTreeMap::from([
            ("native_offered_bet".into(), true),
            ("single_native_transaction".into(), true),
            ("independent_native_prize".into(), true),
            ("native_financial_echoes".into(), true),
        ]),
        native_data: json!({"module_id":MODULE,"client_id":CLIENT,"product_id":PRODUCT,
            "transaction_number":1,"offered_bet":profile.raw_stake,
            "closed_receipt":receipt}),
    })
}

fn practice_request() -> Value {
    let attributes = [
        ("bn", ""),
        ("dos", "Windows 10"),
        ("dosv", "NT 10.0"),
        ("it", "false"),
        ("mktn", ""),
        ("mbb", "Firefox"),
        ("mbbv", "159.0"),
        ("mdln", ""),
        ("ua", USER_AGENT),
        ("ff", "desktop"),
    ]
    .into_iter()
    .map(|(key, value)| json!({"shortCode":key,"value":value}))
    .collect::<Vec<_>>();
    json!({"sessionProductId":PRODUCT,"numLaunchTokens":10,
        "environment":{"clientTypeId":40,"languageCode":"en"},"deviceAttributes":attributes,
        "context":{"moduleId":MODULE,"clientId":CLIENT,"intent":1}})
}

async fn post(
    ctx: &RunContext,
    label: &str,
    path: &str,
    payload: &Value,
    token: Option<&str>,
    financial: bool,
) -> Result<Value> {
    let mut headers = BTreeMap::from([
        ("content-type".into(), "application/json".into()),
        ("accept".into(), "application/json".into()),
        ("accept-encoding".into(), "identity".into()),
        ("origin".into(), ORIGIN.into()),
        ("referer".into(), format!("{ORIGIN}/")),
        ("user-agent".into(), USER_AGENT.into()),
        ("x-clienttypeid".into(), "40".into()),
        ("x-correlationid".into(), Uuid::new_v4().to_string()),
        ("x-route-productid".into(), PRODUCT.to_string()),
        ("x-route-moduleid".into(), MODULE.to_string()),
    ]);
    if let Some(token) = token {
        headers.insert("authorization".into(), format!("Bearer {token}"));
    }
    let response = ctx
        .http(
            label,
            "POST",
            &format!("{API}{path}"),
            headers,
            serde_json::to_string(payload)?,
            financial,
        )
        .await?;
    ensure!(
        response.status == 200,
        "Microgaming HTTP {} at {label}",
        response.status
    );
    serde_json::from_str(&response.body).context("Microgaming native JSON response invalid")
}

pub async fn execute(
    ctx: &RunContext,
    game: &Game,
    mode: &Mode,
    settings: &Value,
) -> Result<RoundOutcome> {
    validate(game, mode, settings)?;
    let practice = post(
        ctx,
        "practice",
        "/user/public/v1/accounts/login/practice",
        &practice_request(),
        None,
        false,
    )
    .await?;
    let token = token(&practice)?;
    let path = format!("/play/public/v1/games2/module/{MODULE}/client/{CLIENT}/play/");
    let initial = post(
        ctx,
        "refresh",
        &format!("{path}refreshes"),
        &json!({"context":{"freeGames":null},"gameRequest":{}}),
        Some(token),
        false,
    )
    .await?;
    let profile = profile(&practice, &initial)?;
    ctx.save_session(&json!({"provider":"microgaming","game":GAME,"module_id":MODULE,"client_id":CLIENT,"product_id":PRODUCT,
        "user_token":profile.token,"currency":profile.currency,"practice":practice,"initialization":initial,
        "offered_bet":profile.raw_stake}))?;
    let receipt = post(
        ctx,
        "normal",
        &format!("{path}spins"),
        &json!({"context":{"freeGames":null},"gameRequest":{"bet":profile.raw_stake}}),
        Some(&profile.token),
        true,
    )
    .await?;
    // Only one normal action is demonstrated. An open round stays retained;
    // no guessed continuation and no replacement practice owner are created.
    settlement(&profile, &receipt)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn game_mode() -> (Game, Mode) {
        let mode = Mode {
            key: "normal".into(),
            kind: ModeKind::Normal,
            label: "Normal".into(),
            ready: true,
            requires_prerequisites: Value::Null,
            execution_source: None,
        };
        let game = Game {
            id: GAME.into(),
            name: "3rd Base".into(),
            ready: true,
            block_reason: String::new(),
            modes: vec![mode.clone()],
        };
        (game, mode)
    }

    fn practice() -> Value {
        json!({"tokens":{"userToken":"fixture-only"},
            "account":{"currencyCode":"EUR","balance":{"totalInAccountCurrency":"100"}}})
    }

    fn initial() -> Value {
        json!({"context":{"isReadOnly":true,"game":{"transactionNumber":-1},"balances":{"totalInAccountCurrency":"100"}},
            "gameResponse":{"summary":{"isComplete":true},"financials":{"availableBetLimits":{"defaultBet":"0.20","minimumBet":"0.10"}}}})
    }

    fn receipt() -> Value {
        json!({"context":{"isReadOnly":false,"game":{"transactionNumber":1},"balances":{"totalInAccountCurrency":"100.10"},
                "financials":{"totalTransactionBetAmount":"0.20","betAmount":"0.20","totalTransactionPayoutAmount":"0.30","payoutAmount":"0.30"}},
            "gameResponse":{"summary":{"isComplete":true},"command":{"name":"Spin"}}})
    }

    #[test]
    fn fixed_game_binding_matches_the_published_catalogue() {
        let catalog: Value = serde_json::from_str(include_str!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../docs/recolector/evidencia/microgaming-bindings.json"
        )))
        .unwrap();
        let binding = &catalog["games"][GAME];
        assert_eq!(binding["module_id"], MODULE);
        assert_eq!(binding["client_id"], CLIENT);
        let (game, mode) = game_mode();
        validate(&game, &mode, &Value::Null).unwrap();
        assert!(validate(&game, &mode, &json!({"currency":"EUR"})).is_err());
        let mut wrong = mode;
        wrong.key = "buy".into();
        wrong.kind = ModeKind::Purchase;
        assert!(validate(&game, &wrong, &Value::Null).is_err());
    }

    #[test]
    fn fresh_practice_uses_the_offered_default_not_the_minimum() {
        let p = profile(&practice(), &initial()).unwrap();
        assert_eq!(p.currency, "EUR");
        assert_eq!(p.before, Decimal::from(100));
        assert_eq!(p.stake, decimal("0.20").unwrap());
        assert_eq!(p.raw_stake, json!("0.20"));
        for (path, value) in [
            ("/context/isReadOnly", json!(false)),
            ("/context/game/transactionNumber", json!(0)),
            ("/gameResponse/summary/isComplete", json!(false)),
            ("/context/balances/totalInAccountCurrency", json!("99")),
            (
                "/gameResponse/financials/availableBetLimits/defaultBet",
                json!("0"),
            ),
            (
                "/gameResponse/financials/availableBetLimits/defaultBet",
                json!("101"),
            ),
            (
                "/gameResponse/financials/availableBetLimits/defaultBet",
                json!(true),
            ),
        ] {
            let mut bad = initial();
            *bad.pointer_mut(path).unwrap() = value;
            assert!(profile(&practice(), &bad).is_err(), "accepted {path}");
        }
    }

    #[test]
    fn currency_is_required_explicit_and_consistent_before_spin() {
        let mut missing = practice();
        missing["account"]
            .as_object_mut()
            .unwrap()
            .remove("currencyCode");
        assert!(profile(&missing, &initial()).is_err());
        let mut explicit = initial();
        explicit["context"]["accountCurrencyCode"] = json!("GBP");
        assert_eq!(profile(&missing, &explicit).unwrap().currency, "GBP");
        assert!(profile(&practice(), &explicit).is_err());
        missing["account"]["core"] = json!({"currencyIsoCode":"USD"});
        assert_eq!(profile(&missing, &initial()).unwrap().currency, "USD");
        assert!(profile(&missing, &explicit).is_err());
        for invalid in [json!("€"), json!(""), json!(false), json!(123)] {
            let mut bad = practice();
            bad["account"]["currencyCode"] = invalid;
            assert!(profile(&bad, &initial()).is_err());
        }
        let mut explicit = practice();
        explicit["account"]
            .as_object_mut()
            .unwrap()
            .remove("currencyCode");
        explicit["account"]["currency"] = json!({"code":"USD"});
        assert_eq!(profile(&explicit, &initial()).unwrap().currency, "USD");
    }

    #[test]
    fn complete_single_transaction_requires_independent_prize_and_wallet() {
        let p = profile(&practice(), &initial()).unwrap();
        let mut out = settlement(&p, &receipt()).unwrap();
        assert!(out.verify().unwrap());
        assert_eq!(
            (
                out.cost.as_str(),
                out.payout.as_str(),
                out.balance_after.as_str()
            ),
            ("0.20", "0.30", "100.10")
        );
        for (path, value) in [
            ("/gameResponse/summary/isComplete", json!(false)),
            ("/gameResponse/command/name", json!("Refresh")),
            ("/context/isReadOnly", json!(true)),
            ("/context/game/transactionNumber", json!(2)),
            (
                "/context/financials/totalTransactionBetAmount",
                json!("0.30"),
            ),
            ("/context/financials/betAmount", json!("0.10")),
            ("/context/financials/payoutAmount", json!("0.20")),
            (
                "/context/financials/totalTransactionPayoutAmount",
                json!("-0.30"),
            ),
            ("/context/balances/totalInAccountCurrency", json!("100.09")),
        ] {
            let mut bad = receipt();
            *bad.pointer_mut(path).unwrap() = value;
            assert!(settlement(&p, &bad).is_err(), "accepted {path}");
        }
        let mut bad = receipt();
        bad["context"]["accountCurrencyCode"] = json!("USD");
        assert!(settlement(&p, &bad).is_err());
    }

    fn context() -> (tempfile::TempDir, RunContext, Game, Mode) {
        use crate::store::Store;
        let dir = tempfile::tempdir().unwrap();
        let store = Store::open(dir.path()).unwrap();
        let (game, mode) = game_mode();
        let inventory = InventorySnapshot {
            id: "microgaming-fixture".into(),
            sources: vec![],
            providers: vec![ProviderInventory {
                id: "microgaming".into(),
                name: "Microgaming".into(),
                ready: true,
                campaign_eligible: true,
                protocol: Value::Null,
                games: vec![game.clone()],
            }],
        };
        store.install_inventory(&inventory).unwrap();
        store
            .create_campaign(&CampaignPlan {
                coverage: None,
                schema_version: 1,
                id: "fixture".into(),
                inventory_id: inventory.id.clone(),
                jobs: vec![Job {
                    provider: "microgaming".into(),
                    game: game.id.clone(),
                    mode: mode.key.clone(),
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
                provider: "microgaming".into(),
                game: game.id.clone(),
                mode: mode.key.clone(),
                kind: ModeKind::Normal,
                settings: Value::Null,
            })
            .unwrap();
        let ctx = RunContext::new(store, round.id, "microgaming", 2, 10, None).unwrap();
        (dir, ctx, game, mode)
    }

    async fn fixture(
        ctx: &RunContext,
        replies: Vec<Value>,
    ) -> (String, tokio::task::JoinHandle<Vec<Value>>) {
        use tokio::{
            io::{AsyncReadExt, AsyncWriteExt},
            net::TcpListener,
            time::{Duration, timeout},
        };
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let origin = format!("http://{}", listener.local_addr().unwrap());
        let store = ctx.store.clone();
        let round_id = ctx.round_id.clone();
        let task = tokio::spawn(async move {
            let mut requests = Vec::new();
            let mut correlations = BTreeSet::new();
            for (index, response) in replies.into_iter().enumerate() {
                let (mut stream, _) = timeout(Duration::from_secs(4), listener.accept())
                    .await
                    .unwrap()
                    .unwrap();
                let mut bytes = Vec::new();
                let end = loop {
                    let mut part = [0_u8; 4096];
                    let n = timeout(Duration::from_secs(4), stream.read(&mut part))
                        .await
                        .unwrap()
                        .unwrap();
                    assert!(n > 0);
                    bytes.extend_from_slice(&part[..n]);
                    if let Some(end) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
                        break end + 4;
                    }
                };
                let header_text = String::from_utf8(bytes[..end].to_vec()).unwrap();
                let headers = header_text
                    .lines()
                    .skip(1)
                    .filter_map(|line| line.split_once(':'))
                    .map(|(k, v)| (k.to_ascii_lowercase(), v.trim().to_owned()))
                    .collect::<BTreeMap<_, _>>();
                let len = headers["content-length"].parse::<usize>().unwrap();
                while bytes.len() < end + len {
                    let mut part = [0_u8; 4096];
                    let n = stream.read(&mut part).await.unwrap();
                    assert!(n > 0);
                    bytes.extend_from_slice(&part[..n]);
                }
                let body = String::from_utf8(bytes[end..].to_vec()).unwrap();
                let request: Value = serde_json::from_str(&body).unwrap();
                let path = header_text
                    .lines()
                    .next()
                    .unwrap()
                    .split_whitespace()
                    .nth(1)
                    .unwrap();
                let expected = match index {
                    0 => "/api8888.maf-114.xyz/base/user/public/v1/accounts/login/practice",
                    1 => {
                        "/api8888.maf-114.xyz/base/play/public/v1/games2/module/11194/client/50300/play/refreshes"
                    }
                    2 => {
                        "/api8888.maf-114.xyz/base/play/public/v1/games2/module/11194/client/50300/play/spins"
                    }
                    _ => panic!("unexpected additional native request"),
                };
                assert_eq!(path, expected);
                assert_eq!(headers["user-agent"], USER_AGENT);
                assert_eq!(headers["origin"], ORIGIN);
                assert_eq!(headers["x-route-productid"], "37241");
                assert_eq!(headers["x-route-moduleid"], "11194");
                assert_eq!(headers["x-clienttypeid"], "40");
                assert!(correlations.insert(headers["x-correlationid"].clone()));
                if index == 0 {
                    assert!(!headers.contains_key("authorization"));
                    assert_eq!(
                        request["context"],
                        json!({"moduleId":11194,"clientId":50300,"intent":1})
                    );
                    assert_eq!(request["sessionProductId"], 37241);
                    assert!(
                        request["deviceAttributes"]
                            .as_array()
                            .unwrap()
                            .iter()
                            .any(|r| r["shortCode"] == "ua" && r["value"] == USER_AGENT)
                    );
                } else {
                    assert_eq!(headers["authorization"], "Bearer fixture-only");
                    assert_eq!(headers["cookie"], "native=practice");
                }
                if index == 2 {
                    assert_eq!(
                        request,
                        json!({"context":{"freeGames":null},"gameRequest":{"bet":"0.20"}})
                    );
                    let owner = store.session(&round_id).unwrap().unwrap();
                    assert_eq!(owner["currency"], "EUR");
                    assert_eq!(owner["user_token"], "fixture-only");
                    let exchanges = store.exchanges(&round_id).unwrap();
                    let intent = exchanges.last().unwrap();
                    assert!(intent.request.financial && intent.response.is_none());
                    assert_eq!(intent.request.body, body);
                }
                requests.push(request);
                let body = response.to_string();
                let cookie = if index == 0 {
                    "Set-Cookie: native=practice; Path=/\r\n"
                } else {
                    ""
                };
                let wire = format!(
                    "HTTP/1.1 200 OK\r\nContent-Length: {}\r\n{cookie}Connection: close\r\n\r\n{body}",
                    body.len()
                );
                stream.write_all(wire.as_bytes()).await.unwrap();
            }
            requests
        });
        (origin, task)
    }

    #[tokio::test]
    async fn fresh_practice_cookie_and_token_authorize_exactly_one_native_spin() {
        let (_dir, mut ctx, game, mode) = context();
        let (origin, server) = fixture(&ctx, vec![practice(), initial(), receipt()]).await;
        ctx.route_to_fixture(&origin).unwrap();
        let mut outcome = execute(&ctx, &game, &mode, &json!({})).await.unwrap();
        assert_eq!(server.await.unwrap().len(), 3);
        assert!(outcome.verify().unwrap());
        assert_eq!(
            outcome.native_data["offered_bet"],
            initial()["gameResponse"]["financials"]["availableBetLimits"]["defaultBet"]
        );
        assert_eq!(
            ctx.store.complete(&ctx.round_id, &outcome).unwrap().status,
            RoundStatus::Verified
        );
        let financial = ctx
            .store
            .exchanges(&ctx.round_id)
            .unwrap()
            .into_iter()
            .filter(|e| e.request.financial)
            .collect::<Vec<_>>();
        assert_eq!(financial.len(), 1);
        assert!(financial[0].request.url.ends_with("/spins"));
    }

    #[tokio::test]
    async fn undocumented_currency_is_archived_without_any_spin() {
        let (_dir, mut ctx, game, mode) = context();
        let mut account = practice();
        account["account"]
            .as_object_mut()
            .unwrap()
            .remove("currencyCode");
        let (origin, server) = fixture(&ctx, vec![account, initial()]).await;
        ctx.route_to_fixture(&origin).unwrap();
        assert!(execute(&ctx, &game, &mode, &json!({})).await.is_err());
        assert_eq!(server.await.unwrap().len(), 2);
        let exchanges = ctx.store.exchanges(&ctx.round_id).unwrap();
        assert_eq!(exchanges.len(), 2);
        assert!(
            exchanges
                .iter()
                .all(|e| !e.request.financial && e.response.is_some())
        );
        assert!(ctx.store.session(&ctx.round_id).unwrap().is_none());
    }

    #[tokio::test]
    async fn an_open_transaction_is_retained_without_guessing_a_continuation() {
        let (_dir, mut ctx, game, mode) = context();
        let mut open = receipt();
        open["gameResponse"]["summary"]["isComplete"] = json!(false);
        let (origin, server) = fixture(&ctx, vec![practice(), initial(), open]).await;
        ctx.route_to_fixture(&origin).unwrap();
        assert!(execute(&ctx, &game, &mode, &json!({})).await.is_err());
        assert_eq!(server.await.unwrap().len(), 3);
        let exchanges = ctx.store.exchanges(&ctx.round_id).unwrap();
        assert_eq!(exchanges.iter().filter(|e| e.request.financial).count(), 1);
        assert!(ctx.store.pending_provider("microgaming").unwrap().is_some());
        assert!(ctx.store.round(&ctx.round_id).unwrap().outcome.is_none());
    }
}
