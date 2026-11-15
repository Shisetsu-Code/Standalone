use crate::{
    context::RunContext,
    model::{Game, Mode, ModeKind, RoundOutcome, decimal, exact_add, exact_mul, wallet_matches},
};
use anyhow::{Context, Result, bail, ensure};
use rust_decimal::Decimal;
use serde::Deserialize;
use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::OnceLock};
use time::{OffsetDateTime, format_description::well_known::Rfc3339};
use uuid::Uuid;

const INIT: &str = "https://rgs-ld-demo.spinomenal.com/api/InitClientUrl";
const CORE: &str = "https://rgs-ld-demo-core.spinomenal.com/api";
const ORIGIN: &str = "https://cdn-live.spinomenal.com";
const CLIENT_UA: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) hardfire/1.5.1 Chrome/152.0.7977.130 Electron/44.5.1 Safari/537.36";

fn archived_init(game: &str) -> Option<&'static Value> {
    static PUBLIC_INIT: OnceLock<BTreeMap<String, Value>> = OnceLock::new();
    PUBLIC_INIT
        .get_or_init(|| {
            serde_json::from_slice(include_bytes!("../../bindings/spinomenal-public-init.json"))
                .expect("compiled Spinomenal public configuration")
        })
        .get(game)
}

fn demo_suffix() -> String {
    const ALPHABET: &[u8; 62] = b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
    let mut suffix = String::with_capacity(50);
    while suffix.len() < 50 {
        let uuid = Uuid::new_v4();
        for (index, &value) in uuid.as_bytes().iter().enumerate() {
            if !matches!(index, 6 | 8) && value < 248 && suffix.len() < 50 {
                suffix.push(ALPHABET[value as usize % ALPHABET.len()] as char);
            }
        }
    }
    suffix
}

#[derive(Deserialize)]
struct Picker {
    choice: u64,
    ticket_bound: bool,
}

impl Picker {
    fn count(&self, start: &Value) -> Result<u64> {
        let mut options = start["FreeSpinsPickerObject"]
            .as_array()
            .context("Spinomenal picker menu missing")?
            .iter()
            .filter(|option| option["FreeSpinsType"] == self.choice);
        let count = options
            .next()
            .and_then(|option| option["FreeSpinsAmount"].as_u64())
            .filter(|&count| count > 0)
            .context("Spinomenal picker branch unavailable")?;
        ensure!(
            options.next().is_none(),
            "ambiguous Spinomenal picker branch"
        );
        Ok(count)
    }

    fn request(&self, start: &Value, round: &Value, common: &Value) -> Result<(Value, u64)> {
        let count = self.count(start)?;
        let mut payload = common.clone();
        payload["FreeSpinsType"] = json!(self.choice);
        payload["Action"] = if self.ticket_bound {
            Value::Null
        } else {
            json!("Spin")
        };
        payload["RequestBalance"] = json!(false);
        if self.ticket_bound {
            payload["ticketId"] = json!(
                round["UniqueIdentifier"]
                    .as_u64()
                    .context("Spinomenal picker ticket missing")?
            );
        }
        Ok((payload, count))
    }
}

#[cfg(test)]
mod picker_tests {
    use super::*;

    #[test]
    fn antebet_quotes_the_native_multiplier_instead_of_a_percentage() {
        let settings = json!({"ToggleFeature":"WILD BET","SpecialBetMultiplier":100});
        let base = json!({"bet":"0.01","lines":5});
        let (_, payload, price, _) =
            action(&Value::Null, &settings, &base, &Binding::Antebet).unwrap();
        assert_eq!(price, decimal("5.00").unwrap());
        assert_eq!(payload["isToggleFeatureOn"], true);
    }

    #[test]
    fn native_picker_uses_the_offered_branch_and_ticket() {
        assert!(
            crate::context::validate_target("spinomenal", &format!("{CORE}/PickFreeSpins")).is_ok()
        );
        let picker = Picker {
            choice: 2,
            ticket_bound: true,
        };
        let start = json!({"FreeSpinsPickerObject":[{"FreeSpinsType":2,"FreeSpinsAmount":10}]});
        let (payload, count) = picker
            .request(&start, &json!({"UniqueIdentifier":17}), &json!({}))
            .unwrap();
        assert_eq!(count, 10);
        assert_eq!(
            payload,
            json!({"FreeSpinsType":2,"Action":null,"RequestBalance":false,"ticketId":17})
        );
        assert!(picker.request(&start, &json!({}), &json!({})).is_err());
        assert!(
            picker
                .request(&json!({}), &json!({"UniqueIdentifier":17}), &json!({}))
                .is_err()
        );
    }
}

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "lowercase")]
enum Binding {
    Normal,
    Antebet,
    Purchase {
        factor: String,
        #[serde(rename = "type")]
        kind: Value,
        spin_type: Value,
        count: Option<u64>,
        #[serde(rename = "default")]
        default_selector: bool,
        granted: Option<u64>,
        picker: Option<Picker>,
    },
    Bonus {
        factor: String,
        #[serde(rename = "type")]
        kind: Value,
    },
}

