use crate::context::RunContext;
use anyhow::{Context, Result, ensure};
use serde_json::{Value, json};
use std::time::Duration;
use std::{collections::BTreeMap, sync::Arc};
use url::Url;

const ORIGIN: &str = "https://games.evolution.com";
const SHOWCASE: &str = "https://showcase.evo-games.com";
const CLIENT_VERSION: &str = "6.20261030.73038.67000-7e7b03116d-r2";

fn demo_wallet(value: &str) -> bool {
    value.strip_prefix("demo-").is_some_and(|id| {
        !id.is_empty()
            && id.len() <= 256
            && id
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'='))
    })
}

fn demo_fragment(url: &Url) -> Option<(String, String)> {
    let mut wallet = None;
    let mut table = None;
    for (key, value) in url::form_urlencoded::parse(url.fragment()?.as_bytes()) {
        match key.as_ref() {
            "balance_id" if wallet.is_none() && demo_wallet(&value) => {
                wallet = Some(value.into_owned());
            }
            "table_id"
                if table.is_none()
                    && !value.is_empty()
                    && value.len() <= 64
                    && value.bytes().all(|b| b.is_ascii_alphanumeric()) =>
            {
                table = Some(value.into_owned());
            }
            "balance_id" | "table_id" => return None,
            _ => {}
        }
    }
    wallet.zip(table)
}

fn geco_init_url(config: &Value, table: &str, wallet: &str) -> Result<Url> {
    ensure!(
        demo_wallet(wallet)
            && config["table_id"] == table
            && config["game_provider"] == "netent"
            && config["game_engine"] == "geco"
            && config["userType"] == 0
            && config["currencyDecimals"] == 2,
        "NetEnt config did not confirm the launched GECO demo table"
    );
    let launch = &config["wrappedLaunchParams"];
    let required = |name: &str| -> Result<&str> {
        launch[name]
            .as_str()
            .filter(|v| !v.is_empty() && v.len() <= 4096 && !v.chars().any(char::is_control))
            .with_context(|| format!("GECO launch parameter {name} missing or malformed"))
    };
    let session = required("sessionId")?;
    let game = required("gameId")?;
    let currency = required("ne_currency")?;
    ensure!(
        session.len() <= 128
            && session.bytes().all(|b| b.is_ascii_alphanumeric())
            && config["bare_session_id"] == session
            && game
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_'))
            && currency.len() == 3
            && currency.bytes().all(|b| b.is_ascii_uppercase())
            && config["currencyCode"] == currency
            && launch["ne_device"] == "desktop"
            && launch["gameServer"] == format!("{SHOWCASE}/public/rng/dragon"),
        "GECO launch parameters disagree with the active demo"
    );
    let mut url = Url::parse(&format!(
        "{SHOWCASE}/public/rng/dragon/servlet/CasinoGameServlet;jsession={session}"
    ))?;
    {
        let mut query = url.query_pairs_mut();
        query
            .append_pair("action", "init")
            .append_pair("gameId", game)
            .append_pair("sessid", session)
            .append_pair("ne_balance_id", wallet)
            .append_pair("ne_mode", "demo")
            .append_pair("wantsfreerounds", "true")
            .append_pair("freeroundmode", "false")
            .append_pair("wantsreels", "true")
            .append_pair("no-cache", &crate::model::now_ms().to_string());
        for key in [
            "ne_currency",
            "ne_casinoId",
            "ne_device",
            "ne_evo_token",
            "ne_evo_token1",
            "ne_evo_token2",
        ] {
            query.append_pair(key, required(key)?);
        }
    }
    Ok(url)
}

fn validate_entry_target(url: &Url, origin: &str, hop: usize) -> Result<()> {
    ensure!(
        url.origin().ascii_serialization() == origin
            && url.username().is_empty()
            && url.password().is_none()
            && ((url.path() == "/entry" && url.fragment().is_none())
                || (hop > 0 && url.path().starts_with("/frontend/evo/"))),
        "unexpected NetEnt demo redirect"
    );
    Ok(())
}

