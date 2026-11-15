pub mod amigogaming;
pub mod amusnet;
pub mod betsoft_live;
pub mod egt_digital;
pub mod ela_games;
pub mod elk;
pub mod endorphina;
pub mod evoplay;
pub mod gamesglobal;
pub mod hacksaw;
pub mod habanero;
pub mod irondog;
pub mod kagaming;
pub mod kendoo;
pub mod kalamba;
pub mod mascot;
pub mod microgaming;
pub(crate) mod netent_launch;
pub(crate) mod netent_geco;
pub(crate) mod netent_horizon;
mod netent_redtiger;
pub mod nolimit;
pub mod onespin4win;
pub mod peterandsons;
pub mod playngo;
pub mod playtech;
pub mod playson;
pub mod pragmatic;
pub mod redtiger;
pub(crate) mod rubyplay;
#[cfg(feature = "rubyplay-native")]
mod rubyplay_native;
pub mod spinomenal;
pub mod thunderspin;
pub mod yggdrasil;

use crate::{context::RunContext, engine::Executor, model::*};
use anyhow::{Context, Result, bail, ensure};
use async_trait::async_trait;
use serde_json::{Value, json};

pub struct NativeExecutor;
fn suffix(key: &str, prefix: &str) -> bool {
    key.strip_prefix(prefix).is_some_and(|s| {
        !s.is_empty() && s.bytes().all(|c| c.is_ascii_digit()) && (s == "0" || !s.starts_with('0'))
    })
}
pub fn supports(provider: &str, game: &Game, mode: &Mode) -> bool {
    match canonical_provider(provider) {
        #[cfg(feature = "rubyplay-native")]
        "rubyplay" => rubyplay_native::supports(game, mode),
        "playtech" => playtech::supports(game, mode),
        "kendoo" => kendoo::supports(game, mode),
        "1spin4win" => onespin4win::supports(game, mode),
        "egt-digital" => egt_digital::supports(game, mode),
        "betsoft" => betsoft_live::supports(game, mode),
        "evoplay" => evoplay::supports(game, mode),
        "ela-games" => ela_games::supports(game, mode),
        "amusnet" => amusnet::supports(game, mode),
        "thunderspin" => thunderspin::supports(game, mode),
        "irondog" => irondog::supports(game, mode),
        "hacksaw" => match mode.kind {
            ModeKind::Normal => mode.key == "normal",
            ModeKind::Booster | ModeKind::Purchase => !mode.key.is_empty(),
            ModeKind::Variant => game.id == "1426" && mode.key == "mode-extreme",
            _ => false,
        },
        "endorphina" => {
            (mode.kind == ModeKind::Normal && mode.key == "normal")
                || (mode.kind == ModeKind::Purchase && mode.key.starts_with("buy-"))
        }
        "peterandsons" => {
            let base = mode.key.split("::offer::").next().unwrap_or("");
            if mode.key.contains("::offer::") {
                return game.id == "bloody-mary"
                    && mode.kind == ModeKind::Purchase
                    && matches!(
                        mode.key.split("::offer::").nth(1),
                        Some("extra_spin_fs" | "extra_spin_sfs")
                    );
            }
            match mode.kind {
                ModeKind::Normal => base == "main",
                ModeKind::Purchase => base == "buy" || base.starts_with("buy_"),
                ModeKind::AnteBet | ModeKind::Special => base == "bet" || base.starts_with("bet_"),
                _ => false,
            }
        }
        "belatra" => match mode.kind {
            ModeKind::Normal => mode.key == "NORMAL",
            ModeKind::AnteBet => mode.key == "VIP",
            ModeKind::Purchase => suffix(&mode.key, "PURCHASE_"),
            _ => false,
        },
        "nolimit" => {
            game.id == "SixFeetUnder" && mode.kind == ModeKind::Normal && mode.key == "normal"
        }
        "hardfire-kalamba" => {
            game.id == "9blazingcashpots50k"
                && mode.kind == ModeKind::Normal
                && mode.key == "normal"
        }
        "yggdrasil" => game.id == "7301" && mode.kind == ModeKind::Normal && mode.key == "BASIC",
        "microgaming" => {
            game.id == "3rd-base" && mode.kind == ModeKind::Normal && mode.key == "normal"
        }
        "elk" => game.id == "propaganda-2" && mode.kind == ModeKind::Normal && mode.key == "DEF",
        "kagaming" => kagaming::supports(game, mode),
        "playngo" => playngo::supports(game, mode),
        "amigogaming" => amigogaming::supports(game, mode),
        "spinomenal" => spinomenal::supports(game, mode),
        "mascot" => mascot::supports(game, mode),
        "habanero" => habanero::supports(game, mode),
        "gamesglobal" => gamesglobal::supports(game, mode),
        "redtiger" => redtiger::supports(game, mode),
        "netent" => netent_geco::supports(game, mode) || netent_horizon::supports(game, mode) || netent_redtiger::supports(game, mode),
        "playson" => match mode.kind {
            ModeKind::Normal => mode.key == "Spin",
            ModeKind::Purchase => suffix(mode.key.split("/Choice:").next().unwrap_or(""), "Buy:"),
            ModeKind::AnteBet => mode.key.starts_with("Ante:"),
            _ => false,
        },
        "pragmatic" => match mode.kind {
            ModeKind::Normal => mode.key == "normal",
            ModeKind::Purchase => suffix(&mode.key, "pur-"),
            ModeKind::AnteBet | ModeKind::Booster | ModeKind::Variant => suffix(&mode.key, "bl-"),
            _ => false,
        },
        _ => false,
    }
}
fn text<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    value
        .get(key)
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .with_context(|| format!("missing public setting {key}"))
}
#[async_trait]
impl Executor for NativeExecutor {
    fn validate(&self, provider: &str, game: &Game, mode: &Mode, settings: &Value) -> Result<()> {
        if settings["executor"] == "suite" {
            return crate::suite::preflight(provider, game, mode, settings);
        }
        ensure!(
            supports(provider, game, mode),
            "no native adapter for {provider}/{}/{}; inventory availability is not execution support",
            game.id,
            mode.key
        );
        ensure!(
            settings.is_null() || settings.is_object(),
            "job settings must be an object"
        );
        match canonical_provider(provider) {
            "1spin4win" | "egt-digital" | "betsoft" | "evoplay" | "ela-games" | "amusnet" | "amigogaming" | "mascot" | "habanero" | "gamesglobal" | "playtech" => {
                ensure!(
                    settings.as_object().is_some_and(|object| object.is_empty()),
                    "{provider} accepts no runtime overrides"
                )
            }
            "netent" => {
                let settings = settings.as_object().context("NetEnt settings must be an object")?;
                ensure!(settings.keys().all(|key| key == "max_prerequisite_rounds"), "unknown NetEnt runtime setting");
                let budget = settings.get("max_prerequisite_rounds")
                    .map(|v| v.as_u64().filter(|&n| n <= 100).context("NetEnt prerequisite budget must be in 0..100"))
                    .transpose()?.unwrap_or(0);
                ensure!(!netent_horizon::requires_progression(game, mode) || budget > 0,
                    "Finn selection requires an explicit prerequisite budget in 1..100");
            }
            "elk" => elk::validate(game, mode, settings)?,
            "microgaming" => microgaming::validate(game, mode, settings)?,
            "kagaming" => kagaming::validate(game, mode, settings)?,
            "playngo" => playngo::validate(game, mode, settings)?,
            "hardfire-kalamba" => kalamba::validate(game, mode, settings)?,
            "yggdrasil" => yggdrasil::validate(game, mode, settings)?,
            "endorphina" => {
                crate::context::validate_target(provider, text(settings, "launch_url")?)?;
            }
            "peterandsons" => {
                ensure!(
                    matches!(text(settings, "wallet")?, "demo" | "demo-preview"),
                    "Peter & Sons requires a public demo wallet"
                );
                text(settings, "currency")?;
                if let Some(modes) = settings.get("verified_modes") {
                    ensure!(
                        modes.as_array().is_some_and(|keys| {
                            keys.iter()
                                .any(|key| key.as_str() == Some(mode.key.as_str()))
                        }),
                        "mode absent from reconciled Peter & Sons slot binding"
                    );
                }
            }
            "playson" => {
                let binding = settings
                    .get("binding")
                    .context("Playson requires a source-bound public binding")?;
                ensure!(
                    text(binding, "slug")? == game.id,
                    "Playson binding slug differs from inventory game"
                );
                crate::context::validate_target(provider, text(binding, "launch_url")?)?;
                let hash = text(binding, "source_sha256")?;
                ensure!(
                    hash.len() == 64 && hash.bytes().all(|b| b.is_ascii_hexdigit()),
                    "source_sha256 must be a SHA-256 digest"
                );
                text(binding, "engine_version")?;
                text(binding, "currency")?;
                ensure!(
                    binding["currency_decimals"]
                        .as_u64()
                        .is_some_and(|v| v <= 6),
                    "Playson binding requires currency_decimals between 0 and 6"
                );
                ensure!(
                    binding["debug"].is_object(),
                    "Playson binding requires public debug configuration"
                );
                playson::validate_reviewed_mode(binding, &mode.key)?;
            }
            _ => {}
        }
        Ok(())
    }
    async fn execute(
        &self,
        ctx: &RunContext,
        provider: &str,
        game: &Game,
        mode: &Mode,
        settings: &Value,
    ) -> Result<RoundOutcome> {
        self.validate(provider, game, mode, settings)?;
        if settings["executor"] == "suite" {
            return crate::suite::execute(ctx, provider, game, mode, settings).await;
        }
        match canonical_provider(provider) {
            "hacksaw" => hacksaw::execute(ctx, game, mode, settings).await,
            "endorphina" => endorphina::execute(ctx, game, mode, settings).await,
            "peterandsons" => peterandsons::execute(ctx, game, mode, settings).await,
            "playson" => playson::execute(ctx, game, mode, settings).await,
            "belatra" => belatra::execute(ctx, game, &mode.key).await,
            "nolimit" => nolimit::execute(ctx, game, mode, settings).await,
            "elk" => elk::execute(ctx, game, mode, settings).await,
            "microgaming" => microgaming::execute(ctx, game, mode, settings).await,
            "kagaming" => kagaming::execute(ctx, game, mode, settings).await,
            "1spin4win" => onespin4win::execute(ctx, game, mode).await,
            "egt-digital" => egt_digital::execute(ctx, game, mode).await,
            "betsoft" => betsoft_live::execute(ctx, game, mode).await,
            "evoplay" => evoplay::execute(ctx, game, mode).await,
            "ela-games" => ela_games::execute(ctx, game, mode).await,
            "amusnet" => amusnet::execute(ctx, game, mode).await,
            "thunderspin" => thunderspin::execute(ctx, game, mode).await,
            "irondog" => irondog::execute(ctx, game, mode).await,
            "playngo" => playngo::execute(ctx, game, mode, settings).await,
            "hardfire-kalamba" => kalamba::execute(ctx, game, mode, settings).await,
            "yggdrasil" => yggdrasil::execute(ctx, game, mode, settings).await,
            "amigogaming" => amigogaming::execute(ctx, game, mode).await,
            "spinomenal" => spinomenal::execute(ctx, game, mode).await,
            "mascot" => mascot::execute(ctx, game, mode).await,
            "habanero" => habanero::execute(ctx, game, mode).await,
            "gamesglobal" => gamesglobal::execute(ctx, game, mode).await,
            "redtiger" => redtiger::execute(ctx, game, mode).await,
            "netent" if netent_redtiger::supports(game, mode) => netent_redtiger::execute(ctx, game, mode).await,
            "netent" if netent_horizon::supports(game, mode) => netent_horizon::execute(ctx, game, mode, settings["max_prerequisite_rounds"].as_u64().unwrap_or(0)).await,
            "netent" => netent_geco::execute(ctx, game, mode).await,
            #[cfg(feature = "rubyplay-native")]
            "rubyplay" => rubyplay_native::execute(ctx, game, mode).await,
            "playtech" => playtech::execute(ctx, game, mode).await,
            "kendoo" => kendoo::execute(ctx, game, mode).await,
            "pragmatic" => pragmatic::execute(ctx, game, mode, settings).await,
            _ => bail!("native adapter unavailable"),
        }
    }
}
pub fn capabilities(inventory: &InventorySnapshot) -> Value {
    let providers=inventory.providers.iter().map(|p|{
        let implemented=matches!(canonical_provider(&p.id),"hacksaw"|"endorphina"|"peterandsons"|"playson"|"pragmatic"|"redtiger"|"netent"|"belatra"|"yggdrasil"|"nolimit"|"hardfire-kalamba"|"playngo"|"elk"|"microgaming"|"kagaming"|"1spin4win"|"egt-digital"|"betsoft"|"evoplay"|"ela-games"|"amusnet"|"thunderspin"|"irondog"|"amigogaming"|"spinomenal"|"mascot"|"habanero"|"gamesglobal");
        let auto_binding=matches!(canonical_provider(&p.id),"hacksaw"|"endorphina"|"peterandsons"|"pragmatic"|"redtiger"|"netent"|"belatra"|"yggdrasil"|"nolimit"|"hardfire-kalamba"|"playngo"|"elk"|"microgaming"|"kagaming"|"1spin4win"|"egt-digital"|"betsoft"|"evoplay"|"ela-games"|"amusnet"|"thunderspin"|"irondog"|"amigogaming"|"spinomenal"|"mascot"|"habanero"|"gamesglobal");
        let supported=p.games.iter().filter(|g|g.ready).flat_map(|g|g.modes.iter().filter(move|m|m.ready&&supports(&p.id,g,m))).count();
        json!({"provider":p.id,"canonical_provider":canonical_provider(&p.id),"inventory_games":p.games.len(),"inventory_modes":p.games.iter().map(|g|g.modes.len()).sum::<usize>(),"native_adapter":implemented,"automatic_public_binding":auto_binding,"ready_mode_selectors":supported,"live_verification":"not_established_by_catalogue","paused":p.id=="kendoo"})
    }).collect::<Vec<_>>();
    json!({"inventory_id":inventory.id,"max_active_games_per_provider":1,"providers":providers})
}
pub mod belatra;
mod belatra_crypto;
