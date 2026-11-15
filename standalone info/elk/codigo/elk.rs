//! Source-bound Propaganda 2 public stage-demo normal round.
use crate::{
    context::RunContext,
    model::{
        ExchangeRecord, Game, Mode, ModeKind, RoundOutcome, WireRequest, decimal, exact_sub,
        now_ms, sha256, wallet_matches,
    },
};
use anyhow::{Context, Result, ensure};
use regex::Regex;
use roxmltree::{Document, Node};
use rust_decimal::Decimal;
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use url::Url;
use uuid::Uuid;

const STATIC: &str = "https://static-stage.contentmedia.eu";
const CAPI: &str = "https://gc5-stage.contentmedia.eu/capi";
const GAME_ID: &str = "10276";

#[derive(Clone, Debug, PartialEq)]
struct Offer {
    level: String,
    amount: Decimal,
}
pub fn validate(game: &Game, mode: &Mode, settings: &Value) -> Result<()> {
    ensure!(
        game.id == "propaganda-2" && settings["game_id"] == GAME_ID && settings["xdm"] == "0",
        "ELK game is not the reviewed public catalogue binding"
    );
    ensure!(
        mode.kind == ModeKind::Normal && mode.key == "DEF",
        "only reviewed ELK normal mode is supported"
    );
    Ok(())
}

fn xml(text: &str) -> Result<Document<'_>> {
    let upper = text.to_ascii_uppercase();
    ensure!(
        !upper.contains("<!DOCTYPE") && !upper.contains("<!ENTITY"),
        "native XML declarations are not permitted"
    );
    Document::parse(text).context("invalid native XML")
}
fn node<'a, 'input>(mut root: Node<'a, 'input>, path: &str) -> Result<Node<'a, 'input>> {
    for part in path.split('/') {
        let mut matches = root
            .children()
            .filter(|n| n.is_element() && n.tag_name().name() == part);
        root = matches.next().context("missing native XML field")?;
        ensure!(
            matches.next().is_none(),
            "ambiguous duplicate native XML field"
        );
    }
    Ok(root)
}
fn value(root: Node<'_, '_>, path: &str) -> Result<String> {
    node(root, path)?
        .text()
        .filter(|s| !s.is_empty())
        .map(str::to_owned)
        .context("empty native XML value")
}
fn money(raw: &str) -> Result<Decimal> {
    let amount = decimal(raw)?;
    ensure!(amount >= Decimal::ZERO, "negative native money");
    Ok(amount)
}
fn field(root: Node<'_, '_>, path: &str) -> Result<Decimal> {
    money(&value(root, path)?)
}
fn response<'a>(text: &'a str, method: &str) -> Result<Document<'a>> {
    let document = xml(text)?;
    let root = document.root_element();
    ensure!(
        root.tag_name().name() == "response"
            && value(root, "errorcode")? == "0"
            && value(root, "method")? == method,
        "native method or response status mismatch"
    );
    Ok(document)
}

fn initial_offer(text: &str) -> Result<Offer> {
    let document = response(text, "init")?;
    let root = document.root_element();
    ensure!(
        value(root, "roundid")? == "0"
            && field(root, "gamesession/totbet")? == Decimal::ZERO
            && field(root, "gamesession/totwon")? == Decimal::ZERO,
        "not a fresh public demo"
    );
    ensure!(
        value(root, "player/currency")? == "EUR" && field(root, "player/balance")? > Decimal::ZERO,
        "native demo currency or wallet mismatch"
    );
    ensure!(
        !value(root, "gamesession/id")?.is_empty(),
        "native session missing"
    );
    ensure!(
        !root
            .children()
            .any(|n| n.has_tag_name("variants") && n.children().any(|n| n.is_element())),
        "native variants need an explicit reviewed selector"
    );
    let table_text = value(root, "game/paytable")?;
    let table = xml(&table_text)?;
    ensure!(
        table.root_element().attribute("gameid") == Some(GAME_ID),
        "native paytable game identity mismatch"
    );
    let levels = node(root, "betlevels")?;
    ensure!(
        levels.attribute("bmode") == Some("true"),
        "reviewed modern ELK bet mode contract changed"
    );
    let mut offers = Vec::new();
    for level in levels.children().filter(|n| n.has_tag_name("betlevel")) {
        let id = level
            .attribute("id")
            .context("native bet level identifier missing")?;
        ensure!(
            !id.is_empty() && id.bytes().all(|b| b.is_ascii_digit()),
            "invalid native bet level identifier"
        );
        let numeric_id: u64 = id.parse()?;
        let modes = node(level, "bmodes")?;
        let mut normal = modes
            .children()
            .filter(|n| n.has_tag_name("bmode") && n.attribute("id") == Some("DEF"));
        if let Some(normal_mode) = normal.next() {
            ensure!(normal.next().is_none(), "duplicate native normal mode");
            let amount = money(
                normal_mode
                    .attribute("amount")
                    .context("published normal price missing")?,
            )?;
            if amount > Decimal::ZERO {
                offers.push((amount, numeric_id, id.to_owned()));
            }
        }
    }
    offers.sort();
    let (amount, _, level) = offers
        .into_iter()
        .next()
        .context("no published positive normal price")?;
    ensure!(
        field(root, "player/balance")? >= amount,
        "insufficient fictitious balance"
    );
    Ok(Offer { level, amount })
}

