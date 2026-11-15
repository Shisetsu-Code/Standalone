use anyhow::{Context, Result, ensure};
use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    time::{SystemTime, UNIX_EPOCH},
};

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ModeKind {
    #[serde(alias = "bet", alias = "spin")]
    Normal,
    #[serde(alias = "buy", alias = "buy_bonus")]
    Purchase,
    #[serde(rename = "antebet", alias = "ante_bet")]
    AnteBet,
    #[serde(alias = "activator")]
    Booster,
    Variant,
    Special,
}
impl ModeKind {
    pub fn operation(self) -> &'static str {
        match self {
            Self::Normal => "bet",
            Self::AnteBet => "ante_bet",
            Self::Purchase => "buy_bonus",
            _ => self.as_str(),
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Normal => "normal",
            Self::Purchase => "purchase",
            Self::AnteBet => "antebet",
            Self::Booster => "booster",
            Self::Variant => "variant",
            Self::Special => "special",
        }
    }
}
fn yes() -> bool {
    true
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Mode {
    pub key: String,
    #[serde(rename = "type")]
    pub kind: ModeKind,
    pub label: String,
    #[serde(default = "yes")]
    pub ready: bool,
    #[serde(default)]
    pub requires_prerequisites: Value,
    #[serde(default)]
    pub execution_source: Option<String>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Game {
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub ready: bool,
    #[serde(default)]
    pub block_reason: String,
    pub modes: Vec<Mode>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProviderInventory {
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub ready: bool,
    #[serde(default)]
    pub campaign_eligible: bool,
    #[serde(default)]
    pub protocol: Value,
    pub games: Vec<Game>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InventorySource {
    pub provider: String,
    pub path: String,
    pub actual_sha256: String,
    pub declared_sha256: String,
    pub hash_representation: String,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InventorySnapshot {
    pub id: String,
    pub providers: Vec<ProviderInventory>,
    pub sources: Vec<InventorySource>,
}
impl InventorySnapshot {
    pub fn lookup(
        &self,
        provider: &str,
        game: &str,
        mode: &str,
    ) -> Result<(&ProviderInventory, &Game, &Mode)> {
        let p = self
            .providers
            .iter()
            .find(|p| p.id == provider)
            .context("provider absent from pinned inventory")?;
        let g = p
            .games
            .iter()
            .find(|g| g.id == game)
            .context("game absent from pinned inventory")?;
        let m = g
            .modes
            .iter()
            .find(|m| m.key == mode)
            .context("mode absent from pinned inventory")?;
        Ok((p, g, m))
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Job {
    pub provider: String,
    pub game: String,
    pub mode: String,
    #[serde(default = "one")]
    pub samples: u32,
    #[serde(default)]
    pub settings: Value,
}
fn one() -> u32 {
    1
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CampaignPlan {
    pub schema_version: u32,
    pub id: String,
    pub inventory_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub coverage: Option<Value>,
    pub jobs: Vec<Job>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RoundSpec {
    pub campaign_id: String,
    pub inventory_id: String,
    pub job_index: u32,
    pub sample_index: u32,
    pub provider: String,
    pub game: String,
    pub mode: String,
    pub kind: ModeKind,
    pub settings: Value,
}
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum RoundStatus {
    Prepared,
    InFlight,
    Open,
    Verified,
    ValidationFailed,
    Uncertain,
    Blocked,
}
impl RoundStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Prepared => "prepared",
            Self::InFlight => "in_flight",
            Self::Open => "open",
            Self::Verified => "verified",
            Self::ValidationFailed => "validation_failed",
            Self::Uncertain => "uncertain",
            Self::Blocked => "blocked",
        }
    }
    pub fn terminal(self) -> bool {
        matches!(
            self,
            Self::Verified | Self::ValidationFailed | Self::Blocked
        )
    }
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RoundRecord {
    pub id: String,
    pub spec: RoundSpec,
    pub status: RoundStatus,
    pub created_at: u64,
    pub updated_at: u64,
    pub reason: Option<String>,
    pub outcome: Option<RoundOutcome>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WireRequest {
    pub label: String,
    pub transport: String,
    pub method: String,
    pub url: String,
    pub headers: BTreeMap<String, String>,
    pub body: String,
    pub financial: bool,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WireResponse {
    pub status: u16,
    pub headers: BTreeMap<String, String>,
    pub body: String,
    /// Individual values cannot be comma-joined (Expires itself contains commas).
    /// Omit an absent list to preserve hashes of older serialized responses.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub set_cookies: Vec<String>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExchangeRecord {
    pub ordinal: u64,
    pub request: WireRequest,
    pub response: Option<WireResponse>,
    pub error: Option<String>,
    pub request_sha256: String,
    pub response_sha256: Option<String>,
    #[serde(default)]
    pub frames: Vec<WireFrame>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WireFrame {
    pub sequence: u64,
    pub kind: String,
    pub body: String,
    pub recorded_at: u64,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RoundOutcome {
    pub native_round_id: Option<String>,
    pub currency: String,
    #[serde(default)]
    pub monetary_unit: String,
    #[serde(default)]
    pub currency_source: String,
    pub balance_before: String,
    pub balance_after: String,
    pub cost: String,
    pub payout: String,
    pub native_closed: bool,
    pub checks: BTreeMap<String, bool>,
    pub native_data: Value,
}
impl RoundOutcome {
    pub fn verify(&mut self) -> Result<bool> {
        let before = decimal(&self.balance_before)?;
        let after = decimal(&self.balance_after)?;
        let cost = decimal(&self.cost)?;
        let payout = decimal(&self.payout)?;
        self.checks
            .insert("native_closed".into(), self.native_closed);
        self.checks.insert(
            "wallet_ledger".into(),
            wallet_matches(before, after, cost, payout),
        );
        self.checks
            .insert("positive_native_cost".into(), cost > Decimal::ZERO);
        ensure!(!self.currency.trim().is_empty(), "currency missing");
        ensure!(
            matches!(self.monetary_unit.as_str(), "native" | "major"),
            "invalid monetary unit"
        );
        ensure!(
            matches!(
                self.currency_source.as_str(),
                "native_response" | "launcher_parameter" | "public_binding"
            ),
            "invalid currency source"
        );
        Ok(self.checks.values().all(|v| *v))
    }
}
pub fn currency_binding(native: Option<&str>, expected: &str) -> Result<&'static str> {
    ensure!(
        !expected.trim().is_empty(),
        "expected public demo currency missing"
    );
    if let Some(native) = native {
        ensure!(
            native == expected,
            "native currency contradicts public binding"
        );
        Ok("native_response")
    } else {
        Ok("public_binding")
    }
}
pub fn decimal(value: &str) -> Result<Decimal> {
    let value = if let Some((mantissa, exponent)) = value.split_once(['e', 'E']) {
        // Parse the mantissa exactly first: `from_scientific` itself uses a lossy parser.
        Decimal::from_str_exact(mantissa).context("invalid exact scientific mantissa")?;
        let shift: i32 = exponent.parse().context("invalid scientific exponent")?;
        ensure!(
            (-128..=128).contains(&shift),
            "scientific exponent outside supported exact range"
        );
        let (sign, unsigned) = if let Some(v) = mantissa.strip_prefix('-') {
            ("-", v)
        } else if let Some(v) = mantissa.strip_prefix('+') {
            ("", v)
        } else {
            ("", mantissa)
        };
        let unsigned = unsigned.replace('_', "");
        let (integer, fraction) = unsigned.split_once('.').unwrap_or((&unsigned, ""));
        let digits = format!("{integer}{fraction}");
        let point = integer.len() as i32 + shift;
        let expanded = if point <= 0 {
            format!("{sign}0.{}{digits}", "0".repeat((-point) as usize))
        } else if point as usize >= digits.len() {
            format!(
                "{sign}{digits}{}",
                "0".repeat(point as usize - digits.len())
            )
        } else {
            format!(
                "{sign}{}.{}",
                &digits[..point as usize],
                &digits[point as usize..]
            )
        };
        Decimal::from_str_exact(&expanded)
            .context("scientific amount cannot be represented exactly")?
    } else {
        Decimal::from_str_exact(value).context("invalid or inexact decimal amount")?
    };
    ensure!(value >= Decimal::ZERO, "negative native money amount");
    Ok(value)
}
fn scaled_mantissa(value: Decimal, scale: u32) -> Option<i128> {
    let factor = 10i128.checked_pow(scale.checked_sub(value.scale())?)?;
    value.mantissa().checked_mul(factor)
}
fn exact_from_parts(mut mantissa: i128, mut scale: u32) -> Result<Decimal> {
    // Remove only zero fractional digits when the Decimal representation requires it.
    while scale > 28 && mantissa % 10 == 0 {
        mantissa /= 10;
        scale -= 1;
    }
    loop {
        match Decimal::try_from_i128_with_scale(mantissa, scale) {
            Ok(value) => return Ok(value),
            Err(_) if scale > 0 && mantissa % 10 == 0 => {
                mantissa /= 10;
                scale -= 1;
            }
            Err(error) => return Err(error).context("exact decimal result not representable"),
        }
    }
}
pub fn exact_add(a: Decimal, b: Decimal) -> Result<Decimal> {
    let scale = a.scale().max(b.scale());
    let x = scaled_mantissa(a, scale).context("exact addition overflow")?;
    let y = scaled_mantissa(b, scale).context("exact addition overflow")?;
    exact_from_parts(x.checked_add(y).context("exact addition overflow")?, scale)
}
pub fn exact_sub(a: Decimal, b: Decimal) -> Result<Decimal> {
    let scale = a.scale().max(b.scale());
    let x = scaled_mantissa(a, scale).context("exact subtraction overflow")?;
    let y = scaled_mantissa(b, scale).context("exact subtraction overflow")?;
    exact_from_parts(
        x.checked_sub(y).context("exact subtraction overflow")?,
        scale,
    )
}
pub fn exact_mul(a: Decimal, b: Decimal) -> Result<Decimal> {
    let n = a
        .mantissa()
        .checked_mul(b.mantissa())
        .context("exact multiplication overflow")?;
    exact_from_parts(n, a.scale() + b.scale())
}
pub fn exact_div100(value: Decimal) -> Result<Decimal> {
    exact_from_parts(value.mantissa(), value.scale() + 2)
}
pub fn wallet_matches(before: Decimal, after: Decimal, cost: Decimal, payout: Decimal) -> bool {
    let scale = [before.scale(), after.scale(), cost.scale(), payout.scale()]
        .into_iter()
        .max()
        .unwrap_or(0);
    let result = || -> Option<bool> {
        let expected = scaled_mantissa(before, scale)?
            .checked_sub(scaled_mantissa(cost, scale)?)?
            .checked_add(scaled_mantissa(payout, scale)?)?;
        Some(expected == scaled_mantissa(after, scale)?)
    };
    result().unwrap_or(false)
}
pub fn canonical_provider(provider: &str) -> &str {
    if provider == "reelkingdom" {
        "pragmatic"
    } else {
        provider
    }
}
pub fn sha256(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
pub fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn legacy_plan_serialization_omits_absent_coverage() {
        let legacy = r#"{"schema_version":1,"id":"old","inventory_id":"inventory","jobs":[]}"#;
        let plan: CampaignPlan = serde_json::from_str(legacy).unwrap();
        assert!(plan.coverage.is_none());
        assert_eq!(serde_json::to_string(&plan).unwrap(), legacy);
    }
    #[test]
    fn outcome_rejects_unknown_money_units_or_currency_source() {
        let mut outcome = RoundOutcome {
            native_round_id: None,
            currency: "EUR".into(),
            monetary_unit: "native".into(),
            currency_source: "native_response".into(),
            balance_before: "10".into(),
            balance_after: "9".into(),
            cost: "1".into(),
            payout: "0".into(),
            native_closed: true,
            checks: BTreeMap::new(),
            native_data: Value::Null,
        };
        assert!(outcome.verify().unwrap());
        outcome.monetary_unit = "".into();
        assert!(outcome.verify().is_err());
        outcome.monetary_unit = "major".into();
        outcome.currency_source = "assumed".into();
        assert!(outcome.verify().is_err());
        outcome.currency_source = "launcher_parameter".into();
        assert!(outcome.verify().unwrap());
    }
    #[test]
    fn aliases_share_one_provider_lock_identity() {
        assert_eq!(canonical_provider("reelkingdom"), "pragmatic");
    }
    #[test]
    fn exact_decimal_ledger_and_mismatch() {
        assert!(wallet_matches(
            decimal("10.00").unwrap(),
            decimal("9.90").unwrap(),
            decimal("0.30").unwrap(),
            decimal("0.20").unwrap()
        ));
        assert!(!wallet_matches(
            decimal("10").unwrap(),
            decimal("9.91").unwrap(),
            decimal("0.3").unwrap(),
            decimal("0.2").unwrap()
        ));
    }
    #[test]
    fn ledger_does_not_round_away_tiny_payout() {
        assert!(!wallet_matches(
            decimal("10").unwrap(),
            decimal("9").unwrap(),
            decimal("1").unwrap(),
            decimal("0.0000000000000000000000000001").unwrap()
        ));
    }
    #[test]
    fn exact_operations_reject_rounding_and_overflow() {
        let smallest = decimal("0.0000000000000000000000000001").unwrap();
        assert!(exact_mul(smallest, decimal("0.1").unwrap()).is_err());
        assert!(exact_add(decimal("9").unwrap(), smallest).is_err());
        assert!(exact_sub(decimal("9").unwrap(), smallest).is_err());
        assert_eq!(
            exact_mul(decimal("0.10").unwrap(), decimal("20").unwrap()).unwrap(),
            decimal("2").unwrap()
        );
        assert_eq!(
            exact_div100(decimal("10").unwrap()).unwrap(),
            decimal("0.10").unwrap()
        );
        assert!(exact_div100(smallest).is_err());
    }
    #[test]
    fn all_inventory_mode_families_remain_distinct() {
        for (s, expected) in [
            ("normal", ModeKind::Normal),
            ("purchase", ModeKind::Purchase),
            ("antebet", ModeKind::AnteBet),
            ("booster", ModeKind::Booster),
            ("variant", ModeKind::Variant),
        ] {
            assert_eq!(
                serde_json::from_value::<ModeKind>(Value::String(s.into())).unwrap(),
                expected
            );
        }
    }
    #[test]
    fn exact_precision_rejects_underflow_and_keeps_precise_json() {
        assert!(decimal("0.00000000000000000000000000001").is_err());
        assert!(decimal("1e-29").is_err());
        let underflow: Value =
            serde_json::from_str(r#"{"amount":0.00000000000000000000000000001}"#).unwrap();
        assert!(decimal(&underflow["amount"].to_string()).is_err());
        let payload: Value =
            serde_json::from_str(r#"{"amount":0.1234567890123456789012345678}"#).unwrap();
        assert_eq!(
            decimal(&payload["amount"].to_string()).unwrap().to_string(),
            "0.1234567890123456789012345678"
        );
        assert_eq!(decimal("1.25e-2").unwrap().to_string(), "0.0125");
        assert!(decimal("1.00000000000000000000000000001e0").is_err());
    }
    #[test]
    fn missing_native_currency_preserves_public_binding_provenance() {
        assert_eq!(currency_binding(None, "EUR").unwrap(), "public_binding");
        assert_eq!(
            currency_binding(Some("EUR"), "EUR").unwrap(),
            "native_response"
        );
        assert!(currency_binding(Some("USD"), "EUR").is_err());
        assert!(currency_binding(Some(""), "EUR").is_err());
    }
    #[test]
    fn negative_money_is_rejected() {
        assert!(decimal("-0.01").is_err());
    }
}