fn binding(game: &Game, mode: &Mode) -> Option<&'static Binding> {
    static MODES: OnceLock<BTreeMap<String, BTreeMap<String, Binding>>> = OnceLock::new();
    let binding = MODES
        .get_or_init(|| {
            serde_json::from_slice(include_bytes!("../../bindings/spinomenal.json"))
                .expect("valid embedded Spinomenal bindings")
        })
        .get(&game.id)?
        .get(&mode.key)?;
    match (mode.kind, binding) {
        (ModeKind::Normal, Binding::Normal)
        | (ModeKind::AnteBet, Binding::Antebet)
        | (ModeKind::Purchase, Binding::Purchase { .. } | Binding::Bonus { .. }) => Some(binding),
        _ => None,
    }
}

pub fn supports(game: &Game, mode: &Mode) -> bool {
    matches!(
        mode.requires_prerequisites,
        Value::Null | Value::Bool(false)
    ) && binding(game, mode).is_some()
}

fn money(value: &Value) -> Result<Decimal> {
    match value {
        Value::String(s) => decimal(s),
        Value::Number(n) => decimal(&n.to_string()),
        _ => bail!("missing Spinomenal monetary field"),
    }
}

fn optional_amount(value: &Value) -> Result<Decimal> {
    if value.is_null() {
        Ok(Decimal::ZERO)
    } else {
        money(value)
    }
}

fn positive(value: &Value) -> Result<Decimal> {
    let amount = money(value)?;
    ensure!(amount > Decimal::ZERO, "invalid Spinomenal offer amount");
    Ok(amount)
}

fn menu<'a>(start: &'a Value, init: &'a Value, key: &str) -> &'a [Value] {
    start[key]
        .as_array()
        .filter(|rows| !rows.is_empty())
        .or_else(|| init["GameInfo"][key].as_array())
        .map(Vec::as_slice)
        .unwrap_or_default()
}

fn offered(
    init: &Value,
    start: &Value,
    key: &str,
    expected: Decimal,
    matches: impl Fn(&Value) -> bool,
) -> Result<()> {
    let mut offers = menu(start, init, key)
        .iter()
        .filter(|v| matches(v) && money(&v["BuyFeatureCost"]).is_ok_and(|v| v == expected));
    ensure!(
        offers.next().is_some() && offers.next().is_none(),
        "Spinomenal native offer changed or is ambiguous"
    );
    Ok(())
}