async fn probe_geco(
    client: &reqwest::Client,
    frontend: &Url,
    wallet: &str,
    table: &str,
) -> Result<Value> {
    let mut referer = frontend.clone();
    referer.set_fragment(None);
    let mut config_url = Url::parse(&format!("{SHOWCASE}/config"))?;
    config_url
        .query_pairs_mut()
        .append_pair("table_id", table)
        .append_pair("client_version", "6.20261030.73038.67000-7e7b03116d-r2");
    let reply = client
        .get(config_url)
        .header("referer", referer.as_str())
        .send()
        .await
        .map_err(|_| anyhow::anyhow!("NetEnt config request failed"))?;
    let config_http = reply.status().as_u16();
    if config_http != 200 {
        return Ok(json!({"config_http":config_http,"ready":false}));
    }
    let config: Value = reply
        .json()
        .await
        .context("NetEnt config is not valid JSON")?;
    let url = geco_init_url(&config, table, wallet)?;
    // The published legacy SDK omits cookies for this cross-origin call.
    let legacy = reqwest::Client::builder()
        .timeout(Duration::from_secs(20))
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .retry(reqwest::retry::never())
        .build()?;
    let reply = legacy
        .get(url)
        .header("referer", referer.as_str())
        .send()
        .await
        .map_err(|_| anyhow::anyhow!("NetEnt GECO initialization request failed"))?;
    let init_http = reply.status().as_u16();
    let ready = if init_http == 200 {
        let fields = super::netent_geco::fields(&reply.text().await?)?;
        super::netent_geco::quote(&fields).is_ok()
    } else {
        false
    };
    Ok(json!({"config_http":config_http,"init_http":init_http,"ready":ready}))
}

async fn probe_entry(
    client: &reqwest::Client,
    mut url: Url,
    origin: &str,
    referer: &str,
) -> Result<(Vec<Value>, Option<Url>)> {
    let mut hops = Vec::new();
    for hop in 0..4 {
        validate_entry_target(&url, origin, hop)?;
        let mut request_url = url.clone();
        request_url.set_fragment(None);
        let reply = client
            .get(request_url)
            .header("referer", referer)
            .send()
            .await
            .map_err(|_| anyhow::anyhow!("NetEnt entry request failed"))?;
        let status = reply.status().as_u16();
        hops.push(json!({"path":url.path(),"status":status}));
        if !matches!(status, 301 | 302 | 303 | 307 | 308) {
            let reached = status == 200 && url.path().starts_with("/frontend/evo/");
            return Ok((hops, reached.then_some(url)));
        }
        let next = reply
            .headers()
            .get("location")
            .context("NetEnt redirect missing")?
            .to_str()?;
        url = url
            .join(next)
            .map_err(|_| anyhow::anyhow!("invalid NetEnt demo redirect"))?;
    }
    Ok((hops, None))
}

pub async fn probe_playin(game: &str) -> Result<bool> {
    ensure!(game == "starburst", "Playin probe is bound to Starburst");
    const SITE: &str = "https://playin.com";
    const ENTRY: &str = "https://fansite.evo-games.com";
    // This identifier is published in the public Playin demo client.
    const CLIENT: &str = "ATp3ZRaTE2u22oTM6GXmHtkgWYc6F8vZ";
    const TABLE: &str = "starburstr000000";
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(20))
        .no_proxy()
        .cookie_provider(Arc::new(reqwest::cookie::Jar::default()))
        .redirect(reqwest::redirect::Policy::none())
        .retry(reqwest::retry::never())
        .build()?;
    let page = format!("{SITE}/embed/v1/demo/{TABLE}");
    let page_http = client.get(&page).send().await?.status().as_u16();
    if page_http != 200 {
        println!(
            "{}",
            json!({"game":game,"route":"playin","page_http":page_http,"financial_requests":0})
        );
        return Ok(false);
    }
    let issue = client
        .post("https://jinx.prod.cmsevo.com/api/v1/oss/token/demo")
        .header("origin", SITE)
        .header("referer", format!("{SITE}/"))
        .header("x-api-key", CLIENT)
        .json(&json!({"demo":{"language":"en-GB","currency":"VC0"},"game":{"tableId":TABLE}}))
        .send()
        .await?;
    let issuer_http = issue.status().as_u16();
    if issuer_http != 200 {
        println!(
            "{}",
            json!({"game":game,"route":"playin","page_http":page_http,
            "issuer_http":issuer_http,"financial_requests":0})
        );
        return Ok(false);
    }
    let message: Value = issue.json().await?;
    let entry = message["entry"]
        .as_str()
        .context("Playin demo entry missing")?;
    let url = Url::parse(ENTRY)?
        .join(entry)
        .map_err(|_| anyhow::anyhow!("invalid Playin demo entry"))?;
    let (hops, frontend) = probe_entry(&client, url, ENTRY, &page).await?;
    println!(
        "{}",
        json!({"game":game,"route":"playin","page_http":page_http,"issuer_http":issuer_http,
        "entry_hops":hops,"frontend_reached":frontend.is_some(),"demo_wallet_fragment":
        frontend.as_ref().and_then(demo_fragment).is_some(),"financial_requests":0})
    );
    Ok(frontend.is_some())
}

