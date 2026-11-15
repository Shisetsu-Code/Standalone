use crate::{
    context::RunContext,
    model::{Game, Mode, ModeKind, RoundOutcome, sha256},
};
use anyhow::{Context, Result, ensure};
use base64::{Engine, engine::general_purpose::STANDARD};
use flate2::read::GzDecoder;
use rquickjs::{CatchResultExt, Context as JsContext, Runtime};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    io::Read,
    time::{Duration, Instant},
};
use url::Url;

const GAME: &str = "rp_47";
const MATH: u64 = 20201103;
const API: &str = "https://srv.prrpeu3.com";
const SOURCE: &str =
    "https://static2.eu3cdn-83.servpavloro.com/africancats/latest/static/js/game.js";
const HASH: &str = "cd94725c10fbd5a1c70313b64c5eacaa6d17c89d52ea745601c48de7133c9c50";

pub fn supports(game: &Game, mode: &Mode) -> bool {
    game.id == GAME && mode.kind == ModeKind::Normal && mode.key == "normal"
}

#[derive(Deserialize)]
#[serde(untagged)]
enum Fragment {
    Script(String),
    Slice(String, usize, usize, String),
}

impl Fragment {
    fn append(&self, source: &str, out: &mut String) -> Result<()> {
        match self {
            Self::Script(s) => out.push_str(s),
            Self::Slice(prefix, at, len, suffix) => {
                out.push_str(prefix);
                out.push_str(
                    source
                        .get(
                            *at..at
                                .checked_add(*len)
                                .context("RubyPlay source range overflow")?,
                        )
                        .context("RubyPlay source range outside bundle")?,
                );
                out.push_str(suffix);
            }
        }
        Ok(())
    }
}

#[derive(Deserialize)]
struct Extraction {
    source_sha256: String,
    definitions: Vec<Fragment>,
    calls: Vec<Vec<Fragment>>,
}

fn inspect(source: &str, init: &Value, replies: &[(u64, Value)]) -> Result<Value> {
    let extraction: Extraction = serde_json::from_str(include_str!(
        "../../bindings/rubyplay-rp47-source-index.json"
    ))?;
    ensure!(
        extraction.source_sha256 == HASH && sha256(source.as_bytes()) == HASH,
        "RubyPlay native bundle changed"
    );
    let runtime = Runtime::new()?;
    runtime.set_memory_limit(96 * 1024 * 1024);
    runtime.set_max_stack_size(1024 * 1024);
    let deadline = Instant::now() + Duration::from_secs(5);
    runtime.set_interrupt_handler(Some(Box::new(move || Instant::now() >= deadline)));
    let context = JsContext::full(&runtime)?;
    context.with(|ctx| -> Result<Value> {
        let run = |script: &str| -> Result<()> {
            ctx.eval::<(), _>(script).catch(&ctx).map_err(|e| anyhow::anyhow!("RubyPlay decoder: {e}"))
        };
        run("Math.random=()=>{throw Error('native random fallback forbidden')};var console={log(){},warn(){},error(){}};")?;
        let mut definitions = String::new();
        for f in extraction.definitions { f.append(source, &mut definitions)?; definitions.push('\n'); }
        run(&definitions)?;
        for call in extraction.calls {
            let mut script = String::new();
            for f in call { f.append(source, &mut script)?; }
            run(&script)?;
        }
        run("var nativeProxy=CE.createProxy();if(_t.getProtocolVersion()!==2||nativeProxy.getEngine().getMathVersion()!==20201103)throw Error('unexpected native decoder version');")?;
        let initial = binary(init)?;
        let balance = amount(&init["data"]["player"]["balance"])?;
        run(&format!("var initial=new Js(0);initial.addField('binary',{initial}).addField('balance',{balance});nativeProxy.handleResponse(initial);"))?;
        let bets = init["data"]["game_config"]["bets"].as_array().context("RubyPlay bet menu missing")?;
        let min = bets.iter().map(amount).collect::<Result<Vec<_>>>()?.into_iter().min().filter(|n| *n > 0)
            .context("RubyPlay has no positive minimum bet")?;
        let mut phases = Vec::new();
        for (action, reply) in replies {
            run(&format!("var request=new Js({action});if({action}===1)request.addField('bet',{min});nativeProxy.prepareRequest(request);"))?;
            let bytes = binary(reply)?;
            let balance = amount(&reply["data"]["player"]["balance"])?;
            let an = amount(&reply["data"]["an"])?;
            run(&format!("var message=new Js({action});message.addField('binary',{bytes}).addField('balance',{balance}).addField('an',{an});nativeProxy.handleResponse(message);"))?;
            let phase: String = ctx.eval("JSON.stringify({win:nativeProxy.getSession().getTotalWin(),next:nativeProxy.getSession().nextAction(),actionWin:nativeProxy.getSession().getGameSettings().actionWin})")
                .catch(&ctx).map_err(|e| anyhow::anyhow!("RubyPlay result decoder: {e}"))?;
            phases.push(serde_json::from_str::<Value>(&phase)?);
        }
        let request: String = ctx.eval(format!("JSON.stringify((()=>{{var action=nativeProxy.getSession().nextAction(),before=nativeProxy.getSession().getPlayer().getBalance(),request=new Js(action);if(action===1)request.addField('bet',{min});nativeProxy.prepareRequest(request);return {{action,fields:request.getFields(),cost:before-nativeProxy.getSession().getPlayer().getBalance()}}}})())"))
            .catch(&ctx).map_err(|e| anyhow::anyhow!("RubyPlay request decoder: {e}"))?;
        Ok(json!({"next":serde_json::from_str::<Value>(&request)?,"phases":phases}))
    })
}

