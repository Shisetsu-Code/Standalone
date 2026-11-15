use super::belatra_crypto;
use crate::{
    context::RunContext,
    model::{Game, RoundOutcome, decimal, exact_add, exact_mul, exact_sub, now_ms},
};
use anyhow::{Context, Result, ensure};
use rust_decimal::Decimal;
use serde::Deserialize;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use url::Url;
use uuid::Uuid;

const ORIGIN: &str = "https://demo.bltrm.com";

fn amount(v: &Value) -> Result<Decimal> {
    ensure!(v.is_number() || v.is_string(), "missing native amount");
    let value = decimal(
        &v.as_str()
            .map(str::to_owned)
            .unwrap_or_else(|| v.to_string()),
    )?;
    ensure!(value >= Decimal::ZERO, "negative native amount");
    Ok(value)
}

fn minimum(v: &Value) -> Result<Value> {
    let mut least = None;
    for value in v.as_array().context("missing native menu")? {
        let n = amount(value)?;
        ensure!(
            n > Decimal::ZERO && value.is_number(),
            "invalid native menu value"
        );
        if least.as_ref().is_none_or(|(prior, _)| n < *prior) {
            least = Some((n, value.clone()));
        }
    }
    Ok(least.context("empty native menu")?.1)
}

struct Session {
    sid: String,
    secret: String,
    document: Url,
    modification: Value,
    uid: String,
    counter: u32,
}
impl Session {
    async fn exchange(
        &mut self,
        ctx: &RunContext,
        mut command: Value,
        financial: bool,
    ) -> Result<Value> {
        command["uid"] = json!(self.uid);
        command["c"] = json!(self.counter % 1000);
        command["modification"] = self.modification.clone();
        self.counter += 1;
        let now = now_ms();
        let mut prefix = [0; 8];
        prefix[..2].copy_from_slice(&((now % 1000) as u16).to_le_bytes());
        prefix[2..4].copy_from_slice(&Uuid::new_v4().as_bytes()[..2]);
        prefix[4..].copy_from_slice(&((now / 1000) as u32).to_le_bytes());
        let payload = belatra_crypto::seal(&serde_json::to_vec(&command)?, &self.secret, prefix);
        let form = url::form_urlencoded::Serializer::new(String::new())
            .append_pair("d", &payload)
            .append_pair("sid", &self.sid)
            .finish();
        let headers = BTreeMap::from([
            (
                "content-type".into(),
                "application/x-www-form-urlencoded; charset=UTF-8".into(),
            ),
            ("x-requested-with".into(), "XMLHttpRequest".into()),
            ("accept".into(), "*/*".into()),
            ("origin".into(), ORIGIN.into()),
            ("referer".into(), self.document.to_string()),
        ]);
        let label = command["q"].as_str().context("missing operation")?;
        let response = ctx
            .http(
                label,
                "POST",
                &format!("{ORIGIN}/game"),
                headers,
                form,
                financial,
            )
            .await?;
        ensure!(
            response.status == 200,
            "Belatra native HTTP {}",
            response.status
        );
        belatra_crypto::open(serde_json::from_str(&response.body)?, &self.secret)
    }
}

async fn launch(ctx: &RunContext, game: &str) -> Result<Session> {
    ensure!(
        !game.is_empty()
            && game
                .bytes()
                .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'_'),
        "invalid game id"
    );
    let referer = BTreeMap::from([("referer".into(), "https://belatragames.com/".into())]);
    let url = Url::parse(&format!("{ORIGIN}/belatra/demo?game={game}&language=es"))?;
    let response = ctx
        .http(
            "demo_launch",
            "GET",
            url.as_str(),
            referer.clone(),
            String::new(),
            false,
        )
        .await?;
    ensure!(
        response.status == 302,
        "official demo did not issue a redirect"
    );
    let document = url.join(
        response
            .headers
            .get("location")
            .context("demo redirect missing")?,
    )?;
    ensure!(
        document.origin().ascii_serialization() == ORIGIN && document.path() == "/",
        "unreviewed launcher redirect"
    );
    let sid = document
        .query_pairs()
        .find(|(key, _)| key == "sid")
        .context("demo session not issued")?
        .1
        .into_owned();
    let modification = document
        .query_pairs()
        .find(|(key, _)| key == "modification")
        .context("game modification missing")?
        .1
        .into_owned();
    let response = ctx
        .http(
            "demo_document",
            "GET",
            document.as_str(),
            referer,
            String::new(),
            false,
        )
        .await?;
    ensure!(response.status == 200, "official demo document unavailable");
    let (_, source) = response
        .body
        .split_once("var config = ")
        .context("native config missing")?;
    let config = Value::deserialize(&mut serde_json::Deserializer::from_str(source.trim_start()))?;
    ensure!(
        config["nickname"] == game
            && config["request_crypt"] == true
            && config["user"]["sid"] == sid
            && (config["modification"].as_str() == Some(&modification)
                || config["modification"].is_number()
                    && config["modification"].to_string() == modification),
        "native launch identity mismatch"
    );
    let secret = config["sc"]
        .as_str()
        .filter(|x| !x.is_empty())
        .context("native session key missing")?
        .to_owned();
    let uid = format!("_{}", &Uuid::new_v4().simple().to_string()[..9]);
    ctx.save_session(
        &json!({"sid":sid,"sc":secret,"uid":uid,"game":game,"modification":config["modification"]}),
    )?;
    Ok(Session {
        sid,
        secret,
        document,
        modification: config["modification"].clone(),
        uid,
        counter: 0,
    })
}