fn result_closure(
    init: Node<'_, '_>,
    purchase: Node<'_, '_>,
    expected_win: Decimal,
) -> Result<usize> {
    let table_text = value(init, "game/paytable")?;
    let table = xml(&table_text)?;
    let modes: BTreeSet<_> = table
        .root_element()
        .children()
        .filter(|n| n.has_tag_name("MODE"))
        .filter_map(|n| n.attribute("name"))
        .collect();
    ensure!(!modes.is_empty(), "native paytable modes missing");
    let results: Vec<_> = purchase.children().filter(|n| n.is_element()).collect();
    ensure!(
        !results.is_empty() && results.iter().all(|n| n.has_tag_name("RESULT")),
        "unreviewed native purchase continuation"
    );
    for result in &results {
        ensure!(
            result
                .attribute("mode")
                .is_some_and(|mode| modes.contains(mode)),
            "unpublished native result mode"
        );
    }
    if results.iter().any(|n| n.attribute("resultIndex").is_some()) {
        for (i, result) in results.iter().enumerate() {
            ensure!(
                result
                    .attribute("resultIndex")
                    .and_then(|s| s.parse::<usize>().ok())
                    == Some(i),
                "native result sequence mismatch"
            );
        }
    }
    let last = *results.last().unwrap();
    for key in ["freespin", "freespins", "fsleft"] {
        if let Some(raw) = last.attribute(key) {
            ensure!(money(raw)? == Decimal::ZERO, "native bonus steps remain");
        }
    }
    for actions in last.children().filter(|n| n.has_tag_name("ACTIONS")) {
        if let Some(raw) = actions.attribute("fscount") {
            ensure!(money(raw)? == Decimal::ZERO, "native bonus actions remain");
        }
    }
    if let Some(raw) = last.attribute("amounttotal") {
        ensure!(
            money(raw)? == expected_win,
            "native final result total mismatch"
        );
    }
    // Reviewed ELK counters distinguish continuation counts from persistent meters.
    let known = [
        "bonus-counter",
        "freedrops",
        "redrops",
        "free-drops",
        "free-spins",
        "respins",
        "freespins",
        "subrounds",
        "dropz",
        "respins-base",
        "respins-bonus",
        "extra-drops",
        "kitty-free-drops",
        "drops",
        "coin-game-counter",
        "lives",
        "sub-rounds",
        "coin-chase-counter",
        "",
        "bonus-symbols",
        "super-bonus-symbols",
        "both-ways",
        "life-lines",
        "bonus spins",
        "casino spins",
        "spins",
        "extras",
        "bonus-spins",
        "progress",
        "base-multiplier",
        "levels",
        "features-collected",
        "bonus-respins",
    ];
    let meters = [
        "win-multiplier",
        "multiplier",
        "collect-bonuses",
        "body-counter",
        "win multiplier",
        "remembered-multiplier",
    ];
    for counters in last.children().filter(|n| n.has_tag_name("COUNTERS")) {
        for counter in counters.children().filter(|n| n.has_tag_name("COUNTER")) {
            let name = counter
                .attribute("name")
                .context("native counter name missing")?;
            ensure!(
                known.contains(&name) || meters.contains(&name),
                "unreviewed native continuation counter"
            );
            if !meters.contains(&name) {
                ensure!(
                    money(counter.attribute("left").unwrap_or("0"))? == Decimal::ZERO,
                    "native continuation counter remains"
                );
            }
        }
    }
    Ok(results.len())
}

fn settlement(
    initial: &str,
    purchased: &str,
    checked: &str,
    offer: &Offer,
) -> Result<RoundOutcome> {
    ensure!(
        initial_offer(initial)? == *offer,
        "control is not the native normal minimum"
    );
    let init_doc = response(initial, "init")?;
    let purchase_doc = response(purchased, "purchase")?;
    let check_doc = response(checked, "checkwin")?;
    let (init, purchase, check) = (
        init_doc.root_element(),
        purchase_doc.root_element(),
        check_doc.root_element(),
    );
    for document in [purchase, check] {
        ensure!(
            value(document, "player/currency")? == "EUR",
            "native currency changed"
        );
    }
    let round = value(purchase, "roundid")?;
    let info = node(purchase, "roundinfo")?;
    ensure!(
        round != "0" && value(info, "roundid")? == round && value(check, "roundid")? == round,
        "native round identity mismatch"
    );
    ensure!(
        value(info, "currency")? == "EUR"
            && value(info, "bmode")? == "DEF"
            && value(info, "betlevel")? == offer.level,
        "native control echo mismatch"
    );
    let cost = field(info, "betamount")?;
    let win = field(info, "winamount")?;
    let before = field(init, "player/balance")?;
    let after = field(check, "player/balance")?;
    ensure!(
        cost == offer.amount && cost > Decimal::ZERO,
        "native entry cost mismatch"
    );
    ensure!(
        wallet_matches(before, after, cost, win) && field(info, "balanceafterwin")? == after,
        "native wallet ledger mismatch"
    );
    ensure!(
        field(check, "gamesession/totbet")? == cost && field(check, "gamesession/totwon")? == win,
        "native session totals mismatch"
    );
    let session = node(check, "gamesession")?;
    if session.children().any(|n| n.has_tag_name("netposition")) {
        // Net position is a signed difference; native costs and awards still use money().
        let net_position = Decimal::from_str_exact(&value(session, "netposition")?)
            .context("invalid native net position")?;
        ensure!(
            net_position == exact_sub(win, cost)?,
            "native net position mismatch"
        );
    }
    let data = value(purchase, "game/pubdata")?;
    let pubdoc = xml(&data)?;
    let root = pubdoc.root_element();
    ensure!(
        root.tag_name().name() == "PURCHASES"
            && root.children().filter(|n| n.is_element()).count() == 1,
        "unreviewed native purchase sequence"
    );
    let native = node(root, "PURCHASE")?;
    ensure!(
        native.attribute("bmode") == Some("DEF")
            && native.attribute("betlevel") == Some(offer.level.as_str()),
        "native pubdata control mismatch"
    );
    ensure!(
        money(
            native
                .attribute("betamount")
                .context("native pubdata cost missing")?
        )? == cost
            && money(
                native
                    .attribute("winamount")
                    .context("native pubdata win missing")?
            )? == win,
        "independent native pubdata money mismatch"
    );
    ensure!(
        native.attribute("currency").unwrap_or("EUR") == "EUR",
        "native pubdata currency changed"
    );
    let steps = result_closure(init, native, win)?;
    Ok(RoundOutcome {
        native_round_id: Some(round),
        currency: "EUR".into(),
        monetary_unit: "native".into(),
        currency_source: "native_response".into(),
        balance_before: before.to_string(),
        balance_after: after.to_string(),
        cost: cost.to_string(),
        payout: win.to_string(),
        native_closed: true,
        checks: BTreeMap::from([
            ("fresh_demo_and_currency".into(), true),
            ("native_offer".into(), true),
            ("native_pubdata".into(), true),
            ("native_session_totals".into(), true),
        ]),
        native_data: json!({"initialization":initial,"purchase":purchased,"checkwin":checked,"native_results":steps,"game_id":GAME_ID}),
    })
}

