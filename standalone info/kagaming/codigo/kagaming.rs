//! Bonus Mania public demo, ported from the published KA client and receipt.
use crate::{context::RunContext, model::*};
use anyhow::{Context, Result, ensure};
use rust_decimal::Decimal;
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::LazyLock,
    time::Duration,
};
use uuid::Uuid;

#[cfg(test)]
const GAME_HASH: &str = "2239f232a495aeab4b4a75cefb1446fd911d95895ab2bc43f2f8a1ba19bc40ed";
const ENGINE_SOURCE: &str = "https://gamesdemo.kaga88.com/game.min.2090.js";
const ENGINE_HASH: &str = "6cf1bdace2d5fb0a889364ad05fa3a3a31ed2fc37aa79b36be4ee71a6e49a0f2";

#[derive(Clone, Debug)]
struct Profile {
    game: String,
    sel: i64,
    cps: i64,
    dn: Value,
    cost: Decimal,
    atb: i64,
    reset_atb: bool,
    position: Option<Vec<u64>>,
    source_sha256: String,
}

#[derive(Deserialize)]
struct Binding {
    source_sha256: String,
    sel: i64,
    cps: i64,
    dn: Value,
    cost: u64,
    atb: i64,
    reset_atb: bool,
    position: Option<Vec<u64>>,
}

fn atb_for_step(atb: i64, reset_atb: bool, step: usize) -> i64 {
    if reset_atb && step > 0 { 0 } else { atb }
}

static BINDINGS: LazyLock<BTreeMap<String, BTreeMap<String, Binding>>> = LazyLock::new(|| {
    serde_json::from_str(include_str!("../../bindings/kagaming.json"))
        .expect("valid embedded KA Gaming bindings")
});

fn binding(game: &Game, mode: &Mode) -> Option<&'static Binding> {
    let expected = if mode.key == "normal" {
        ModeKind::Normal
    } else if mode.key.starts_with("ante-") {
        ModeKind::AnteBet
    } else if mode.key.starts_with("buy-") {
        ModeKind::Purchase
    } else if game.id == "PenaltyShootout" && mode.key.starts_with("target-") {
        ModeKind::Variant
    } else {
        return None;
    };
    if mode.kind != expected {
        return None;
    }
    BINDINGS.get(&game.id)?.get(&mode.key)
}

