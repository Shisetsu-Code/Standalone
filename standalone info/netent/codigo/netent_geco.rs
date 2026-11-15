use crate::{
    context::RunContext,
    model::{Game, Mode, ModeKind, RoundOutcome, decimal, exact_div100, wallet_matches},
};
use anyhow::{Context, Result, ensure};
use rust_decimal::Decimal;
use serde_json::json;
use std::collections::BTreeMap;
use url::Url;

#[derive(serde::Deserialize)]
struct ReviewedGame {
    table_id: String,
    game_id: String,
}

#[derive(serde::Deserialize)]
struct SpecialProfile {
    #[serde(flatten)]
    game: ReviewedGame,
    source_path: String,
    source_sha256: String,
    free_actions: Vec<String>,
    modes: BTreeMap<String, SpecialMode>,
}

#[derive(serde::Deserialize)]
struct SpecialMode {
    action: String,
    factor: String,
    params: BTreeMap<String, String>,
}

fn special(game: &str, mode: &str) -> Option<(&'static SpecialProfile, &'static SpecialMode)> {
    static PROFILES: std::sync::OnceLock<BTreeMap<String, SpecialProfile>> =
        std::sync::OnceLock::new();
    let profile = PROFILES
        .get_or_init(|| {
            serde_json::from_slice(include_bytes!("../../bindings/netent-geco-modes.json"))
                .expect("reviewed NetEnt GECO special bindings")
        })
        .get(game)?;
    Some((profile, profile.modes.get(mode)?))
}

fn reviewed(game: &str) -> Option<&'static ReviewedGame> {
    static GAMES: std::sync::OnceLock<BTreeMap<String, ReviewedGame>> = std::sync::OnceLock::new();
    GAMES
        .get_or_init(|| {
            serde_json::from_slice(include_bytes!("../../bindings/netent-geco.json"))
                .expect("reviewed NetEnt GECO bindings")
        })
        .get(game)
}

pub fn supports(game: &Game, mode: &Mode) -> bool {
    (mode.kind == ModeKind::Normal && mode.key == "Spin" && reviewed(&game.id).is_some())
        || (matches!(
            mode.kind,
            ModeKind::Purchase | ModeKind::Variant | ModeKind::AnteBet | ModeKind::Booster
        ) && special(&game.id, &mode.key).is_some())
}

fn action_url(
    init: &Url,
    action: &str,
    wager: Option<&Quote>,
    mode: Option<(&SpecialProfile, &SpecialMode)>,
) -> Result<Url> {
    ensure!(
        matches!(
            (action, wager),
            ("spin", Some(_)) | ("drop" | "freespin" | "respin" | "initfreespin", None)
        ) || mode.is_some_and(|(profile, entry)| match wager {
            Some(_) => action == "featurebuy" && entry.action == action,
            None =>
                !matches!(action, "spin" | "featurebuy")
                    && profile.free_actions.iter().any(|allowed| allowed == action),
        }),
        "unreviewed GECO next action"
    );
    let mut url = init.clone();
    url.set_query(None);
    let mut params = url.query_pairs_mut();
    params.extend_pairs(init.query_pairs().filter(|(key, _)| {
        matches!(
            key.as_ref(),
            "sessid" | "gameId" | "wantsfreerounds" | "freeroundmode"
        ) || key.starts_with("ne_")
    }));
    params
        .append_pair("action", action)
        .append_pair("wantsreels", "true")
        .append_pair("no-cache", &uuid::Uuid::new_v4().to_string());
    if let Some(wager) = wager {
        let mut quoted: BTreeMap<String, String> = wager
            .parameters()
            .into_iter()
            .map(|(k, v)| (k.into(), v))
            .collect();
        if let Some((_, entry)) = mode {
            quoted.extend(entry.params.clone());
        }
        params.extend_pairs(quoted);
    }
    drop(params);
    Ok(url)
}