/// Reconcile one already recorded ELK normal root without network or store writes.
pub fn reconcile_recorded(exchanges: &[ExchangeRecord]) -> Result<RoundOutcome> {
    let mut native = Vec::new();
    let mut last_ordinal = 0;
    for exchange in exchanges {
        ensure!(
            exchange.ordinal > last_ordinal,
            "recorded exchange order is ambiguous"
        );
        last_ordinal = exchange.ordinal;
        ensure!(
            exchange.error.is_none()
                && exchange.frames.is_empty()
                && exchange.request.transport == "http",
            "recorded exchange is incomplete or not HTTP"
        );
        let reply = exchange
            .response
            .as_ref()
            .context("recorded response missing")?;
        ensure!(
            sha256(&serde_json::to_vec(&exchange.request)?) == exchange.request_sha256
                && exchange.response_sha256.as_deref()
                    == Some(sha256(&serde_json::to_vec(reply)?).as_str()),
            "recorded exchange hash mismatch"
        );
        if matches!(
            exchange.request.label.as_str(),
            "init" | "purchase" | "checkwin"
        ) {
            ensure!(
                reply.status == 200,
                "recorded native HTTP status is not 200"
            );
            native.push(exchange);
        } else {
            ensure!(
                native.is_empty()
                    && exchange.request.method == "GET"
                    && !exchange.request.financial
                    && exchange.request.body.is_empty(),
                "unreviewed exchange in recorded native root"
            );
            let url = Url::parse(&exchange.request.url)?;
            ensure!(
                url.scheme() == "https"
                    && url.port().is_none()
                    && url.username().is_empty()
                    && url.password().is_none()
                    && url.fragment().is_none(),
                "unreviewed recorded bootstrap authority"
            );
            match exchange.request.label.as_str() {
                "launcher" => {
                    ensure!(
                        url.host_str() == Some("gamelauncher-stage.contentmedia.eu")
                            && url.path() == "/1.0/game/"
                            && matches!(reply.status, 301 | 302 | 303 | 307 | 308),
                        "recorded demo launcher mismatch"
                    );
                    launch_binding(
                        reply
                            .headers
                            .get("location")
                            .context("recorded launcher redirect missing")?,
                    )?;
                }
                "version" => ensure!(
                    url.host_str() == Some("static-stage.contentmedia.eu")
                        && matches!(
                            url.path(),
                            "/propaganda2/version.js"
                                | "/ecf3/version.js"
                                | "/ecf2/version.js"
                                | "/ecf/version.js"
                        )
                        && url.query().is_none()
                        && reply.status == 200,
                    "recorded native version source mismatch"
                ),
                _ => anyhow::bail!("unreviewed recorded exchange"),
            }
        }
    }
    ensure!(
        native.len() == 3,
        "one recorded init, purchase and checkwin are required"
    );
    let (init, purchase, check) = (native[0], native[1], native[2]);
    ensure!(
        purchase.ordinal.checked_sub(init.ordinal) == Some(1)
            && check.ordinal.checked_sub(purchase.ordinal) == Some(1),
        "recorded native sequence has a gap"
    );
    let mut last_request_id = 0;
    for (exchange, method) in [(init, "init"), (purchase, "purchase"), (check, "checkwin")] {
        let request = &exchange.request;
        ensure!(
            request.label == method
                && request.method == "POST"
                && request.financial == (method != "init")
                && request.url
                    == format!(
                        "{CAPI}/{GAME_ID}/play/{method}?gl=true&standalone=false&iframe=false"
                    ),
            "recorded native route or financial intent mismatch"
        );
        for (name, expected) in [
            ("origin", STATIC),
            ("content-type", "text/xml; charset=utf-8"),
            ("x-capi-version", "2.0"),
        ] {
            ensure!(
                recorded_header(request, name)? == expected,
                "recorded native header mismatch"
            );
        }
        for name in ["x-client-version", "x-ecf-version"] {
            let revision = recorded_header(request, name)?;
            ensure!(
                !revision.is_empty()
                    && revision.bytes().all(|b| b.is_ascii_digit())
                    && revision == recorded_header(&init.request, name)?,
                "recorded native client revision changed"
            );
        }
        let request_id: u64 = recorded_header(request, "x-capi-rid")?
            .strip_suffix(":1")
            .context("recorded native request id malformed")?
            .parse()
            .context("recorded native request id invalid")?;
        ensure!(
            request_id > last_request_id,
            "recorded native request ids are not increasing"
        );
        last_request_id = request_id;
    }

    let initial = &init.response.as_ref().unwrap().body;
    let purchased = &purchase.response.as_ref().unwrap().body;
    let checked = &check.response.as_ref().unwrap().body;
    let offer = initial_offer(initial)?;
    let init_response = response(initial, "init")?;
    let purchase_response = response(purchased, "purchase")?;
    let check_response = response(checked, "checkwin")?;
    let initial_session = value(init_response.root_element(), "gamesession/id")?;
    let purchase_session = value(purchase_response.root_element(), "gamesession/id")?;
    let native_round = value(purchase_response.root_element(), "roundid")?;

    let init_request = recorded_request(&init.request)?;
    let init_root = init_request.root_element();
    let external = init_root
        .attribute("extsession")
        .context("recorded external demo session missing")?;
    ensure!(
        external.parse::<u64>().ok().is_some_and(|id| id > 0),
        "recorded external demo session invalid"
    );
    recorded_attributes(
        init_root,
        &[
            ("opid", "44"),
            ("extsession", external),
            ("cur", "EUR"),
            ("desktopmode", "true"),
            ("lang", "en_gb"),
            ("screenres", "1920,1080,1718,966"),
            ("extjur", "NA"),
        ],
    )?;
    let purchase_request = recorded_request(&purchase.request)?;
    let purchase_root = purchase_request.root_element();
    let amount = purchase_root
        .attribute("amount")
        .context("recorded purchase amount missing")?;
    ensure!(
        money(amount)? == offer.amount,
        "recorded purchase is not the offered minimum"
    );
    recorded_attributes(
        purchase_root,
        &[
            ("gamesession", &initial_session),
            ("amount", amount),
            ("cur", "EUR"),
            ("bmode", "DEF"),
            ("betdetails", ""),
            ("betlevel", &offer.level),
            ("pmode", "click-s0"),
            ("orientation", "landscape"),
            ("sound", "bgeffect"),
            ("monetaryunit", "money"),
            ("gamespeed", "normal"),
        ],
    )?;
    let check_request = recorded_request(&check.request)?;
    recorded_attributes(
        check_request.root_element(),
        &[
            ("gamesession", &purchase_session),
            ("roundid", &native_round),
        ],
    )?;
    ensure!(
        value(check_response.root_element(), "gamesession/id")? == purchase_session,
        "recorded checkwin session changed"
    );
    let mut outcome = settlement(initial, purchased, checked, &offer)?;
    outcome.checks.extend(BTreeMap::from([
        ("recorded_exchange_integrity".into(), true),
        ("recorded_request_controls".into(), true),
        ("recorded_session_chain".into(), true),
    ]));
    ensure!(outcome.verify()?, "recorded native outcome did not verify");
    Ok(outcome)
}