pub fn supports(game: &Game, mode: &Mode) -> bool {
    binding(game, mode).is_some()
}
fn hash31(text: &str) -> i32 {
    text.encode_utf16().fold(0_i32, |hash, unit| {
        hash.wrapping_mul(31).wrapping_add(i32::from(unit))
    })
}
fn signed_context(body: &str, context: &Value, timestamp: u64) -> Result<Value> {
    let mut signed = context.as_object().context("KA context missing")?.clone();
    let device = context["idv"]
        .as_str()
        .context("KA device identity missing")?;
    let version = context["dv"]
        .as_str()
        .context("KA device version missing")?;
    let time = timestamp.to_string();
    // This constant is the published anonymous demo client's request signature,
    // never a credential loaded from another player's session.
    let salt = "SzXS@78TWls@x9&$5212Qw*oOZP@!tQybp5msFRpt1b@kaqN@3ms2932733tSyst";
    let e = hash31(&format!("{body}2090{device}{time}"));
    let f = hash31(&format!("{time}{device}{version}"));
    let source = if e % 2 == 0 {
        format!("{time}1.0.268 (2090){e}{salt}{f}{body}2090")
    } else {
        format!("{salt}{body}{f}{version}{e}2090{time}")
    };
    signed.insert(
        "ida".into(),
        json!(format!("{}{time}", sha256(source.as_bytes()))),
    );
    Ok(Value::Object(signed))
}
fn amount(value: &Value) -> Result<Decimal> {
    ensure!(
        value.is_string() || value.is_number(),
        "KA native number missing"
    );
    decimal(
        value
            .as_str()
            .map(str::to_owned)
            .unwrap_or_else(|| value.to_string())
            .as_str(),
    )
}
fn integer(value: &Value) -> Result<i64> {
    let n = amount(value)?;
    ensure!(n.fract().is_zero(), "KA native integer expected");
    n.normalize()
        .to_string()
        .parse()
        .context("KA native integer out of range")
}
fn populated(value: Option<&Value>) -> bool {
    match value {
        None | Some(Value::Null) | Some(Value::Bool(false)) => false,
        Some(Value::Array(v)) => !v.is_empty(),
        Some(Value::Object(v)) => !v.is_empty(),
        Some(Value::String(v)) => !v.is_empty(),
        Some(Value::Number(v)) => v.to_string() != "0",
        _ => true,
    }
}
fn profile(init: &Value, game: &str, binding: &Binding) -> Result<Profile> {
    ensure!(
        init["gn"] == game && init["gm"] == 0 && init["mi"] == -1 && init["fs"] == false,
        "KA initialization is not a fresh demo for the selected game"
    );
    ensure!(
        init["e"] == false && init["ec"] == 0 && init["sgr"]["lsd"]["cr"] == "USD",
        "KA demo/currency not confirmed"
    );
    ensure!(
        !remaining(&init["sgr"]["lsd"])?
            && integer(&init["sgr"]["lsd"]["pbb"])? == 0
            && integer(&init["sgr"]["lsd"]["obb"])? == 0,
        "KA fresh session has previous state"
    );
    let minimum = |key: &str| -> Result<i64> {
        let values = init[key]
            .as_array()
            .context("KA native offer missing")?
            .iter()
            .map(integer)
            .collect::<Result<Vec<_>>>()?;
        ensure!(
            values.iter().all(|n| *n > 0),
            "KA native offer contains invalid amount"
        );
        values.into_iter().min().context("KA native offer empty")
    };
    let sel = minimum("ase")?;
    let cps = minimum("cup")?;
    let denominations = init["dn"].as_array().context("KA denominations missing")?;
    let mut dn: Option<(Decimal, Value)> = None;
    for value in denominations {
        let n = amount(value)?;
        ensure!(n > Decimal::ZERO, "KA invalid denomination");
        if dn.as_ref().is_none_or(|(old, _)| n < *old) {
            dn = Some((n, value.clone()));
        }
    }
    let dn = dn.context("KA denominations empty")?.1;
    ensure!(
        sel == binding.sel && cps == binding.cps && amount(&dn)? == amount(&binding.dn)?,
        "KA offer differs from the reviewed minimum"
    );
    Ok(Profile {
        game: game.into(),
        sel,
        cps,
        dn,
        cost: Decimal::from(binding.cost),
        atb: binding.atb,
        reset_atb: binding.reset_atb,
        position: binding.position.clone(),
        source_sha256: binding.source_sha256.clone(),
    })
}
fn free_spins_remaining(md: &Value) -> Result<bool> {
    ensure!(
        integer(&md["rf"])? == 0,
        "KA respin state requires a reviewed binding"
    );
    let free_spins = integer(&md["fsr"])?;
    ensure!(free_spins >= 0, "KA negative free-spin count");
    ensure!(
        free_spins == 0 || !populated(md.get("fsd")),
        "KA bundled free spins require review"
    );
    Ok(free_spins > 0)
}

fn remaining(md: &Value) -> Result<bool> {
    ensure!(
        !populated(md.get("bpd")),
        "KA bonus choice requires a reviewed binding"
    );
    free_spins_remaining(md)
}

fn space_pick_pending(md: &Value) -> Result<bool> {
    let bonus = &md["bpd"];
    if bonus.is_null() {
        return Ok(false);
    }
    match (bonus["c"].as_bool(), bonus["s"].as_bool()) {
        (Some(true), Some(true)) => Ok(false),
        (Some(false), Some(false)) => {
            ensure!(
                md["acb"] == 2 && bonus["np"] == 3 && bonus["w"] == 0,
                "KA Space bonus offer changed"
            );
            Ok(true)
        }
        _ => anyhow::bail!("KA Space bonus flags changed"),
    }
}

fn space_pick_award(
    prior: &Value,
    next: &Value,
    request: &Value,
    response: &Value,
) -> Result<Decimal> {
    ensure!(
        space_pick_pending(prior)?
            && next["bpd"]["c"] == true
            && !space_pick_pending(next)?
            && request["p"] == 0
            && response["p"] == 0
            && request["sid"] == prior["sid"]
            && next["sid"] == prior["sid"]
            && next["tw"] == prior["tw"]
            && next["tid"] == prior["tid"],
        "KA Space bonus selection differs from the open spin"
    );
    let win = integer(&next["bpd"]["w"])?;
    ensure!(
        win >= 0 && integer(&next["bpd"]["lpw"])? == win,
        "KA Space bonus award differs from the completed pick"
    );
    Ok(Decimal::from(win))
}