#[derive(serde::Deserialize)]
struct Launch {
    family: String,
    public_game_id: String,
}

fn nonce(html: &str) -> Result<String> {
    let script = regex::Regex::new(r"var\s+game_api_settings\s*=\s*(\{[^;]+\});")?;
    let mut scripts = script.captures_iter(html);
    let entry = scripts
        .next()
        .context("NetEnt public launch settings missing")?;
    ensure!(scripts.next().is_none(), "NetEnt launch settings ambiguous");
    let settings: Value = serde_json::from_str(&entry[1])?;
    let nonce = settings["nonce"]
        .as_str()
        .filter(|v| (8..=64).contains(&v.len()) && v.bytes().all(|b| b.is_ascii_alphanumeric()))
        .context("NetEnt launch nonce missing or malformed")?;
    Ok(nonce.to_owned())
}

pub(crate) struct DemoLaunch {
    pub config: Value,
    pub wallet: String,
    pub frontend: Url,
    pub frontend_body: String,
}

pub(crate) async fn open_config(
    ctx: &RunContext,
    game: &str,
    table: &str,
    family: &str,
    client_version: &str,
) -> Result<DemoLaunch> {
    let launches: BTreeMap<String, Launch> =
        serde_json::from_slice(include_bytes!("../../bindings/netent-launch.json"))?;
    let row = launches
        .get(game)
        .context("missing reviewed NetEnt launcher")?;
    ensure!(
        row.family == family
            && !row.public_game_id.is_empty()
            && row.public_game_id.bytes().all(|b| b.is_ascii_digit())
            && game
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-'),
        "invalid NetEnt launch binding"
    );
    let page = format!("{ORIGIN}/slots/{game}/");
    let reply = ctx.get("netent_game_page", &page).await?;
    ensure!(
        reply.status == 200,
        "HTTP {} at NetEnt game page",
        reply.status
    );
    let mut issuer = Url::parse(&format!("{ORIGIN}/wp-json/games/v1/start"))?;
    issuer
        .query_pairs_mut()
        .append_pair("id", &row.public_game_id)
        .append_pair("mobile", "false");
    ctx.seed_cookie(&page, "age_confirmed=1; Path=/; Secure")?;
    let headers = BTreeMap::from([
        ("accept".into(), "*/*".into()),
        ("referer".into(), page.clone()),
        ("x-requested-with".into(), "XMLHttpRequest".into()),
        ("x-wp-nonce".into(), nonce(&reply.body)?),
    ]);
    let reply = ctx
        .http(
            "netent_demo_issuer",
            "GET",
            issuer.as_str(),
            headers,
            String::new(),
            false,
        )
        .await?;
    ensure!(
        reply.status == 200,
        "HTTP {} at NetEnt demo issuer",
        reply.status
    );
    let launch: Value =
        serde_json::from_str(&reply.body).context("invalid NetEnt issuer response")?;
    ensure!(
        launch["success"] == true,
        "NetEnt demo issuer declined the launch"
    );
    let mut entry = launch["payload"]
        .as_str()
        .and_then(|s| Url::parse(s).ok())
        .context("invalid NetEnt issuer entry")?;
    for hop in 0..4 {
        validate_entry_target(&entry, SHOWCASE, hop)?;
        let mut frontend = entry.clone();
        frontend.set_fragment(None);
        let reply = ctx
            .http(
                "netent_demo_entry",
                "GET",
                frontend.as_str(),
                BTreeMap::from([("referer".into(), page.clone())]),
                String::new(),
                false,
            )
            .await?;
        if matches!(reply.status, 301 | 302 | 303 | 307 | 308) {
            let location = reply
                .headers
                .get("location")
                .context("NetEnt entry redirect missing")?;
            entry = entry
                .join(location)
                .map_err(|_| anyhow::anyhow!("invalid NetEnt entry redirect"))?;
            continue;
        }
        ensure!(
            reply.status == 200 && frontend.path().starts_with("/frontend/evo/"),
            "HTTP {} at NetEnt demo entry without a supported frontend",
            reply.status
        );
        let frontend_body = reply.body;
        let (wallet, launched_table) =
            demo_fragment(&entry).context("NetEnt demo wallet missing from frontend")?;
        ensure!(
            launched_table == table,
            "NetEnt issuer returned a different demo table"
        );
        let mut config_url = Url::parse(&format!("{SHOWCASE}/config"))?;
        config_url
            .query_pairs_mut()
            .append_pair("table_id", table)
            .append_pair("client_version", client_version);
        let reply = ctx
            .http(
                "netent_demo_config",
                "GET",
                config_url.as_str(),
                BTreeMap::from([("referer".into(), frontend.to_string())]),
                String::new(),
                false,
            )
            .await?;
        ensure!(
            reply.status == 200,
            "HTTP {} at NetEnt demo config",
            reply.status
        );
        let config: Value =
            serde_json::from_str(&reply.body).context("invalid NetEnt demo config")?;
        return Ok(DemoLaunch {
            config,
            wallet,
            frontend,
            frontend_body,
        });
    }
    anyhow::bail!("NetEnt demo entry redirect limit reached")
}