fn select_mode(gs: &Value, mode: &str, start: &mut Value) -> Result<Decimal> {
    match mode {
        "NORMAL" => Ok(Decimal::ONE),
        "VIP" => {
            let multiplier = amount(&gs["vipMode"]["vipBetK"])?;
            ensure!(multiplier > Decimal::ZERO, "VIP not advertised");
            start["vipOn"] = json!(1);
            Ok(multiplier)
        }
        _ => {
            let index = mode
                .strip_prefix("PURCHASE_")
                .context("unknown mode")?
                .parse::<usize>()?;
            let offer = &gs["buyBonus"]["buyTotalBetK"];
            let factor = if let Some(options) = offer.as_array() {
                let option = options.get(index).context("purchase not advertised")?;
                start["selectId"] = json!(index);
                amount(&option["cost"])?
            } else {
                ensure!(index == 0 && offer.is_number(), "purchase not advertised");
                amount(offer)?
            };
            ensure!(factor >= Decimal::ONE, "invalid native purchase price");
            start["buyBonus"] = json!(1);
            Ok(factor)
        }
    }
}

pub async fn execute(ctx: &RunContext, game: &Game, mode: &str) -> Result<RoundOutcome> {
    let mut session = launch(ctx, &game.id).await?;
    let enter = session
        .exchange(
            ctx,
            json!({"q":"enter","curFloor":1,"userAgent":ctx.user_agent()}),
            false,
        )
        .await?;
    let gs = &enter["gs"];
    ensure!(
        enter["useracc"]["currency"] == "FUN" && gs["phaseNext"] == "toIdle",
        "idle fictional FUN demo not confirmed"
    );
    let before = amount(&enter["useracc"]["amount"])?;
    let lines = gs["nlines"].clone();
    ensure!(
        gs["linesAssortment"]
            .as_array()
            .is_some_and(|a| a.contains(&lines)),
        "unreviewed line menu"
    );
    let bets = gs["betDependOnLines"]
        .as_array()
        .and_then(|a| a.iter().find(|row| row["lines"] == lines))
        .map_or(&gs["betAssortment"], |row| &row["betAssort"]);
    let bet = minimum(bets)?;
    let denom = minimum(&gs["denomAssortment_cents"])?;
    let scale = gs
        .get("linesPerCredit")
        .map(amount)
        .transpose()?
        .unwrap_or(Decimal::ONE);
    let gross = exact_mul(exact_mul(amount(&lines)?, amount(&bet)?)?, amount(&denom)?)?;
    let base = gross.checked_div(scale).context("invalid line factor")?;
    ensure!(
        base > Decimal::ZERO && exact_mul(base, scale)? == gross,
        "invalid native price or funds"
    );
    let mut start = json!({"q":"start","betPerLine":bet,"nlines":lines,"denom":denom,
        "buyBonus":null,"selectId":null,"vipOn":0,"hideInsideInHistory":0,"showingInMoney":0});
    let cost = exact_mul(base, select_mode(gs, mode, &mut start)?)?;
    ensure!(before >= cost, "insufficient demo funds");
    if let Some(id) = gs.get("historyId") {
        start["ghistId"] = id.clone();
    }
    let mut state = session.exchange(ctx, start, true).await?;
    let history = state["gs"]["historyId"].clone();
    ensure!(
        (history.is_string() || history.is_number()) && amount(&state["gs"]["placedbet"])? == cost,
        "native stake or round identity mismatch"
    );
    let native_denom = state["gs"]
        .get("gdenom")
        .map(amount)
        .transpose()?
        .unwrap_or(amount(&denom)?);
    ensure!(
        native_denom == amount(&denom)?,
        "native denomination changed"
    );
    let debited = exact_sub(before, cost)?;
    for _ in 0..ctx.max_steps() {
        ensure!(
            state["useracc"]["currency"] == "FUN"
                && amount(&state["useracc"]["amount"])? == debited
                && state["gs"].get("historyId").is_none_or(|id| *id == history),
            "round owner, currency or debit changed"
        );
        let gs = &state["gs"];
        let next = gs["phaseNext"].as_str().context("native phase missing")?;
        let request = match next {
            "toPaid" | "toDoubleDialog" => {
                let final_state = session
                    .exchange(ctx, json!({"q":"finish","ghistId":history}), true)
                    .await?;
                let end = &final_state["gs"];
                ensure!(
                    end["phaseCur"] == "finished"
                        && end["phaseNext"] == "toIdle"
                        && end.get("historyId").is_none_or(|id| *id == history)
                        && final_state["useracc"]["currency"] == "FUN",
                    "native settlement did not close"
                );
                let payout = exact_mul(amount(&end["curWin"])?, native_denom)?;
                let after = amount(&final_state["useracc"]["amount"])?;
                ensure!(
                    exact_add(debited, payout)? == after,
                    "wallet settlement mismatch"
                );
                return Ok(RoundOutcome {
                    native_round_id: Some(
                        history
                            .as_str()
                            .map(str::to_owned)
                            .unwrap_or_else(|| history.to_string()),
                    ),
                    currency: "FUN".into(),
                    currency_source: "native_response".into(),
                    monetary_unit: "native".into(),
                    balance_before: before.to_string(),
                    cost: cost.to_string(),
                    payout: payout.to_string(),
                    balance_after: after.to_string(),
                    native_closed: true,
                    checks: BTreeMap::from([
                        ("wallet_ledger".into(), true),
                        ("native_debit".into(), true),
                        ("demo".into(), true),
                    ]),
                    native_data: json!({"game":game.id}),
                });
            }
            "toRespin" | "toNextFG" if gs["respinInfo"]["nIt"].as_u64().is_some_and(|n| n >= 1) => {
                json!({"q":"play","userAction":"askRespin","ghistId":history})
            }
            "toNextFG" if gs["freeInfo"]["remain"].as_u64().is_some_and(|n| n >= 1) => {
                json!({"q":"play","userAction":"askNextFG","remainFG":gs["freeInfo"]["remain"],"ghistId":history})
            }
            _ => anyhow::bail!("unreviewed native continuation; retain round"),
        };
        state = session.exchange(ctx, request, true).await?;
    }
    anyhow::bail!("native continuation limit reached")
}