pub async fn execute(ctx: &RunContext, game: &Game, mode: &Mode) -> Result<RoundOutcome> {
    let selected = special(&game.id, &mode.key);
    let (binding, asset) = if let Some((profile, _)) = selected {
        (
            &profile.game,
            Some((profile.source_path.as_str(), profile.source_sha256.as_str())),
        )
    } else {
        (reviewed(&game.id).context("unreviewed GECO game")?, None)
    };
    let (init, referer) =
        super::netent_launch::open_geco(ctx, &game.id, &binding.table_id, &binding.game_id, asset)
            .await?;
    let native_headers = |referer: &str| {
        BTreeMap::from([
            ("accept".into(), "*/*".into()),
            ("referer".into(), referer.into()),
            ("cookie".into(), String::new()),
        ])
    };
    let currency = init
        .query_pairs()
        .find(|(key, _)| key == "ne_currency")
        .map(|(_, v)| v.into_owned())
        .context("missing demo currency")?;
    let response = ctx
        .http(
            "netent_geco_init",
            "GET",
            init.as_str(),
            native_headers(&referer),
            String::new(),
            false,
        )
        .await?;
    ensure!(
        response.status == 200,
        "HTTP {} at GECO initialization",
        response.status
    );
    let mut initial = fields(&response.body)?;
    ensure!(
        initial.get("gameId").is_none_or(|v| *v == binding.game_id)
            && initial
                .get("playercurrencyiso")
                .is_none_or(|v| *v == currency),
        "GECO initialization owner changed"
    );
    initial
        .entry("gameId".into())
        .or_insert_with(|| binding.game_id.clone());
    let wager = quote(&initial)?;
    let factor = selected
        .map(|(_, entry)| decimal(&entry.factor))
        .transpose()?
        .unwrap_or(Decimal::ONE);
    ensure!(factor > Decimal::ZERO, "invalid GECO mode cost factor");
    let cost = Decimal::from(wager.cents)
        .checked_mul(factor)
        .context("GECO mode cost overflow")?;
    let balance = decimal(required(&initial, "credit")?)?;
    ensure!(
        cost.fract().is_zero() && balance.fract().is_zero() && balance >= cost,
        "insufficient or invalid GECO demo credit"
    );
    ctx.save_session(
        &json!({"geco_init":init.as_str(),"native_game":binding.game_id,"table":binding.table_id}),
    )?;
    let mut next = selected
        .map_or("spin", |(_, entry)| entry.action.as_str())
        .to_owned();
    for index in 0..ctx.max_steps().min(400) {
        let url = action_url(&init, &next, (index == 0).then_some(&wager), selected)?;
        let response = ctx
            .http(
                match (index, &mode.kind) {
                    (0, ModeKind::Purchase) => "netent_geco_purchase",
                    (0, _) => "netent_geco_spin",
                    _ => "netent_geco_continue",
                },
                "GET",
                url.as_str(),
                native_headers("https://showcase.evo-games.com/"),
                String::new(),
                true,
            )
            .await?;
        ensure!(
            response.status == 200,
            "HTTP {} at GECO action",
            response.status
        );
        let current = fields(&response.body)?;
        ensure!(
            required(&current, "playforfun")? == "true"
                && current.get("gameId").is_none_or(|v| *v == binding.game_id)
                && ["error", "errorcode"]
                    .into_iter()
                    .all(|k| current.get(k).is_none_or(|v| v.is_empty() || v == "0")),
            "GECO did not acknowledge the selected demo action"
        );
        next = required(&current, "nextaction")?.into();
        if required(&current, "gameover")? == "true" {
            if let Some((_, entry)) = selected {
                if let Some(math) = entry.params.get("bet.mathMode") {
                    ensure!(
                        current.get("mathMode") == Some(math),
                        "GECO math mode was not acknowledged"
                    );
                }
            }
            let mut outcome = reconcile_cost(&initial, &current, &currency, &wager, cost)?;
            if let Some((profile, entry)) = selected {
                outcome.native_data["selector"] = json!({"mode":mode.key,"params":entry.params,"source_sha256":profile.source_sha256});
            }
            return Ok(outcome);
        }
    }
    anyhow::bail!("GECO continuation limit reached")
}

type Fields = BTreeMap<String, String>;