pub(crate) async fn open_geco(
    ctx: &RunContext,
    game: &str,
    table: &str,
    native_game: &str,
    asset: Option<(&str, &str)>,
) -> Result<(Url, String)> {
    let DemoLaunch {
        config,
        wallet,
        frontend,
        ..
    } = open_config(ctx, game, table, "geco_http", CLIENT_VERSION).await?;
    ensure!(
        config["wrappedLaunchParams"]["gameId"] == native_game,
        "NetEnt native game identity changed"
    );
    let init = geco_init_url(&config, table, &wallet)?;
    if let Some((path, digest)) = asset {
        const STATIC: &str = "https://affiliate0000001-static2.casinomodule.com/";
        ensure!(
            config["wrappedLaunchParams"]["staticServer"] == STATIC && path.starts_with("/games/"),
            "NetEnt GECO asset origin changed"
        );
        let source = Url::parse(STATIC)?.join(path)?;
        let reply = ctx
            .get("netent_geco_reviewed_source", source.as_str())
            .await?;
        ensure!(
            reply.status == 200 && crate::model::sha256(reply.body.as_bytes()) == digest,
            "NetEnt GECO reviewed client source changed or is unavailable"
        );
    }
    Ok((init, frontend.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn official_frontend_carries_demo_wallet_in_the_local_fragment() {
        let href = Url::parse("https://showcase.evo-games.com/frontend/evo/r2/#balance_id=demo-fixture&table_id=fixture000000000").unwrap();
        assert!(demo_fragment(&href).is_some());
        assert!(demo_fragment(&Url::parse("https://showcase.evo-games.com/frontend/evo/r2/#balance_id=demo-a&balance_id=demo-b&table_id=fixture").unwrap()).is_none());
        assert!(demo_fragment(&Url::parse("https://showcase.evo-games.com/frontend/evo/r2/#balance_id=demo-test%3D%3D-demo&table_id=fixture").unwrap()).is_some());
    }

    #[test]
    fn reads_only_the_nonce_from_unambiguous_launch_settings() {
        let script = r#"<script>var game_api_settings = {"nonce":"a012bc3456","mobile_game_loader":"https:\/\/games.evolution.com\/mobile-game\/"};</script>"#;
        assert_eq!(nonce(script).unwrap(), "a012bc3456");
        assert!(nonce(&format!("{script}{script}")).is_err());
        assert!(nonce(r#"var other_settings = {"nonce":"a012bc3456"};"#).is_err());
        assert!(nonce(r#"var game_api_settings = {"nonce":"not a nonce"};"#).is_err());
    }

    #[test]
    fn geco_config_is_bound_to_the_current_demo_table() {
        let config = json!({
            "table_id":"table123","game_provider":"netent","game_engine":"geco",
            "userType":0,"currencyCode":"USD","currencyDecimals":2,
            "bare_session_id":"session123",
            "wrappedLaunchParams":{
                "gameServer":"https://showcase.evo-games.com/public/rng/dragon",
                "gameId":"fixture_not_mobile_sw","sessionId":"session123",
                "ne_currency":"USD","ne_device":"desktop","ne_casinoId":"affiliate0000001",
                "ne_evo_token":"fixture-token","ne_evo_token1":"fixture-token1","ne_evo_token2":"fixture-token2"
            }
        });
        let begin = geco_init_url(&config, "table123", "demo-fixture").unwrap();
        assert_eq!(
            begin.path(),
            "/public/rng/dragon/servlet/CasinoGameServlet;jsession=session123"
        );
        let params: BTreeMap<_, _> = begin.query_pairs().into_owned().collect();
        assert_eq!(params["action"], "init");
        assert_eq!(params["ne_mode"], "demo");
        assert_eq!(params["ne_balance_id"], "demo-fixture");
        assert!(geco_init_url(&config, "anotherTable", "demo-fixture").is_err());
        assert!(geco_init_url(&config, "table123", "non-demo-fixture").is_err());
        let mut conflict = config;
        conflict["wrappedLaunchParams"]["sessionId"] = json!("different");
        assert!(geco_init_url(&conflict, "table123", "demo-fixture").is_err());
    }
}

pub async fn probe(game: &str) -> Result<bool> {
    let launches: BTreeMap<String, Launch> =
        serde_json::from_slice(include_bytes!("../../bindings/netent-launch.json"))?;
    let row = launches
        .get(game)
        .context("no reviewed NetEnt launch for game")?;
    ensure!(
        game.bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
            && row.public_game_id.bytes().all(|b| b.is_ascii_digit()),
        "invalid NetEnt game binding"
    );
    let cookies = Arc::new(reqwest::cookie::Jar::default());
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(20))
        .redirect(reqwest::redirect::Policy::none())
        .retry(reqwest::retry::never())
        .no_proxy()
        .cookie_provider(cookies.clone())
        .user_agent("Evidencia-Demo-Runner/0.1")
        .build()?;
    let page = format!("{ORIGIN}/slots/{game}/");
    let reply = client
        .get(&page)
        .send()
        .await
        .context("NetEnt game page request failed")?;
    let status = reply.status().as_u16();
    if status != 200 {
        println!(
            "{}",
            json!({"game":game,"page_http":status,"launch_requested":false,"financial_requests":0})
        );
        return Ok(false);
    }
    let nonce = nonce(&reply.text().await?)?;
    cookies.add_cookie_str("age_confirmed=1; Path=/; Secure", &Url::parse(ORIGIN)?);
    let mut issuer = Url::parse(&format!("{ORIGIN}/wp-json/games/v1/start"))?;
    issuer
        .query_pairs_mut()
        .append_pair("id", &row.public_game_id)
        .append_pair("mobile", "false");
    let reply = client
        .get(issuer)
        .header("accept", "*/*")
        .header("referer", &page)
        .header("x-requested-with", "XMLHttpRequest")
        .header("x-wp-nonce", nonce)
        .send()
        .await
        .context("NetEnt demo issuer request failed")?;
    let status = reply.status().as_u16();
    let message: Value = if status == 200 {
        reply.json().await.context("NetEnt issuer JSON invalid")?
    } else {
        Value::Null
    };
    let target = message["payload"]
        .as_str()
        .and_then(|s| Url::parse(s).ok())
        .filter(|u| validate_entry_target(u, SHOWCASE, 0).is_ok());
    let launched = status == 200 && message["success"] == true && target.is_some();
    let state = match (status, launched, message["success"].as_bool()) {
        (_, true, _) => "demo_link_issued",
        (200, false, Some(false)) => "issuer_declined",
        (200, false, _) => "unrecognized_issuer_response",
        _ => "http_rejected",
    };
    let (entry_hops, frontend) = match target {
        Some(url) if launched => probe_entry(&client, url, SHOWCASE, &page).await?,
        _ => (Vec::new(), None),
    };
    let demo = frontend.as_ref().and_then(demo_fragment);
    let geco = if row.family == "geco_http" {
        match (frontend.as_ref(), demo.as_ref()) {
            (Some(frontend), Some((wallet, table))) => {
                probe_geco(&client, frontend, wallet, table).await?
            }
            _ => Value::Null,
        }
    } else {
        Value::Null
    };
    println!(
        "{}",
        json!({"game":game,"family":row.family,"page_http":200,"issuer_http":status,
        "state":state,"entry_hops":entry_hops,"frontend_reached":frontend.is_some(),
        "demo_wallet_fragment":demo.is_some(),"geco":geco,"financial_requests":0})
    );
    Ok(if row.family == "geco_http" {
        geco["ready"] == true
    } else {
        frontend.is_some()
    })
}