#[cfg(test)]
mod mode_tests {
    use super::*;

    #[test]
    fn purchase_and_vip_selectors_use_native_prices() {
        let mut body = json!({"vipOn":0,"buyBonus":null,"selectId":null});
        let menu = json!({"vipMode":{"vipBetK":1.5},"buyBonus":{"buyTotalBetK":[{"cost":100},{"cost":250}]}});
        assert_eq!(
            select_mode(&menu, "PURCHASE_1", &mut body).unwrap(),
            Decimal::from(250)
        );
        assert_eq!(body, json!({"vipOn":0,"buyBonus":1,"selectId":1}));
        assert!(select_mode(&menu, "PURCHASE_2", &mut body).is_err());
        let mut vip = json!({"vipOn":0,"buyBonus":null,"selectId":null});
        assert_eq!(
            select_mode(&menu, "VIP", &mut vip).unwrap(),
            decimal("1.5").unwrap()
        );
        assert_eq!(vip, json!({"vipOn":1,"buyBonus":null,"selectId":null}));
        let mut scalar = json!({"vipOn":0,"buyBonus":null,"selectId":null});
        assert_eq!(
            select_mode(
                &json!({"buyBonus":{"buyTotalBetK":50}}),
                "PURCHASE_0",
                &mut scalar
            )
            .unwrap(),
            Decimal::from(50)
        );
        assert!(scalar["selectId"].is_null());
    }
}