fn action(
    init: &Value,
    start: &Value,
    base: &Value,
    mode: &Binding,
) -> Result<(&'static str, Value, Decimal, Option<u64>)> {
    let mut payload = base.clone();
    let (endpoint, factor, granted) = match mode {
        Binding::Normal => ("ProcessSlotMachine", Decimal::ONE, None),
        Binding::Antebet => {
            ensure!(
                start["ToggleFeature"]
                    .as_str()
                    .is_some_and(|s| !s.is_empty()),
                "Spinomenal antebet not offered"
            );
            payload["isToggleFeatureOn"] = json!(true);
            (
                "ProcessSlotMachine",
                positive(&start["SpecialBetMultiplier"])?,
                None,
            )
        }
        Binding::Purchase {
            factor,
            kind,
            spin_type,
            count,
            default_selector,
            granted,
            ..
        } => {
            ensure!(
                start["IsBuyFeatureEnabled"] == true
                    && menu(start, init, "BuyBonusOptions").is_empty(),
                "Spinomenal purchase unavailable"
            );
            let factor = decimal(factor)?;
            if *default_selector {
                ensure!(
                    menu(start, init, "BuyFeatures").is_empty()
                        && positive(&start["BuyFeatureCost"])
                            .or_else(|_| positive(&init["GameInfo"]["BuyFeatureCost"]))?
                            == factor,
                    "Spinomenal default purchase changed"
                );
            } else {
                offered(init, start, "BuyFeatures", factor, |offer| {
                    let amount = offer["FreeSpinAmount"]
                        .as_u64()
                        .or_else(|| offer["FreeSpinAmount"].as_str()?.parse().ok());
                    amount == *count
                        && offer["FreeSpinType"] == *spin_type
                        && offer["BuyFeatureType"].as_u64().unwrap_or_default()
                            == kind.as_u64().unwrap_or_default()
                })?;
                let layout = init["GameInfo"]["BuyFeatureLayouts"]["LayoutType"].as_u64();
                if matches!(layout, Some(1 | 4)) {
                    let fixed = optional_amount(&start["BuyFeatureCost"])?;
                    let first = menu(start, init, "BuyFeatures")
                        .first()
                        .context("missing Spinomenal fixed offer")?;
                    ensure!(
                        if start["BuyFeatureCost"].is_null() {
                            money(&first["BuyFeatureCost"])? == factor
                        } else {
                            fixed == factor
                        },
                        "Spinomenal fixed purchase changed"
                    );
                }
                payload["freeSpinType"] = spin_type.clone();
                payload["freeSpinAmount"] =
                    json!(count.context("missing Spinomenal feature count")?);
            }
            payload["buyFeatureType"] = kind.clone();
            ("BuyFeature", factor, *granted)
        }
        Binding::Bonus { factor, kind } => {
            ensure!(
                start["IsBuyFeatureEnabled"] == true,
                "Spinomenal bonus purchase unavailable"
            );
            let factor = decimal(factor)?;
            offered(init, start, "BuyBonusOptions", factor, |offer| {
                offer["BonusType"] == *kind
            })?;
            payload["BuyFeatureBonusType"] = kind.clone();
            ("ProcessSlotMachine", factor, None)
        }
    };
    ensure!(factor > Decimal::ZERO, "invalid Spinomenal price factor");
    if endpoint == "BuyFeature" {
        for key in ["isToggleFeatureOn", "featureBoosterType", "turboMode"] {
            payload
                .as_object_mut()
                .context("invalid Spinomenal payload")?
                .remove(key);
        }
    }
    let price = exact_mul(
        exact_mul(positive(&base["bet"])?, positive(&base["lines"])?)?,
        factor,
    )?;
    Ok((endpoint, payload, price, granted))
}

async fn post(ctx: &RunContext, endpoint: &str, payload: &Value, financial: bool) -> Result<Value> {
    let url = if endpoint == "InitClientUrl" {
        INIT.into()
    } else {
        format!("{CORE}/{endpoint}")
    };
    let mut payload = payload.clone();
    if endpoint == "ProcessSlotMachine" {
        payload["timestamp"] = json!(OffsetDateTime::now_utc().format(&Rfc3339)?);
    }
    tokio::time::sleep(std::time::Duration::from_secs(1)).await;
    let message = ctx
        .json(
            endpoint,
            &url,
            &payload,
            BTreeMap::from([
                (
                    "accept".into(),
                    "application/json, text/javascript, */*; q=0.01".into(),
                ),
                ("accept-language".into(), "es".into()),
                (
                    "content-type".into(),
                    "application/json; charset=UTF-8".into(),
                ),
                ("origin".into(), ORIGIN.into()),
                ("referer".into(), format!("{ORIGIN}/")),
                ("user-agent".into(), CLIENT_UA.into()),
            ]),
            financial,
        )
        .await?;
    ensure!(
        message["ResultInfo"]["Code"] == 0 && message["Result"].is_object(),
        "Spinomenal rejected {endpoint}"
    );
    Ok(message["Result"].clone())
}

fn verify_route(init: &Value, key: &str, endpoint: &str) -> Result<()> {
    ensure!(
        init["Urls"][key] == format!("{CORE}/{endpoint}"),
        "Spinomenal {key} changed"
    );
    Ok(())
}

fn pending_collect(result: &Value) -> bool {
    fn pending(item: &Value) -> bool {
        item["PendingAction"] == true || item["PrizeObject"]["PendingAction"] == true
    }
    match &result["CollectInfo"] {
        Value::Array(items) => items.iter().any(pending),
        item => pending(item),
    }
}