fn recorded_header<'a>(request: &'a WireRequest, name: &str) -> Result<&'a str> {
    let mut matches = request
        .headers
        .iter()
        .filter(|(key, _)| key.eq_ignore_ascii_case(name));
    let (_, value) = matches.next().context("recorded native header missing")?;
    ensure!(matches.next().is_none(), "duplicate recorded native header");
    Ok(value)
}

fn recorded_request(request: &WireRequest) -> Result<Document<'_>> {
    let document = xml(&request.body)?;
    let root = document.root_element();
    ensure!(
        root.tag_name().name() == "request"
            && root.tag_name().namespace().is_none()
            && !root
                .children()
                .any(|n| n.is_element() || n.is_text() && !n.text().unwrap_or("").trim().is_empty())
            && root.attributes().all(|a| a.namespace().is_none()),
        "unreviewed recorded native request structure"
    );
    Ok(document)
}

fn recorded_attributes(root: Node<'_, '_>, expected: &[(&str, &str)]) -> Result<()> {
    ensure!(
        root.attributes().len() == expected.len()
            && expected
                .iter()
                .all(|(name, value)| root.attribute(*name) == Some(*value)),
        "recorded native request control or session mismatch"
    );
    Ok(())
}

fn launch_binding(location: &str) -> Result<(String, String)> {
    let parsed = Url::parse(location)?;
    ensure!(
        parsed.scheme() == "https"
            && parsed.host_str() == Some("static-stage.contentmedia.eu")
            && parsed.port().is_none()
            && parsed.username().is_empty()
            && parsed.password().is_none()
            && parsed.fragment().is_none(),
        "unverified public ELK launcher authority"
    );
    ensure!(
        matches!(
            parsed.path(),
            "/ecf3/index.html" | "/ecf2/index.html" | "/ecf/index.html"
        ),
        "unreviewed public framework path"
    );
    let mut query = BTreeMap::new();
    for (k, v) in parsed.query_pairs() {
        ensure!(
            query.insert(k.into_owned(), v.into_owned()).is_none(),
            "duplicate launcher parameter"
        );
    }
    for (key, expected) in [
        ("gameid", GAME_ID),
        ("operatorid", "44"),
        ("mode", "demo"),
        ("currency", "EUR"),
        ("capi", CAPI),
        ("gamename", "propaganda2"),
    ] {
        ensure!(
            query.get(key).map(String::as_str) == Some(expected),
            "official demo launcher contract mismatch"
        );
    }
    Ok((
        "propaganda2".into(),
        parsed.path().split('/').nth(1).unwrap().into(),
    ))
}