impl Profile {
    fn position_for_step(&self, step: usize) -> Option<&Vec<u64>> {
        if step == 0 || self.game == "PenaltyShootout" {
            self.position.as_ref()
        } else {
            None
        }
    }

    fn pending(&self, md: &Value) -> Result<bool> {
        if self.game == "Space" {
            let free = free_spins_remaining(md)?;
            Ok(space_pick_pending(md)? || free)
        } else {
            remaining(md)
        }
    }
}
fn reconcile(before: Decimal, profile: &Profile, steps: &[(Value, Value)]) -> Result<RoundOutcome> {
    let outcome = validate_chain(before, profile, steps)?;
    ensure!(outcome.native_closed, "KA native round still open");
    Ok(outcome)
}
fn validate_chain(
    before: Decimal,
    profile: &Profile,
    steps: &[(Value, Value)],
) -> Result<RoundOutcome> {
    ensure!(
        !steps.is_empty() && profile.cost > Decimal::ZERO,
        "KA no paid root"
    );
    let tid = steps[0].1["md"]["tid"]
        .as_str()
        .filter(|s| !s.is_empty())
        .context("KA round identity missing")?;
    let mut previous = before;
    let mut payout = Decimal::ZERO;
    let mut ids = BTreeSet::new();
    for (i, (request, response)) in steps.iter().enumerate() {
        let md = &response["md"];
        ensure!(
            response["e"] == false && response["ec"] == 0 && md["v"] == true,
            "KA native response rejected"
        );
        let sid = integer(&request["sid"])?;
        if profile.game == "Space" && request.get("p").is_some() {
            ensure!(
                i > 0 && request["gn"] == profile.game && md["cr"] == "USD",
                "KA Space pick has no matching root"
            );
            let bonus = space_pick_award(&steps[i - 1].1["md"], md, request, response)?;
            let after = amount(&response["cr"])?;
            ensure!(
                after == exact_add(previous, bonus)? && amount(&md["obb"])? == after,
                "KA Space bonus credit does not match the native award"
            );
            payout = exact_add(payout, bonus)?;
            previous = after;
            continue;
        }
        ensure!(
            sid >= 0 && sid == integer(&response["sid"])? && ids.insert(sid),
            "KA native request identity mismatch"
        );
        ensure!(
            integer(&md["sid"])? >= 0 && md["cr"] == "USD",
            "KA invalid native spin identity or currency"
        );
        ensure!(
            request["gn"] == profile.game
                && md["tid"] == tid
                && request.get("pos").cloned() == profile.position_for_step(i).map(|p| json!(p)),
            "KA root/choice identity changed"
        );
        ensure!(
            integer(&request["sel"])? == profile.sel
                && integer(&request["cps"])? == profile.cps
                && integer(&request["atb"])? == atb_for_step(profile.atb, profile.reset_atb, i)
                && amount(&request["dn"])? == amount(&profile.dn)?,
            "KA request differs from native offer"
        );
        for key in ["sel", "cps", "dn", "atb"] {
            ensure!(
                amount(&request[key])? == amount(&md[key])?,
                "KA native parameter echo mismatch"
            );
        }
        if profile.game == "PenaltyShootout" {
            ensure!(
                md["pos"] == request["pos"] && !populated(md.get("fsd")),
                "KA penalty target or native continuation changed"
            );
        }
        if i > 0 {
            ensure!(
                profile.pending(&steps[i - 1].1["md"])?
                    && (profile.game != "Space" || !space_pick_pending(&steps[i - 1].1["md"])?),
                "KA extra paid entry after closure"
            );
        }
        let pcr = amount(&response["pcr"])?;
        let after = amount(&response["cr"])?;
        let credit = amount(&md["tw"])?;
        if profile.game == "Space" {
            ensure!(
                md["bpd"].is_null() || space_pick_pending(md)? || md["bpd"]["w"] == 0,
                "KA Space reported an unobserved completed bonus"
            );
        }
        ensure!(
            credit >= Decimal::ZERO
                && credit.fract().is_zero()
                && after.fract().is_zero()
                && pcr.fract().is_zero(),
            "KA native ledger must be integral and prize nonnegative"
        );
        let debit = if i == 0 { profile.cost } else { Decimal::ZERO };
        ensure!(
            pcr == exact_sub(previous, debit)? && after == exact_add(pcr, credit)?,
            "KA native payout/wallet mismatch"
        );
        ensure!(
            amount(&md["pbb"])? == previous && amount(&md["obb"])? == after,
            "KA native wallet echo mismatch"
        );
        payout = exact_add(payout, credit)?;
        previous = after;
    }
    let closed = !profile.pending(&steps.last().context("KA missing last step")?.1["md"])?;
    Ok(RoundOutcome {
        native_round_id: Some(tid.into()),
        currency: "USD".into(),
        monetary_unit: "native".into(),
        currency_source: "native_response".into(),
        balance_before: before.to_string(),
        balance_after: previous.to_string(),
        cost: profile.cost.to_string(),
        payout: payout.to_string(),
        native_closed: closed,
        checks: BTreeMap::from([
            ("native_parameter_echo".into(), true),
            ("independent_native_prize".into(), true),
            ("single_native_root".into(), true),
        ]),
        native_data: json!({"denomination":profile.dn,"steps":steps,"game_source_sha256":profile.source_sha256,"engine_source_sha256":ENGINE_HASH}),
    })
}
pub fn validate(game: &Game, mode: &Mode, settings: &Value) -> Result<()> {
    ensure!(
        supports(game, mode),
        "KA mode has no reviewed native slot binding"
    );
    ensure!(
        settings.is_null() || settings.as_object().is_some_and(|o| o.is_empty()),
        "KA public binding has no overrides"
    );
    Ok(())
}
async fn get(ctx: &RunContext, label: &str, url: &str) -> Result<String> {
    let reply = ctx.get(label, url).await?;
    ensure!(reply.status == 200, "KA HTTP failure at {label}");
    Ok(reply.body)
}
async fn call(
    ctx: &RunContext,
    label: &str,
    path: &str,
    user: &str,
    context: &Value,
    body: &Value,
    financial: bool,
) -> Result<Value> {
    let bytes = serde_json::to_string(body)?;
    let signed = signed_context(&bytes, context, now_ms())?;
    let headers = BTreeMap::from([
        ("content-type".into(), "application/json".into()),
        ("ctx".into(), serde_json::to_string(&signed)?),
        ("origin".into(), "https://gamesdemo.kaga88.com".into()),
        ("referer".into(), "https://gamesdemo.kaga88.com/".into()),
    ]);
    let url = format!("https://rmpdemo.kaga88.com{path}?ak=accessKey&cr=USD&m=0&u={user}");
    let reply = ctx
        .http(label, "POST", &url, headers, bytes, financial)
        .await?;
    ensure!(reply.status == 200, "KA HTTP failure at {label}");
    let value: Value = serde_json::from_str(&reply.body).context("KA invalid native JSON")?;
    ensure!(
        value["e"] == false && value["ec"] == 0,
        "KA native command rejected at {label}"
    );
    Ok(value)
}
pub async fn execute(
    ctx: &RunContext,
    game: &Game,
    mode: &Mode,
    settings: &Value,
) -> Result<RoundOutcome> {
    validate(game, mode, settings)?;
    let binding = binding(game, mode).context("KA native mode missing")?;
    let user = (100_000_000_u128 + Uuid::new_v4().as_u128() % 900_000_000).to_string();
    let launch = url::Url::parse_with_params(
        "https://gamesdemo.kaga88.com/",
        [
            ("g", game.id.as_str()),
            ("p", "demo"),
            ("u", user.as_str()),
            ("t", "1238"),
            ("ak", "accessKey"),
            ("cr", "USD"),
            ("loc", "es"),
        ],
    )?;
    get(ctx, "launcher", launch.as_str()).await?;
    let source_url = format!(
        "https://gamesdemo.kaga88.com/res/js/2090/{}.js",
        game.id.to_ascii_lowercase()
    );
    let source = get(ctx, "public_client", &source_url).await?;
    ensure!(
        sha256(source.as_bytes()) == binding.source_sha256,
        "KA game client changed; no bet sent"
    );
    let engine = get(ctx, "public_engine", ENGINE_SOURCE).await?;
    ensure!(
        sha256(engine.as_bytes()) == ENGINE_HASH,
        "KA public engine changed; no bet sent"
    );
    let mut context = json!({"dt":"Evidencia Rust QA client","dv":env!("CARGO_PKG_VERSION"),"av":"1.0.268 (2090)","idv":sha256(Uuid::new_v4().as_bytes()),"lg":"es","do":"Linux","as":"","ak":"accessKey"});
    let start = json!({"un":user,"pn":"demo","ak":"accessKey","gn":game.id,"loc":"es","to":"123","cr":"USD","gm":0,"tb":null,"mi":-1,"mc":0});
    let init = call(
        ctx,
        "init",
        "/kaga/rmp/startGame",
        &user,
        &context,
        &start,
        false,
    )
    .await?;
    let session = init["si"]
        .as_str()
        .filter(|s| !s.is_empty() && *s != "[REDACTED]")
        .context("KA fresh demo session missing")?;
    let returned_user = init["un"]
        .as_str()
        .filter(|s| !s.is_empty() && *s != "[REDACTED]")
        .context("KA fresh demo user missing")?;
    // The server returns the canonical anonymous account used in ctx.u; the
    // published client keeps the original public user in the query string.
    context["u"] = json!(returned_user);
    context["c"] = json!(session);
    ctx.save_session(&json!({"provider":"kagaming","game":game.id,"demo_user":user,"session_id":session,"context":context,"currency":"USD","game_source_sha256":binding.source_sha256,"engine_source_sha256":ENGINE_HASH}))?;
    let p = profile(&init, &game.id, binding)?;
    let before = amount(&init["bl"])?;
    ensure!(
        before.fract().is_zero() && before >= p.cost,
        "KA invalid demo wallet"
    );
    let mut steps: Vec<(Value, Value)> = Vec::new();
    let seed = now_ms() % 2_000_000_000;
    for index in 0..ctx.max_steps() {
        tokio::time::sleep(Duration::from_secs(2)).await;
        if p.game == "Space"
            && let Some((_, previous)) = steps.last()
            && space_pick_pending(&previous["md"])?
        {
            let request = json!({"gn":game.id,"p":0,"sid":integer(&previous["md"]["sid"])?});
            let reply = call(
                ctx,
                "bonus_pick",
                "/kaga/command/bonusPick",
                &user,
                &context,
                &request,
                true,
            )
            .await?;
            steps.push((request, reply));
            if validate_chain(before, &p, &steps)?.native_closed {
                break;
            }
            continue;
        }
        let mut request = json!({"gn":game.id,"sel":p.sel,"sid":seed+index as u64+1,
            "cps":p.cps,"atb":atb_for_step(p.atb, p.reset_atb, index),"dn":p.dn});
        if let Some(position) = p.position_for_step(index) {
            request["pos"] = json!(position);
        }
        let reply = call(
            ctx,
            if index == 0 {
                mode.kind.operation()
            } else {
                "continuation"
            },
            "/kaga/command/spin",
            &user,
            &context,
            &request,
            true,
        )
        .await?;
        steps.push((request, reply));
        if validate_chain(before, &p, &steps)?.native_closed {
            break;
        }
    }
    reconcile(before, &p, &steps)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn space_pick_closes_with_native_bonus_award() {
        let trace: Value = serde_json::from_str(include_str!(
            "../../../demo-dashboard/kagaming/batches/101-200/traces/Space-normal.json"
        ))
        .unwrap();
        let steps = trace["steps"].as_array().unwrap();
        let first = &steps[0]["response"]["md"];
        let last = &steps[1]["response"]["md"];
        assert!(space_pick_pending(first).unwrap());
        assert!(!space_pick_pending(last).unwrap());
        assert_eq!(
            space_pick_award(first, last, &steps[1]["request"], &steps[1]["response"]).unwrap(),
            Decimal::from(103)
        );
        let mut wrong = steps[1]["response"].clone();
        wrong["p"] = json!(1);
        assert!(space_pick_award(first, last, &steps[1]["request"], &wrong).is_err());
        let init: Value = serde_json::from_str(include_str!(
            "../../../demo-dashboard/kagaming/batches/101-200/initializations/Space.json"
        ))
        .unwrap();
        let profile = profile(&init, "Space", &BINDINGS["Space"]["normal"]).unwrap();
        let before = amount(&init["bl"]).unwrap();
        let recorded: Vec<_> = steps
            .iter()
            .map(|s| (s["request"].clone(), s["response"].clone()))
            .collect();
        assert!(reconcile(before, &profile, &recorded[..1]).is_err());
        let outcome = reconcile(before, &profile, &recorded).unwrap();
        assert_eq!(outcome.payout, "328");
        assert_eq!(outcome.balance_after, "10000228");
    }
    #[test]
    fn atb_purchase_resets_the_selector_only_for_continuations() {
        assert_eq!(atb_for_step(3, true, 0), 3);
        assert_eq!(atb_for_step(3, true, 1), 0);
        assert_eq!(atb_for_step(3, false, 1), 3);
    }
    const INIT: &str = include_str!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../demo-dashboard/kagaming/batches/1-100/initializations/BonusMania.json"
    ));
    const TRACE: &str = include_str!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../demo-dashboard/kagaming/batches/1-100/traces/BonusMania-normal.json"
    ));
    #[test]
    fn published_signature_vector_uses_exact_bytes_and_utf16() {
        assert_eq!(hash31("😀"), 1772899);
        let ctx = json!({"idv":"device-new","dv":"1.2.3","av":"1.0.268 (2090)"});
        let signed = signed_context("{\"gn\":\"Unit\",\"sid\":7}", &ctx, 1793240000000).unwrap();
        assert_eq!(
            signed["ida"],
            "4a417018a7c9867e7fc2354b739a544b4df91c23b732f2ca9c153309587d9b861793240000000"
        );
        assert_ne!(
            signed["ida"],
            signed_context("{\"gn\": \"Unit\",\"sid\":7}", &ctx, 1793240000000).unwrap()["ida"]
        );
        assert!(ctx.get("ida").is_none());
    }
    #[test]
    fn native_offer_and_captured_normal_reconcile_without_balance_derived_win() {
        let init: Value = serde_json::from_str(INIT).unwrap();
        let b = &BINDINGS["BonusMania"]["normal"];
        assert_eq!(b.source_sha256, GAME_HASH);
        let p = profile(&init, "BonusMania", b).unwrap();
        assert_eq!((p.sel, p.cps, p.cost), (1, 5, Decimal::from(15)));
        let trace: Value = serde_json::from_str(TRACE).unwrap();
        let steps = vec![(
            trace["steps"][0]["request"].clone(),
            trace["steps"][0]["response"].clone(),
        )];
        let mut out = reconcile(Decimal::from(10_000_000), &p, &steps).unwrap();
        assert!(out.verify().unwrap());
        assert_eq!(out.payout, "0");
        assert_eq!(out.balance_after, "9999985");
        let mut bad = steps.clone();
        bad[0].1["cr"] = json!(9999984);
        assert!(reconcile(Decimal::from(10_000_000), &p, &bad).is_err());
        let mut bad = steps.clone();
        bad[0].1["sid"] = json!(1);
        assert!(reconcile(Decimal::from(10_000_000), &p, &bad).is_err());
        let mut bad = steps.clone();
        bad[0].1["md"]["sid"] = json!("invalid");
        assert!(reconcile(Decimal::from(10_000_000), &p, &bad).is_err());
        let mut bad = steps.clone();
        bad[0].1["md"]["cr"] = json!("EUR");
        assert!(reconcile(Decimal::from(10_000_000), &p, &bad).is_err());
        let mut stale = init.clone();
        stale["ase"] = json!([2]);
        assert!(profile(&stale, "BonusMania", b).is_err());
    }
    #[test]
    fn continuation_stops_at_terminal_and_rejects_unknown_choices() {
        assert!(!remaining(&json!({"fsr":0,"rf":0})).unwrap());
        assert!(remaining(&json!({"fsr":2,"rf":0})).unwrap());
        assert!(remaining(&json!({"fsr":0,"rf":1})).is_err());
        assert!(remaining(&json!({"fsr":0,"rf":0,"bpd":{"choices":[1,2]}})).is_err());
        assert!(remaining(&json!({"fsr":-1,"rf":0})).is_err());
    }
}