pub(crate) fn fields(data: &str) -> Result<Fields> {
    let mut fields = Fields::new();
    for (key, value) in url::form_urlencoded::parse(data.as_bytes()) {
        if let Some(previous) = fields.insert(key.into_owned(), value.to_string()) {
            ensure!(previous == value, "GECO response has conflicting fields");
        }
    }
    if !fields.contains_key("nextaction")
        && fields.get("gameover").is_some_and(|v| v == "true")
        && fields.get("allowedactions").is_some_and(|v| v == "spin")
    {
        fields.insert("nextaction".into(), "spin".into());
    }
    Ok(fields)
}

fn required<'a>(fields: &'a Fields, key: &str) -> Result<&'a str> {
    fields
        .get(key)
        .map(String::as_str)
        .filter(|s| !s.is_empty())
        .with_context(|| format!("GECO field {key} missing"))
}

fn idle(fields: &Fields) -> Result<()> {
    ensure!(
        required(fields, "playforfun")? == "true"
            && required(fields, "gameover")? == "true"
            && required(fields, "nextaction")? == "spin"
            && ["error", "errorcode"]
                .into_iter()
                .all(|k| fields.get(k).is_none_or(|v| v.is_empty() || v == "0")),
        "GECO response does not confirm an idle demo"
    );
    Ok(())
}

fn minimum(fields: &Fields, key: &str) -> Result<u64> {
    let mut min = u64::MAX;
    for entry in required(fields, key)?.split(',') {
        let value: u64 = entry
            .parse()
            .with_context(|| format!("invalid GECO menu {key}"))?;
        ensure!(value > 0, "GECO menu has a nonpositive option");
        min = min.min(value);
    }
    Ok(min)
}

#[derive(Debug, PartialEq)]
pub(crate) struct Quote {
    level: u64,
    denomination: u64,
    lines: String,
    cents: u64,
}

impl Quote {
    pub(crate) fn parameters(&self) -> BTreeMap<&'static str, String> {
        BTreeMap::from([
            ("bet.betlevel", self.level.to_string()),
            ("bet.denomination", self.denomination.to_string()),
            ("bet.betlines", self.lines.clone()),
        ])
    }
}