fn request_xml(attributes: &BTreeMap<String, String>) -> String {
    let mut text = String::from("<?xml version=\"1.0\"?><request");
    for (name, raw) in attributes {
        let escaped = raw
            .replace('&', "&amp;")
            .replace('<', "&lt;")
            .replace('>', "&gt;")
            .replace('"', "&quot;")
            .replace('\'', "&apos;");
        text.push_str(&format!(" {name}=\"{escaped}\""));
    }
    text.push_str(" />");
    text
}

struct Session<'a> {
    ctx: &'a RunContext,
    headers: BTreeMap<String, String>,
    key: String,
    last_rid: u64,
}
impl Session<'_> {
    async fn call(
        &mut self,
        method: &str,
        attributes: BTreeMap<String, String>,
        financial: bool,
    ) -> Result<String> {
        ensure!(
            matches!(method, "init" | "purchase" | "checkwin"),
            "unreviewed native method"
        );
        let rid = now_ms()
            .checked_mul(10)
            .context("native request id overflow")?
            .max(
                self.last_rid
                    .checked_add(1)
                    .context("native request id overflow")?,
            );
        self.last_rid = rid;
        let mut headers = self.headers.clone();
        headers.insert("x-capi-rid".into(), format!("{rid}:1"));
        let reply = self
            .ctx
            .http(
                method,
                "POST",
                &format!("{CAPI}/{GAME_ID}/play/{method}?gl=true&standalone=false&iframe=false"),
                headers,
                request_xml(&attributes),
                financial,
            )
            .await?;
        ensure!(reply.status == 200, "native ELK HTTP failure");
        let document = response(&reply.body, method)?;
        let root = document.root_element();
        if node(root, "gamesession")?
            .children()
            .any(|n| n.has_tag_name("id"))
        {
            self.key = value(root, "gamesession/id")?;
        }
        Ok(reply.body)
    }
}