fn minimum_setting(start: &Value, menu: &str, default: &str) -> Result<Value> {
    let default = &start[default];
    positive(default)?;
    let mut smallest = None;
    if let Some(options) = start[menu].as_array() {
        for option in options {
            let amount = positive(option)?;
            if smallest.is_none_or(|(previous, _)| amount < previous) {
                smallest = Some((amount, option));
            }
        }
    }
    Ok(smallest.map_or(default, |(_, value)| value).clone())
}

pub async fn execute(ctx: &RunContext, game: &Game, mode: &Mode) -> Result<RoundOutcome> {
    let mode_binding = binding(game, mode).context("unreviewed Spinomenal mode")?;
    let init = if cfg!(all(windows, feature = "spinomenal-bundled-http"))
        && let Some(config) = archived_init(&game.id)
    {
        config.clone()
    } else {
        post(
        ctx,
        "InitClientUrl",
        &json!({
            "gameCode":game.id,"gameToken":"AFF-DEMO","partnerId":"SPIN-AFF","langCode":"en_US",
            "FromLobby":null,"extComLabel":null,"kremboComLabel":null,"alternativeGameCode":null,
            "IsNativeIos":null,"NativeAppHostUrl":null,"Debug":null
        }),
        false,
    )
        .await?
    };
    verify_route(&init, "StartUrl", "StartSlotMachine")?;
    verify_route(&init, "ProcessUrl", "ProcessSlotMachine")?;
    let suffix = demo_suffix();
    let start = post(ctx, "StartSlotMachine", &json!({
        "gameCode":game.id,"gameToken":format!("AFF-DEMO_{suffix}"),"playerId":0,
        "langCode":"en_US","partnerId":"SPIN-AFF","originalLangCode":"en_US","platformId":1,"subPlatformId":0
    }), false).await?;
    ensure!(
        start["DemoMode"] == 1 && start["IsLastRoundFinished"] == true,
        "fresh Spinomenal demo did not start idle"
    );
    let token = start["Token"]
        .as_str()
        .filter(|s| !s.is_empty())
        .context("Spinomenal demo token missing")?;
    let class = start["ClassId"]
        .as_u64()
        .context("Spinomenal game class missing")?;
    let currency = start["CurrencyCode"].as_str().unwrap_or_default();
    let denomination_menu = if matches!(
        mode_binding,
        Binding::Purchase { .. } | Binding::Bonus { .. }
    ) && start["BuyFeatureDenominations"]
        .as_array()
        .is_some_and(|items| !items.is_empty())
    {
        "BuyFeatureDenominations"
    } else {
        "BettingUnits"
    };
    let lines = minimum_setting(&start, "LinesOptions", "DefaultLines")?;
    let bet = minimum_setting(&start, denomination_menu, "DefaultBetUnit")?;
    let common = json!({
        "gameCode":game.id,"gameToken":token,"classId":class,"langCode":"en_us","partnerId":"SPIN-AFF","originalLangCode":"en_us",
        "EnvironmentRuntime":30,"fastPlay":false,"autoPlay":false,"forceTicket":0,"CurrencyCode":currency,"platformId":1,"subPlatformId":0
    });
    let mut base = common.clone();
    base["lines"] = lines;
    base["bet"] = bet;
    base["isToggleFeatureOn"] = json!(false);
    base["featureBoosterType"] = Value::Null;
    base["turboMode"] = json!("single_off");
    let (first, entry, cost, granted) = action(&init, &start, &base, mode_binding)?;
    let picker = match mode_binding {
        Binding::Purchase { picker, .. } => picker.as_ref(),
        _ => None,
    };
    if let Some(picker) = picker {
        picker.count(&start)?;
        verify_route(&init, "PickFreeSpinsUrl", "PickFreeSpins")?;
    }
    if first == "BuyFeature" {
        verify_route(&init, "BuyFeatureUrl", "BuyFeature")?;
    }
    let before = money(&start["Coins"])?;
    ensure!(before >= cost, "insufficient fictional Spinomenal coins");
    ctx.save_session(&json!({"game":game.id,"session":common}))?;
    let mut result = post(ctx, first, &entry, true).await?;
    let mut free = result["FreeTickets"].clone();
    let charged = if first == "BuyFeature" {
        let count = free["To"]
            .as_u64()
            .filter(|n| *n > 0)
            .context("Spinomenal did not grant purchased spins")?;
        if matches!(
            mode_binding,
            Binding::Purchase {
                default_selector: false,
                ..
            }
        ) {
            ensure!(
                granted == Some(count),
                "Spinomenal purchased spin count changed"
            );
        }
        money(&free["PurchasePrice"])?
    } else {
        money(&result["TotalBetPlaced"])?
    };
    ensure!(
        charged == cost,
        "Spinomenal native charge differs from offer"
    );
    let mut payout = optional_amount(&result["Win"])?;
    let mut balance = money(&result["CoinOut"])?;
    ensure!(
        payout >= Decimal::ZERO && wallet_matches(before, balance, cost, payout),
        "Spinomenal entry wallet differs"
    );
    let mut steps = 1;
    let mut picked = false;
    loop {
        if free["PendingAction"] == true {
            let picker = picker.context("Spinomenal continuation requires a reviewed choice")?;
            ensure!(
                !picked && steps < ctx.max_steps(),
                "unexpected Spinomenal picker phase"
            );
            ensure!(
                free["Gamble"].is_null() || free["Gamble"]["Ended"] == true,
                "Spinomenal has another pending control before the picker"
            );
            let (request, count) = picker.request(&start, &result, &common)?;
            let selection = post(ctx, "PickFreeSpins", &request, true).await?;
            ensure!(
                selection["Type"] == picker.choice
                    && selection["To"] == count
                    && selection["PendingAction"] == false
                    && money(&selection["PurchasePrice"])? == cost,
                "Spinomenal picker receipt differs from the selected offer"
            );
            free = selection;
            picked = true;
            steps += 1;
            continue;
        }
        ensure!(
            free["PendingAction"] != true
                && result["PendingEnd"] != true
                && !pending_collect(&result)
                && (result["MiniGame"]["Units"].is_null() || result["IsRoundFinished"] == true),
            "Spinomenal continuation requires a reviewed choice"
        );
        let remaining = free["To"]
            .as_u64()
            .context("Spinomenal free-spin count missing")?;
        if !free["Gamble"].is_null() && free["Gamble"]["Ended"] != true {
            ensure!(
                steps < ctx.max_steps(),
                "Spinomenal continuation limit reached"
            );
            verify_route(&init, "FreeSpinsGambleUrl", "Gamble")?;
            let mut decline = common.clone();
            decline["isGamble"] = json!(false);
            free = post(ctx, "Gamble", &decline, true).await?;
            ensure!(
                free["To"].as_u64() == Some(remaining)
                    && (free["Gamble"].is_null() || free["Gamble"]["Ended"] == true),
                "Spinomenal gamble decline did not preserve the free spins"
            );
            steps += 1;
            continue;
        }
        if remaining == 0 {
            ensure!(
                result["IsRoundFinished"] == true && (picker.is_none() || picked),
                "Spinomenal native closure absent"
            );
            break;
        }
        ensure!(
            steps < ctx.max_steps(),
            "Spinomenal continuation limit reached"
        );
        // Ante is an entry modifier. Continue with the exact same flag used by the native client.
        let mut pending = base.clone();
        pending["isToggleFeatureOn"] = json!(matches!(mode_binding, Binding::Antebet));
        result = post(ctx, "ProcessSlotMachine", &pending, true).await?;
        let previous = balance;
        balance = money(&result["CoinOut"])?;
        let award = money(&result["Win"])?;
        ensure!(
            award >= Decimal::ZERO
                && money(&result["TotalBetPlaced"])? == Decimal::ZERO
                && wallet_matches(previous, balance, Decimal::ZERO, award),
            "Spinomenal continuation wallet differs"
        );
        payout = exact_add(payout, award)?;
        free = result["FreeTickets"].clone();
        steps += 1;
    }
    let ticket = result["UniqueIdentifier"]
        .as_u64()
        .filter(|n| *n != 0)
        .map(|n| n.to_string());
    Ok(RoundOutcome {
        native_round_id: ticket,
        currency: if currency.is_empty() {
            "DEMO_COINS".into()
        } else {
            currency.into()
        },
        currency_source: if currency.is_empty() {
            "public_binding".into()
        } else {
            "native_response".into()
        },
        monetary_unit: "native".into(),
        balance_before: before.to_string(),
        balance_after: balance.to_string(),
        cost: cost.to_string(),
        payout: payout.to_string(),
        native_closed: true,
        checks: BTreeMap::from([
            ("demo_mode".into(), true),
            ("native_quote".into(), true),
            ("phase_wallet".into(), true),
        ]),
        native_data: json!({"steps":steps,"mode":mode.key,"picked_free_spin_type":
            picker.filter(|_| picked).map(|picker| picker.choice)}),
    })
}