fn binary(reply: &Value) -> Result<String> {
    let encoded = reply["data"]["binary"]
        .as_str()
        .context("RubyPlay binary missing")?;
    ensure!(encoded.len() <= 256 * 1024, "RubyPlay binary too large");
    Ok(serde_json::to_string(&STANDARD.decode(encoded)?)?)
}

fn amount(value: &Value) -> Result<u64> {
    value
        .as_u64()
        .filter(|n| *n <= 9_007_199_254_740_991)
        .context("RubyPlay integer missing or outside exact range")
}

pub async fn execute(ctx: &RunContext, game: &Game, mode: &Mode) -> Result<RoundOutcome> {
    ensure!(
        supports(game, mode),
        "RubyPlay mode has no reviewed binding"
    );
    let headers = BTreeMap::from([
        ("user-agent".into(), "Mozilla/5.0".into()),
        (
            "accept".into(),
            "text/html,application/json,application/javascript".into(),
        ),
    ]);
    let source = ctx
        .http(
            "native_source",
            "GET",
            SOURCE,
            headers.clone(),
            String::new(),
            false,
        )
        .await?;
    ensure!(
        source.status == 200,
        "RubyPlay source HTTP {}",
        source.status
    );
    let content = if source
        .headers
        .get("x-evidencia-body-encoding")
        .is_some_and(|s| s == "base64")
    {
        STANDARD.decode(source.body)?
    } else {
        source.body.into_bytes()
    };
    let source = if content.starts_with(&[0x1f, 0x8b]) {
        let mut value = String::new();
        GzDecoder::new(content.as_slice())
            .take(4 * 1024 * 1024)
            .read_to_string(&mut value)?;
        value
    } else {
        String::from_utf8(content)?
    };
    ensure!(
        sha256(source.as_bytes()) == HASH,
        "RubyPlay native bundle changed"
    );
    let issuer = Url::parse_with_params(
        &format!("{API}/init-session/demo"),
        [
            ("gamename", GAME),
            ("operator", "rubyplay.com"),
            ("mode", "fun"),
            ("currency", "EUR"),
            ("playerSession", ""),
        ],
    )?;
    let session = ctx
        .http(
            "demo_session",
            "GET",
            issuer.as_str(),
            headers.clone(),
            String::new(),
            false,
        )
        .await?;
    ensure!(
        session.status == 200,
        "RubyPlay issuer HTTP {}",
        session.status
    );
    let session: Value = serde_json::from_str(&session.body)?;
    let key = session["sessionKey"]
        .as_str()
        .filter(|s| !s.is_empty())
        .context("RubyPlay session missing")?;
    ensure!(
        session["status"] == "success" && !session["funModeData"].is_null(),
        "RubyPlay demo unavailable"
    );
    let endpoint = format!("{API}/gameserver/demo");
    let init = ctx
        .json(
            "init",
            &endpoint,
            &json!({"v_protocol":2,"v_math":MATH,"key":key,"device_type":"desktop",
        "funModeData":session["funModeData"],"action":"init"}),
            headers.clone(),
            false,
        )
        .await?;
    ensure!(
        init["status"] == "ok"
            && init["topic"] == "gameserver/init"
            && init["data"]["next_action"] == "spin"
            && init["data"]["an"] == 0,
        "RubyPlay demo is not idle"
    );
    let before = amount(&init["data"]["player"]["balance"])?;
    let mut previous = before;
    let mut fun = init["funModeData"].clone();
    let mut replies = Vec::new();
    let mut cost = 0;
    let mut previous_win = 0;
    let mut payout = 0_u64;
    ctx.save_session(&json!({"game":GAME,"key":key,"currency":"EUR"}))?;
    let mut decoded = inspect(&source, &init, &replies)?;
    for index in 0..ctx.max_steps().min(64) {
        let next = &decoded["next"];
        let action = amount(&next["action"])?;
        let name = match (index, action) {
            (0, 1) => "spin",
            (1.., 2) => "freespin",
            (1.., 3) => "respin",
            _ => anyhow::bail!("RubyPlay continuation requires review"),
        };
        let debit = amount(&next["cost"])?;
        if index == 0 {
            cost = debit;
        }
        ensure!(
            ((index == 0 && debit > 0) || (index > 0 && debit == 0))
                && previous >= debit
                && !fun.is_null(),
            "RubyPlay unexpected wager or demo funds"
        );
        let mut wire = next["fields"].clone();
        ensure!(
            wire.is_object()
                && wire["v_protocol"] == 2
                && wire["v_math"] == MATH
                && wire["an"] == index as u64,
            "RubyPlay native request binding changed"
        );
        wire["key"] = json!(key);
        wire["device_type"] = json!("desktop");
        wire["funModeData"] = fun;
        wire["action"] = json!(name);
        let reply = ctx
            .json(name, &endpoint, &wire, headers.clone(), true)
            .await?;
        ensure!(
            reply["status"] == "ok" && reply["data"]["an"] == (index + 1) as u64,
            "RubyPlay round response changed"
        );
        let after = amount(&reply["data"]["player"]["balance"])?;
        fun = reply["funModeData"].clone();
        replies.push((action, reply));
        decoded = inspect(&source, &init, &replies)?;
        let phase = &decoded["phases"][index];
        let win = amount(&phase["win"])?;
        let closed = phase["next"] == 1;
        let credit = if phase["actionWin"] == true {
            win.checked_sub(previous_win)
                .context("RubyPlay cumulative award decreased")?
        } else if closed {
            win
        } else {
            0
        };
        ensure!(
            previous
                .checked_sub(debit)
                .and_then(|v| v.checked_add(credit))
                == Some(after),
            "RubyPlay native award and wallet disagree"
        );
        payout = payout
            .checked_add(credit)
            .context("RubyPlay total award overflow")?;
        if closed {
            ensure!(
                replies[index].1["data"]["next_action"] == "spin",
                "RubyPlay terminal marker changed"
            );
            return Ok(RoundOutcome {
                native_round_id: None,
                currency: "EUR".into(),
                currency_source: "launcher_parameter".into(),
                monetary_unit: "native".into(),
                balance_before: before.to_string(),
                balance_after: after.to_string(),
                cost: cost.to_string(),
                payout: payout.to_string(),
                native_closed: true,
                checks: BTreeMap::from([("native_binary_award".into(), true)]),
                native_data: json!({"game":GAME,"actions":index+1,"source_sha256":HASH}),
            });
        }
        previous = after;
        previous_win = win;
    }
    anyhow::bail!("RubyPlay continuation limit reached")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    #[ignore = "requires the private African Cats archive"]
    fn archived_african_cats_decodes_its_own_native_result() -> Result<()> {
        let fixture = std::path::PathBuf::from(
            std::env::var_os("RUBYPLAY_FIXTURE").context("set RUBYPLAY_FIXTURE")?,
        );
        let source = std::fs::read_to_string(fixture.join("game-js.body.private"))?;
        let init =
            serde_json::from_slice(&std::fs::read(fixture.join("native-init.body.private"))?)?;
        let expected: Value =
            serde_json::from_slice(&std::fs::read(fixture.join("normal-0001.request.private"))?)?;
        let reply =
            serde_json::from_slice(&std::fs::read(fixture.join("normal-0001.body.private"))?)?;
        let before = inspect(&source, &init, &[])?;
        assert_eq!(before["next"]["cost"], 20);
        for key in ["bet", "v_protocol", "v_math", "an"] {
            assert_eq!(before["next"]["fields"][key], expected[key]);
        }
        let after = inspect(&source, &init, &[(1, reply)])?;
        assert_eq!(after["phases"][0]["win"], 0);
        assert_eq!(after["phases"][0]["next"], 1);
        Ok(())
    }
}