pub async fn execute(
    ctx: &RunContext,
    game: &Game,
    mode: &Mode,
    settings: &Value,
) -> Result<RoundOutcome> {
    validate(game, mode, settings)?;
    let mut launcher = Url::parse("https://gamelauncher-stage.contentmedia.eu/1.0/game/")?;
    launcher.query_pairs_mut().extend_pairs([
        ("gameid", GAME_ID),
        ("operatorid", "44"),
        ("mode", "demo"),
        ("currency", "EUR"),
        ("device", "desktop"),
        ("language", "en_gb"),
        ("xdm", "0"),
    ]);
    let launched = ctx.get("launcher", launcher.as_str()).await?;
    ensure!(
        matches!(launched.status, 301 | 302 | 303 | 307 | 308),
        "public launcher did not return its reviewed redirect"
    );
    let (name, framework) = launch_binding(
        launched
            .headers
            .get("location")
            .context("official launcher location missing")?,
    )?;
    let game_source = ctx
        .get("version", &format!("{STATIC}/{name}/version.js"))
        .await?;
    let framework_source = ctx
        .get("version", &format!("{STATIC}/{framework}/version.js"))
        .await?;
    ensure!(
        game_source.status == 200 && framework_source.status == 200,
        "official version unavailable"
    );
    fn revision(source: &str, key: &str) -> Result<String> {
        let pattern = Regex::new(&format!(
            r#"\b{}\s*=\s*["']([0-9]+)["']"#,
            regex::escape(key)
        ))?;
        let mut matches = pattern.captures_iter(source);
        let first = matches.next().context("public build revision missing")?;
        ensure!(matches.next().is_none(), "ambiguous public revision");
        Ok(first[1].to_owned())
    }
    let client_revision = revision(&game_source.body, "game_revision")?;
    let ecf_revision = revision(&framework_source.body, "ecf_revision")?;
    let headers = BTreeMap::from([
        ("origin".into(), STATIC.into()),
        ("content-type".into(), "text/xml; charset=utf-8".into()),
        ("x-capi-version".into(), "2.0".into()),
        ("x-client-version".into(), client_revision.clone()),
        ("x-ecf-version".into(), ecf_revision.clone()),
    ]);
    let external = now_ms()
        .checked_add((Uuid::new_v4().as_u128() % 10000) as u64)
        .context("native external session overflow")?
        .to_string();
    let mut session = Session {
        ctx,
        headers,
        key: String::new(),
        last_rid: 0,
    };
    let initial = session
        .call(
            "init",
            BTreeMap::from([
                ("opid".into(), "44".into()),
                ("extsession".into(), external.clone()),
                ("cur".into(), "EUR".into()),
                ("desktopmode".into(), "true".into()),
                ("lang".into(), "en_gb".into()),
                ("screenres".into(), "1920,1080,1718,966".into()),
                ("extjur".into(), "NA".into()),
            ]),
            false,
        )
        .await?;
    let offer = initial_offer(&initial)?;
    ctx.save_session(&json!({"provider":"elk","game":game.id,"game_id":GAME_ID,"initial_gamesession":session.key,"external_session":external,"client_revision":client_revision,"ecf_revision":ecf_revision,"currency":"EUR","mode":"demo","operator_id":"44"}))?;
    let purchased = session
        .call(
            "purchase",
            BTreeMap::from([
                ("gamesession".into(), session.key.clone()),
                ("amount".into(), offer.amount.to_string()),
                ("cur".into(), "EUR".into()),
                ("bmode".into(), "DEF".into()),
                ("betdetails".into(), String::new()),
                ("betlevel".into(), offer.level.clone()),
                ("pmode".into(), "click-s0".into()),
                ("orientation".into(), "landscape".into()),
                ("sound".into(), "bgeffect".into()),
                ("monetaryunit".into(), "money".into()),
                ("gamespeed".into(), "normal".into()),
            ]),
            true,
        )
        .await?;
    let round = value(response(&purchased, "purchase")?.root_element(), "roundid")?;
    ensure!(round != "0", "native accepted round identifier missing");
    let checked = session
        .call(
            "checkwin",
            BTreeMap::from([
                ("gamesession".into(), session.key.clone()),
                ("roundid".into(), round),
            ]),
            true,
        )
        .await?;
    settlement(&initial, &purchased, &checked, &offer)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{WireRequest, WireResponse, decimal, sha256};

    const INIT: &str = r#"<response><method>init</method><errorcode>0</errorcode><gamesession><id>fixture-session</id><totbet>0.00</totbet><totwon>0.00</totwon></gamesession><roundid>0</roundid><player><currency>EUR</currency><balance>5000.00</balance></player><betlevels bmode="true"><betlevel id="2"><bmodes><bmode id="DEF" amount="0.40"/></bmodes></betlevel><betlevel id="1"><bmodes><bmode id="DEF" amount="0.20"/><bmode id="X01" amount="0.50"/></bmodes></betlevel></betlevels><game><paytable>&lt;SETUP gameid="10276" protocol-version="2"&gt;&lt;MODE name="BASE"/&gt;&lt;MODE name="BONUS"/&gt;&lt;/SETUP&gt;</paytable></game></response>"#;
    const PURCHASE: &str = r#"<response><method>purchase</method><errorcode>0</errorcode><gamesession><id>fixture-session</id><totbet>0.20</totbet><totwon>0.75</totwon></gamesession><roundid>123456</roundid><player><currency>EUR</currency><balance>5000.55</balance></player><roundinfo><roundid>123456</roundid><betlevel>1</betlevel><betamount>0.20</betamount><winamount>0.75</winamount><bmode>DEF</bmode><currency>EUR</currency><balanceafterwin>5000.55</balanceafterwin></roundinfo><game><pubdata>&lt;PURCHASES&gt;&lt;PURCHASE betlevel="1" bmode="DEF" betamount="0.20000" winamount="0.75000"&gt;&lt;RESULT resultIndex="0" mode="BASE" winamount="0.25" amounttotal="0.25"/&gt;&lt;RESULT resultIndex="1" mode="BONUS" winamount="0.50" amounttotal="0.75" fsleft="0"/&gt;&lt;/PURCHASE&gt;&lt;/PURCHASES&gt;</pubdata></game></response>"#;
    const CHECK: &str = r#"<response><method>checkwin</method><errorcode>0</errorcode><gamesession><totbet>0.20</totbet><totwon>0.75</totwon><netposition>0.55</netposition></gamesession><roundid>123456</roundid><player><currency>EUR</currency><balance>5000.55</balance></player></response>"#;
    const LOSS_PURCHASE: &str = r#"<response><method>purchase</method><errorcode>0</errorcode><gamesession><id>fixture-session</id><totbet>0.20</totbet><totwon>0.00</totwon><netposition>-0.20</netposition></gamesession><roundid>123456</roundid><player><currency>EUR</currency><balance>4999.80</balance></player><roundinfo><roundid>123456</roundid><betlevel>1</betlevel><betamount>0.20</betamount><winamount>0.00</winamount><bmode>DEF</bmode><currency>EUR</currency><balanceafterwin>4999.80</balanceafterwin></roundinfo><game><pubdata>&lt;PURCHASES&gt;&lt;PURCHASE betlevel="1" bmode="DEF" betamount="0.20000" winamount="0.00000"&gt;&lt;RESULT resultIndex="0" mode="BASE" winamount="0.00" amounttotal="0.00"/&gt;&lt;/PURCHASE&gt;&lt;/PURCHASES&gt;</pubdata></game></response>"#;
    const LOSS_CHECK: &str = r#"<response><method>checkwin</method><errorcode>0</errorcode><gamesession><id>fixture-session</id><totbet>0.20</totbet><totwon>0.00</totwon><netposition>-0.20</netposition></gamesession><roundid>123456</roundid><player><currency>EUR</currency><balance>4999.80</balance></player></response>"#;

    #[test]
    fn losing_round_accepts_negative_net_position_without_negative_money() {
        let offer = initial_offer(INIT).unwrap();
        let mut result = settlement(INIT, LOSS_PURCHASE, LOSS_CHECK, &offer).unwrap();
        assert_eq!(result.balance_before, "5000.00");
        assert_eq!(result.balance_after, "4999.80");
        assert_eq!(result.cost, "0.20");
        assert_eq!(result.payout, "0.00");
        assert!(result.verify().unwrap());
        assert!(
            settlement(
                INIT,
                LOSS_PURCHASE,
                &LOSS_CHECK.replace("-0.20", "0.20"),
                &offer
            )
            .is_err()
        );
        assert!(
            settlement(
                INIT,
                &LOSS_PURCHASE.replace("<betamount>0.20", "<betamount>-0.20"),
                LOSS_CHECK,
                &offer
            )
            .is_err()
        );
        assert!(
            settlement(
                INIT,
                &LOSS_PURCHASE.replace("<winamount>0.00", "<winamount>-0.01"),
                LOSS_CHECK,
                &offer
            )
            .is_err()
        );
    }

    fn rehash(exchange: &mut ExchangeRecord) {
        exchange.request_sha256 = sha256(&serde_json::to_vec(&exchange.request).unwrap());
        exchange.response_sha256 = exchange
            .response
            .as_ref()
            .map(|response| sha256(&serde_json::to_vec(response).unwrap()));
    }

    fn recorded_loss() -> Vec<ExchangeRecord> {
        let requests = [
            (
                "init",
                r#"<request opid="44" extsession="123400" cur="EUR" desktopmode="true" lang="en_gb" screenres="1920,1080,1718,966" extjur="NA" />"#,
                INIT,
            ),
            (
                "purchase",
                r#"<request gamesession="fixture-session" amount="0.20" cur="EUR" bmode="DEF" betdetails="" betlevel="1" pmode="click-s0" orientation="landscape" sound="bgeffect" monetaryunit="money" gamespeed="normal" />"#,
                LOSS_PURCHASE,
            ),
            (
                "checkwin",
                r#"<request gamesession="fixture-session" roundid="123456" />"#,
                LOSS_CHECK,
            ),
        ];
        requests
            .into_iter()
            .enumerate()
            .map(|(i, (method, request, response))| {
                let mut exchange = ExchangeRecord {
                    ordinal: i as u64 + 1,
                    request: WireRequest {
                        label: method.into(),
                        transport: "http".into(),
                        method: "POST".into(),
                        url: format!(
                            "{CAPI}/{GAME_ID}/play/{method}?gl=true&standalone=false&iframe=false"
                        ),
                        headers: BTreeMap::from([
                            ("content-type".into(), "text/xml; charset=utf-8".into()),
                            ("origin".into(), STATIC.into()),
                            ("x-capi-version".into(), "2.0".into()),
                            ("x-client-version".into(), "123".into()),
                            ("x-ecf-version".into(), "456".into()),
                            ("x-capi-rid".into(), format!("{}:1", 100 + i)),
                        ]),
                        body: request.into(),
                        financial: method != "init",
                    },
                    response: Some(WireResponse {
                        status: 200,
                        headers: BTreeMap::new(),
                        body: response.into(),
                        set_cookies: Vec::new(),
                    }),
                    error: None,
                    request_sha256: String::new(),
                    response_sha256: None,
                    frames: Vec::new(),
                };
                rehash(&mut exchange);
                exchange
            })
            .collect()
    }

    #[test]
    fn recorded_loss_reconciles_from_retained_http_only() {
        let mut result = reconcile_recorded(&recorded_loss()).unwrap();
        assert_eq!(result.native_round_id.as_deref(), Some("123456"));
        assert_eq!(result.balance_before, "5000.00");
        assert_eq!(result.balance_after, "4999.80");
        assert_eq!(result.cost, "0.20");
        assert_eq!(result.payout, "0.00");
        assert!(result.verify().unwrap());
    }

    #[test]
    fn recorded_reconciliation_rejects_tampered_or_incomplete_exchanges() {
        let original = recorded_loss();
        let mut changed = original.clone();
        changed[1].request.body.push(' ');
        assert!(reconcile_recorded(&changed).is_err());
        let mut changed = original.clone();
        changed[2].response.as_mut().unwrap().body.push(' ');
        assert!(reconcile_recorded(&changed).is_err());
        let mut changed = original.clone();
        changed[2].response_sha256 = None;
        assert!(reconcile_recorded(&changed).is_err());
        let mut changed = original.clone();
        changed[1].response.as_mut().unwrap().status = 403;
        rehash(&mut changed[1]);
        assert!(reconcile_recorded(&changed).is_err());
        let mut changed = original.clone();
        changed[1].error = Some("fixture transport failure".into());
        assert!(reconcile_recorded(&changed).is_err());
        let mut changed = original;
        changed[2].response = None;
        rehash(&mut changed[2]);
        assert!(reconcile_recorded(&changed).is_err());
    }

    #[test]
    fn recorded_reconciliation_rejects_cross_session_or_changed_request_controls() {
        let original = recorded_loss();
        for (index, from, to) in [
            (0, "opid=\"44\"", "opid=\"45\""),
            (1, "fixture-session", "unrelated-session"),
            (1, "amount=\"0.20\"", "amount=\"0.40\""),
            (1, "bmode=\"DEF\"", "bmode=\"X01\""),
            (1, "betdetails=\"\"", "betdetails=\"extra\""),
            (2, "fixture-session", "unrelated-session"),
            (2, "roundid=\"123456\"", "roundid=\"654321\""),
        ] {
            let mut changed = original.clone();
            changed[index].request.body = changed[index].request.body.replace(from, to);
            rehash(&mut changed[index]);
            assert!(
                reconcile_recorded(&changed).is_err(),
                "changed request accepted at {index}"
            );
        }
        let mut changed = original.clone();
        changed[1].request.url = changed[1].request.url.replace("10276", "10271");
        rehash(&mut changed[1]);
        assert!(reconcile_recorded(&changed).is_err());
        let mut changed = original.clone();
        changed[1].request.financial = false;
        rehash(&mut changed[1]);
        assert!(reconcile_recorded(&changed).is_err());
        let mut changed = original;
        changed[1]
            .request
            .headers
            .insert("x-client-version".into(), "789".into());
        rehash(&mut changed[1]);
        assert!(reconcile_recorded(&changed).is_err());
    }

    #[test]
    fn recorded_reconciliation_rejects_missing_duplicate_or_reordered_roots() {
        let original = recorded_loss();
        assert!(reconcile_recorded(&original[..2]).is_err());
        let mut changed = original.clone();
        let mut duplicate = changed[1].clone();
        duplicate.ordinal = 4;
        changed.push(duplicate);
        assert!(reconcile_recorded(&changed).is_err());
        let mut changed = original.clone();
        changed.swap(0, 1);
        assert!(reconcile_recorded(&changed).is_err());
        let mut changed = original;
        let mut unknown = changed[1].clone();
        unknown.ordinal = 4;
        unknown.request.label = "unreviewed-financial-step".into();
        rehash(&mut unknown);
        changed.push(unknown);
        assert!(reconcile_recorded(&changed).is_err());
    }

    #[test]
    fn published_propaganda_initialization_matches_reviewed_normal_minimum() {
        let rows: Value = serde_json::from_str(include_str!(
            "../../../demo-dashboard/elk/batches/1-100/inventory.json"
        ))
        .unwrap();
        let game = rows
            .as_array()
            .unwrap()
            .iter()
            .find(|g| g["slug"] == "propaganda-2")
            .unwrap();
        assert_eq!(
            initial_offer(game["init"].as_str().unwrap()).unwrap(),
            Offer {
                level: "1".into(),
                amount: decimal("0.20").unwrap()
            }
        );
    }

    #[test]
    fn official_launcher_rejects_changed_game_demo_or_authority() {
        let launch = "https://static-stage.contentmedia.eu/ecf3/index.html?gameid=10276&operatorid=44&mode=demo&currency=EUR&capi=https%3A%2F%2Fgc5-stage.contentmedia.eu%2Fcapi&gamename=propaganda2";
        assert_eq!(
            launch_binding(launch).unwrap(),
            ("propaganda2".into(), "ecf3".into())
        );
        assert!(launch_binding(&launch.replace("mode=demo", "mode=real")).is_err());
        assert!(launch_binding(&launch.replace("10276", "10271")).is_err());
        assert!(
            launch_binding(&launch.replace("static-stage.contentmedia.eu", "other.example"))
                .is_err()
        );
        assert!(launch_binding(&(launch.to_string() + "&gameid=10276")).is_err());
    }

    #[test]
    fn native_minimum_rejects_existing_round_and_wrong_paytable_identity() {
        assert_eq!(
            initial_offer(INIT).unwrap(),
            Offer {
                level: "1".into(),
                amount: decimal("0.20").unwrap()
            }
        );
        assert!(
            initial_offer(&INIT.replace("<roundid>0</roundid>", "<roundid>123</roundid>")).is_err()
        );
        assert!(initial_offer(&INIT.replace("gameid=\"10276\"", "gameid=\"10271\"")).is_err());
        assert!(
            initial_offer(&INIT.replace("<totbet>0.00</totbet>", "<totbet>0.20</totbet>")).is_err()
        );
        assert!(
            initial_offer(&INIT.replace("<currency>EUR</currency>", "<currency>USD</currency>"))
                .is_err()
        );
    }

    #[test]
    fn native_payout_round_and_checkwin_wallet_must_all_agree() {
        let offer = Offer {
            level: "1".into(),
            amount: decimal("0.20").unwrap(),
        };
        let mut result = settlement(INIT, PURCHASE, CHECK, &offer).unwrap();
        assert_eq!(result.payout, "0.75");
        assert_eq!(result.cost, "0.20");
        assert_eq!(result.native_round_id.as_deref(), Some("123456"));
        assert!(result.verify().unwrap());
        assert!(settlement(INIT, PURCHASE, &CHECK.replace("123456", "123457"), &offer).is_err());
        assert!(
            settlement(
                INIT,
                &PURCHASE.replace("winamount=\"0.75000\"", "winamount=\"0.80000\""),
                CHECK,
                &offer
            )
            .is_err()
        );
        assert!(settlement(INIT, PURCHASE, &CHECK.replace("5000.55", "5000.56"), &offer).is_err());
    }

    #[test]
    fn unfinished_bonus_or_duplicate_xml_fields_cannot_verify() {
        let offer = Offer {
            level: "1".into(),
            amount: decimal("0.20").unwrap(),
        };
        assert!(
            settlement(
                INIT,
                &PURCHASE.replace("fsleft=\"0\"", "fsleft=\"1\""),
                CHECK,
                &offer
            )
            .is_err()
        );
        assert!(
            settlement(
                INIT,
                &PURCHASE.replace("resultIndex=\"1\"", "resultIndex=\"2\""),
                CHECK,
                &offer
            )
            .is_err()
        );
        assert!(
            settlement(
                INIT,
                &PURCHASE.replace("mode=\"BONUS\"", "mode=\"UNKNOWN\""),
                CHECK,
                &offer
            )
            .is_err()
        );
        assert!(
            initial_offer(&INIT.replace(
                "<roundid>0</roundid>",
                "<roundid>0</roundid><roundid>123</roundid>"
            ))
            .is_err()
        );
        assert!(initial_offer(&format!("<!DOCTYPE response>{INIT}")).is_err());
    }
}
