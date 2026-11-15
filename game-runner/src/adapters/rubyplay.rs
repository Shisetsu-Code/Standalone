use anyhow::{Context, Result, ensure};
use serde_json::{Value, json};
use std::time::Duration;

const ORIGIN: &str = "https://srv.prrpeu3.com";
const GAME: &str = "rp_47";

pub(crate) async fn probe(game: &str) -> Result<bool> {
    ensure!(
        game == GAME,
        "RubyPlay launch binding is available for African Cats"
    );
    let client = reqwest::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(20))
        .redirect(reqwest::redirect::Policy::none())
        .retry(reqwest::retry::never())
        .user_agent("Mozilla/5.0")
        .build()?;
    let issuer = url::Url::parse_with_params(
        &format!("{ORIGIN}/init-session/demo"),
        [
            ("gamename", GAME),
            ("operator", "rubyplay.com"),
            ("mode", "fun"),
            ("currency", "EUR"),
            ("playerSession", ""),
        ],
    )?;
    let reply = client
        .get(issuer)
        .header(
            "accept",
            "text/html,application/json,application/javascript",
        )
        .send()
        .await
        .context("RubyPlay demo issuer request failed")?;
    let issuer_http = reply.status().as_u16();
    if issuer_http != 200 {
        println!(
            "{}",
            json!({"game":game,"issuer_http":issuer_http,"financial_requests":0})
        );
        return Ok(false);
    }
    let session: Value = reply.json().await?;
    let key = session["sessionKey"]
        .as_str()
        .filter(|s| !s.is_empty())
        .context("RubyPlay session key missing")?;
    ensure!(
        session["status"] == "success" && !session["funModeData"].is_null(),
        "RubyPlay public demo was not issued"
    );
    let reply = client
        .post(format!("{ORIGIN}/gameserver/demo"))
        .header(
            "accept",
            "text/html,application/json,application/javascript",
        )
        .json(
            &json!({"v_protocol":2,"v_math":20201103,"key":key,"device_type":"desktop",
            "funModeData":session["funModeData"],"action":"init"}),
        )
        .send()
        .await
        .context("RubyPlay demo initialization failed")?;
    let init_http = reply.status().as_u16();
    let mut initialized = false;
    if init_http == 200 {
        let init: Value = reply.json().await?;
        let d = &init["data"];
        initialized = init["status"] == "ok"
            && init["topic"] == "gameserver/init"
            && d["next_action"] == "spin"
            && d["an"] == 0
            && d["binary"].as_str().is_some_and(|v| !v.is_empty())
            && d["player"]["balance"].as_u64().is_some();
    }
    println!(
        "{}",
        json!({"game":game,"issuer_http":issuer_http,"init_http":init_http,
        "idle_demo":initialized,"financial_requests":0})
    );
    Ok(initialized)
}