pub(crate) fn quote(fields: &Fields) -> Result<Quote> {
    idle(fields)?;
    let level = minimum(fields, "betlevel.all")?;
    let denomination = minimum(fields, "denomination.all")?;
    let selection = required(fields, "bl.standard")?;
    let ids: Vec<_> = selection.split(',').collect();
    let (mut lines, mut weights) = if ids.len() == 1 && ids[0] != "0" {
        ensure!(
            required(fields, "bl.i0.line")?.contains('/'),
            "unreviewed GECO line selector"
        );
        let mut ways = Vec::new();
        for key in fields.keys() {
            let Some(index) = key.strip_prefix("bl.i").and_then(|v| v.strip_suffix(".id")) else {
                continue;
            };
            let _: u64 = index.parse()?;
            let id: u64 = required(fields, key)?.parse()?;
            let coins: u64 = required(fields, &format!("bl.i{index}.coins"))?.parse()?;
            ensure!(
                coins != 0 && !ways.iter().any(|&(_, previous)| previous == id),
                "invalid GECO ways offer"
            );
            ways.push((coins, id));
        }
        let offered: u64 = selection.parse()?;
        ensure!(
            ways.iter().any(|&(_, id)| id == offered),
            "GECO selected ways absent from menu"
        );
        let (coins, id) = ways.into_iter().min().context("GECO ways menu empty")?;
        (id.to_string(), coins)
    } else {
        let mut indices = ids
            .iter()
            .map(|id| id.parse::<usize>())
            .collect::<std::result::Result<Vec<_>, _>>()?;
        indices.sort_unstable();
        ensure!(
            indices.into_iter().eq(0..ids.len()),
            "unreviewed GECO line indexing"
        );
        let coins = (0..ids.len()).try_fold(0_u64, |sum, index| {
            let coins = required(fields, &format!("bl.i{index}.coins"))?.parse::<u64>()?;
            sum.checked_add(coins).context("GECO line cost overflow")
        })?;
        (format!("0-{}", ids.len() - 1), coins)
    };
    // These desktop clients send a title-specific selector for an unchanged wager.
    match (
        fields.get("gameId").map(String::as_str),
        lines.as_str(),
        weights,
    ) {
        (Some("fairymirror_not_mobile_sw"), "0-0", 10) => lines = "243".into(),
        (Some("narcos_not_mobile_sw"), "243", 20) => lines = "0-0".into(),
        // Reviewed config SHA-256: 92dc14c248bd857c349f29f4883eea852b83e97ff6be3ed02843644d4d67c932.
        (Some("butterflystaxx2_not_mobile_sw"), "0-39", 40) => weights = 25,
        (
            Some(
                "fairymirror_not_mobile_sw"
                | "narcos_not_mobile_sw"
                | "butterflystaxx2_not_mobile_sw",
            ),
            _,
            _,
        ) => {
            anyhow::bail!("reviewed GECO client has an unexpected line offer")
        }
        _ => {}
    }
    let cents = denomination
        .checked_mul(level)
        .and_then(|n| n.checked_mul(weights))
        .filter(|v| *v > 0)
        .context("invalid GECO base cost")?;
    Ok(Quote {
        denomination,
        level,
        lines,
        cents,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn netent_geco_journals_bootstrap_spin_and_free_continuation() {
        use crate::model::{CampaignPlan, InventorySnapshot, Job, RoundSpec};
        use crate::store::Store;
        use tokio::{
            io::{AsyncReadExt, AsyncWriteExt},
            net::TcpListener,
        };

        let config = json!({"table_id":"alohaxmas0000000","game_provider":"netent","game_engine":"geco",
            "userType":0,"currencyCode":"USD","currencyDecimals":2,"bare_session_id":"session123",
            "wrappedLaunchParams":{"gameServer":"https://showcase.evo-games.com/public/rng/dragon",
            "gameId":"alohaxmas_not_mobile_sw","sessionId":"session123","ne_currency":"USD","ne_device":"desktop",
            "ne_casinoId":"fixture","ne_evo_token":"x","ne_evo_token1":"y","ne_evo_token2":"z"}});
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let local = format!("http://{}", listener.local_addr().unwrap());
        let server = tokio::spawn(async move {
            let nodes = [
                ("/slots/aloha-christmas/", "200 OK", "", r#"var game_api_settings = {"nonce":"a012bc3456"};"#.into()),
                ("/wp-json/games/v1/start?", "200 OK", "", r#"{"success":true,"payload":"https://showcase.evo-games.com/entry?fixture=1"}"#.into()),
                ("/entry?", "302 Found", "Location: /frontend/evo/r2/#balance_id=demo-fixture&table_id=alohaxmas0000000\r\n", String::new()),
                ("/frontend/evo/r2/", "200 OK", "", String::new()),
                ("/config?", "200 OK", "", config.to_string()),
                ("action=init", "200 OK", "", "playforfun=true&gameover=true&nextaction=spin&credit=100&betlevel.all=1&denomination.all=1&bl.standard=0&bl.i0.coins=20".into()),
                ("action=spin", "200 OK", "", "playforfun=true&gameover=false&nextaction=drop&credit=80&gameRoundId=r1".into()),
                ("action=drop", "200 OK", "", "playforfun=true&gameover=true&nextaction=spin&credit=95&gameRoundId=r1&totalwin.cents=15".into()),
            ];
            for (expected, status, extra, body) in nodes {
                let (mut socket, _) = listener.accept().await.unwrap();
                let mut data = Vec::new();
                while !data.ends_with(b"\r\n\r\n") {
                    data.push(socket.read_u8().await.unwrap());
                    assert!(data.len() < 16384);
                }
                let request = String::from_utf8(data).unwrap();
                assert!(
                    request.lines().next().unwrap().contains(expected),
                    "expected {expected}"
                );
                if expected == "action=spin" {
                    assert!(request.contains("bet.betlines=0-0"));
                }
                if expected == "action=drop" {
                    assert!(!request.contains("bet.betlines="));
                }
                socket.write_all(format!("HTTP/1.1 {status}\r\n{extra}Connection: close\r\nContent-Length: {}\r\n\r\n{body}", body.len()).as_bytes()).await.unwrap();
            }
        });
        let directory = tempfile::tempdir().unwrap();
        let store = Store::open(directory.path()).unwrap();
        let inventory: InventorySnapshot = serde_json::from_value(json!({"id":"geco-test","sources":[],"providers":[
            {"id":"netent","name":"NetEnt","ready":true,"campaign_eligible":true,"games":[
                {"id":"aloha-christmas","name":"Aloha Christmas","ready":true,"modes":[{"key":"Spin","type":"normal","label":"Spin"}]}]}]})).unwrap();
        let game = &inventory.providers[0].games[0];
        store.install_inventory(&inventory).unwrap();
        let plan = CampaignPlan {
            schema_version: 1,
            id: "geco-fixture".into(),
            inventory_id: inventory.id.clone(),
            coverage: None,
            jobs: vec![Job {
                provider: "netent".into(),
                game: game.id.clone(),
                mode: "Spin".into(),
                samples: 1,
                settings: json!({}),
            }],
        };
        store.create_campaign(&plan).unwrap();
        let round = store
            .create_round(&RoundSpec {
                campaign_id: plan.id,
                inventory_id: inventory.id.clone(),
                job_index: 0,
                sample_index: 0,
                provider: "netent".into(),
                game: game.id.clone(),
                mode: "Spin".into(),
                kind: ModeKind::Normal,
                settings: json!({}),
            })
            .unwrap();
        let mut ctx =
            RunContext::new(store.clone(), round.id.clone(), "netent", 2, 10, None).unwrap();
        ctx.route_to_fixture(&local).unwrap();
        let result = execute(&ctx, game, &game.modes[0]).await.unwrap();
        server.await.unwrap();
        assert_eq!(decimal(&result.cost).unwrap(), Decimal::new(20, 2));
        assert_eq!(decimal(&result.payout).unwrap(), Decimal::new(15, 2));
        let exchanges = store.exchanges(&round.id).unwrap();
        assert_eq!(exchanges.len(), 8);
        assert!(exchanges[..6].iter().all(|item| !item.request.financial));
        assert!(exchanges[6..].iter().all(|item| item.request.financial));
    }

    #[test]
    fn continuation_never_reuses_paid_query_or_opens_another_round() {
        let init = url::Url::parse("https://showcase.evo-games.com/native?action=init&sessid=owner&gameId=fixture&ne_mode=demo&wantsfreerounds=true&freeroundmode=false&wantsreels=true&no-cache=old").unwrap();
        let endpoint = action_url(&init, "drop", None, None).unwrap();
        let params: BTreeMap<_, _> = endpoint.query_pairs().into_owned().collect();
        assert_eq!(params["sessid"], "owner");
        assert_eq!(params["action"], "drop");
        assert_ne!(params["no-cache"], "old");
        assert!(!params.keys().any(|key| key.starts_with("bet.")));
        assert!(action_url(&init, "spin", None, None).is_err());
        assert!(action_url(&init, "featurebuy", None, None).is_err());
    }

    #[test]
    fn purchase_uses_reviewed_selector_and_one_adjusted_cost() {
        let init = Url::parse("https://showcase.evo-games.com/native?sessid=owner").unwrap();
        let selected = special("cupcakes", "FeatureBuy").unwrap();
        let start = fields("playforfun=true&gameover=true&nextaction=spin&credit=10000&betlevel.all=1&denomination.all=1&bl.standard=0&bl.i0.coins=20").unwrap();
        let wager = quote(&start).unwrap();
        let purchase = action_url(&init, "featurebuy", Some(&wager), Some(selected)).unwrap();
        let params: BTreeMap<_, _> = purchase.query_pairs().into_owned().collect();
        assert_eq!(params["buyFeature"], "true");
        assert_eq!(params["bet.betlines"], "");
        assert_eq!(
            purchase
                .query_pairs()
                .filter(|(key, _)| key == "bet.betlines")
                .count(),
            1
        );
        let continuation = action_url(&init, "freespin", None, Some(selected)).unwrap();
        assert!(
            !continuation
                .query_pairs()
                .any(|(key, _)| key == "buyFeature")
        );
        assert!(action_url(&init, "featurebuy", None, Some(selected)).is_err());
        let end = fields("playforfun=true&gameover=true&nextaction=spin&credit=8100&gameRoundId=r1&totalwin.cents=100").unwrap();
        let receipt = reconcile_cost(&start, &end, "USD", &wager, Decimal::from(2000)).unwrap();
        assert_eq!(decimal(&receipt.cost).unwrap(), Decimal::from(20));
        assert_eq!(decimal(&receipt.payout).unwrap(), Decimal::ONE);
    }

    #[test]
    fn reviewed_clients_use_their_accepted_selector_even_when_the_menu_disagrees() {
        for (game, offered, coins, selector) in [
            ("fairymirror_not_mobile_sw", "0", "10", "243"),
            ("narcos_not_mobile_sw", "243", "20", "0-0"),
        ] {
            let initial = fields(&format!(
                "gameId={game}&playforfun=true&gameover=true&nextaction=spin&betlevel.all=1&denomination.all=1&bl.standard={offered}&bl.i0.id={offered}&bl.i0.coins={coins}&bl.i0.line=0/1/2"
            ))
            .unwrap();
            let quote = quote(&initial).unwrap();
            assert_eq!(quote.parameters()["bet.betlines"], selector);
            assert_eq!(quote.cents.to_string(), coins);
        }
    }

    #[test]
    fn butterfly_client_charges_the_configured_coin_count() {
        let mut initial = fields(
            "gameId=butterflystaxx2_not_mobile_sw&playforfun=true&gameover=true&nextaction=spin&betlevel.all=1&denomination.all=1",
        )
        .unwrap();
        initial.insert(
            "bl.standard".into(),
            (0..40).map(|n| n.to_string()).collect::<Vec<_>>().join(","),
        );
        for index in 0..40 {
            initial.insert(format!("bl.i{index}.coins"), "1".into());
        }
        let quote = quote(&initial).unwrap();
        assert_eq!(quote.parameters()["bet.betlines"], "0-39");
        assert_eq!(quote.cents, 25);
    }
}

pub(crate) fn reconcile(start: &Fields, end: &Fields, currency: &str) -> Result<RoundOutcome> {
    let wager = quote(start)?;
    reconcile_cost(start, end, currency, &wager, Decimal::from(wager.cents))
}

fn reconcile_cost(
    start: &Fields,
    end: &Fields,
    currency: &str,
    wager: &Quote,
    cost: Decimal,
) -> Result<RoundOutcome> {
    idle(end)?;
    let before = decimal(required(start, "credit")?)?;
    let after = decimal(required(end, "credit")?)?;
    let payout = decimal(required(end, "totalwin.cents")?)?;
    ensure!(
        [before, after, payout]
            .iter()
            .all(|v| *v >= Decimal::ZERO && v.fract().is_zero())
            && before >= cost
            && wallet_matches(before, after, cost, payout),
        "GECO cash and native prize do not reconcile"
    );
    ensure!(
        currency.len() == 3 && currency.bytes().all(|b| b.is_ascii_uppercase()),
        "invalid GECO demo currency"
    );
    let native_round = end
        .get("gameRoundId")
        .filter(|id| !id.is_empty())
        .context("GECO terminal response has no round identity")?;
    ensure!(
        start.get("gameRoundId") != Some(native_round),
        "GECO round identity did not advance"
    );
    Ok(RoundOutcome {
        native_round_id: Some(native_round.clone()),
        currency: currency.into(),
        currency_source: "launcher_parameter".into(),
        monetary_unit: "major".into(),
        balance_before: exact_div100(before)?.to_string(),
        balance_after: exact_div100(after)?.to_string(),
        cost: exact_div100(cost)?.to_string(),
        payout: exact_div100(payout)?.to_string(),
        native_closed: true,
        checks: BTreeMap::from([
            ("demo".into(), true),
            ("native_quote".into(), true),
            ("native_prize".into(), true),
        ]),
        native_data: json!({"bet":wager.parameters()}),
    })
}
