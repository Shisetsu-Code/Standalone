use crate::model::{Game, sha256};
use anyhow::{Context, Result, bail, ensure};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{collections::BTreeMap, fs, path::Path};
use url::Url;

// Exact upstream blob at fd95f62d39ce5abe236a62b66d7cdf0d0f394d33.
const ENDORPHINA_SHA256: &str = "abc567806dd03e943b8d1516b40206e4c7f3d0d30a58cb851121bb33616cfd5c";
#[derive(Deserialize)]
struct EndorphinaEntry {
    id: String,
    name: String,
    slug: String,
    source: Option<String>,
    source_entry: Option<u64>,
    play_url: String,
}

fn endorphina_catalog(data: &[u8], game: &Game) -> Result<Value> {
    let entries: Vec<EndorphinaEntry> =
        serde_json::from_slice(data).context("invalid Endorphina catalogue")?;
    let mut matches = entries.iter().filter(|r| r.id == game.id);
    let row = matches
        .next()
        .context("game id absent from Endorphina public catalogue")?;
    ensure!(
        matches.next().is_none(),
        "duplicate Endorphina catalogue id"
    );
    ensure!(
        row.name == game.name,
        "Endorphina catalogue game name mismatch"
    );
    ensure!(
        row.source.as_deref() == Some("official_public_page")
            || row.source_entry.is_some_and(|n| n > 0),
        "Endorphina catalogue source is not the official public page"
    );
    ensure!(
        !row.slug.is_empty()
            && row
                .slug
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-'),
        "invalid Endorphina catalogue slug"
    );
    let url = Url::parse(&row.play_url).context("invalid Endorphina play URL")?;
    ensure!(
        url.scheme() == "https"
            && url.host_str() == Some("endorphina.com")
            && url.port().is_none()
            && url.username().is_empty()
            && url.password().is_none()
            && url.query().is_none()
            && url.fragment().is_none(),
        "invalid Endorphina play URL authority"
    );
    ensure!(
        url.path() == format!("/es/juegos/{}/play", row.slug)
            || url.path() == format!("/games/{}/play", row.slug),
        "Endorphina play URL is not bound to catalogue slug"
    );
    Ok(json!({"launch_url":row.play_url}))
}

#[derive(Deserialize)]
struct PeterAndSonsBinding {
    title: String,
    wallet: String,
    currency: String,
    verified_modes: Vec<String>,
    authentication_sha256: Vec<String>,
}

fn peterandsons_catalog(repo: &Path, game: &Game) -> Result<Value> {
    let path = repo.join("game-runner/bindings/peterandsons.json");
    let data = fs::read(&path).context("Peter & Sons slot bindings missing")?;
    peterandsons_binding(&data, game)
}

fn peterandsons_binding(data: &[u8], game: &Game) -> Result<Value> {
    let catalog: BTreeMap<String, PeterAndSonsBinding> =
        serde_json::from_slice(data).context("invalid Peter & Sons slot bindings")?;
    let row = catalog
        .get(&game.id)
        .context("slot without reconciled Peter & Sons binding")?;
    ensure!(
        row.title == game.name,
        "Peter & Sons catalogue game name mismatch"
    );
    ensure!(
        matches!(row.wallet.as_str(), "demo" | "demo-preview")
            && row.currency == "eur"
            && !row.verified_modes.is_empty()
            && !row.authentication_sha256.is_empty()
            && row.authentication_sha256.iter().all(|hash| {
                hash.len() == 64 && hash.bytes().all(|byte| byte.is_ascii_hexdigit())
            }),
        "invalid Peter & Sons public demo binding"
    );
    Ok(json!({
        "wallet": row.wallet,
        "currency": row.currency,
        "verified_modes": row.verified_modes,
    }))
}

fn playson_binding(data: &[u8], game: &Game) -> Result<Value> {
    let rows: BTreeMap<String, Value> =
        serde_json::from_slice(data).context("invalid Playson public bindings")?;
    let row = rows
        .get(&game.id)
        .context("no reviewed Playson binding for this game")?;
    Ok(json!({"binding": row}))
}

/// Resolve only documented, nonsecret launch configuration. Never opens a live game.
pub fn from_repo(repo: &Path, provider: &str, game: &Game) -> Result<Value> {
    match provider {
        "playtech" | "kendoo" | "rubyplay" => Ok(json!({})),
        "thunderspin" | "irondog" | "amigogaming" | "spinomenal" | "mascot" | "habanero"
        | "gamesglobal" => Ok(json!({})),
        "1spin4win" | "egt-digital" | "betsoft" | "evoplay" | "ela-games" | "amusnet" => Ok(json!({})),
        "hacksaw" | "pragmatic" | "reelkingdom" | "redtiger" | "netent" | "belatra" => Ok(json!({})),
        "elk" if game.id == "propaganda-2" => Ok(json!({"game_id":"10276","xdm":"0"})),
        "microgaming" if game.id == "3rd-base" => Ok(json!({})),
        "kagaming" => Ok(json!({})),
        "playngo" => crate::adapters::playngo::embedded_settings(game),
        "hardfire-kalamba" if game.id == "9blazingcashpots50k" => Ok(json!({})),
        "nolimit" if game.id == "SixFeetUnder" => Ok(json!({})),
        "yggdrasil" if game.id == "7301" => Ok(json!({"coin":"0.1","amount":"1","stake":"1"})),
        "endorphina" => {
            let path = repo.join("demo-dashboard/endorphina/catalog.json");
            let data = fs::read(&path).with_context(|| {
                format!("Endorphina public catalogue missing: {}", path.display())
            })?;
            let matches = if sha256(&data) == ENDORPHINA_SHA256 {
                true
            } else {
                let text =
                    std::str::from_utf8(&data).context("invalid Endorphina catalogue UTF-8")?;
                let normalized = text.replace("\r\n", "\n");
                text == normalized.replace('\n', "\r\n")
                    && sha256(normalized.as_bytes()) == ENDORPHINA_SHA256
            };
            ensure!(
                matches,
                "Endorphina public catalogue differs from pinned upstream revision"
            );
            endorphina_catalog(&data, game)
        }
        "peterandsons" => peterandsons_catalog(repo, game),
        "playson" => {
            let data = fs::read(repo.join("game-runner/bindings/playson.json"))
                .context("Playson public bindings missing")?;
            playson_binding(&data, game)
        }
        _ => bail!("no reviewed automatic binding for provider {provider}"),
    }
}

pub fn embedded(provider: &str, game: &Game) -> Result<Value> {
    match provider {
        "playtech" | "kendoo" | "rubyplay" => Ok(json!({})),
        "thunderspin" | "irondog" | "amigogaming" | "spinomenal" | "mascot" | "habanero"
        | "gamesglobal" => Ok(json!({})),
        "1spin4win" | "egt-digital" | "betsoft" | "evoplay" | "ela-games" | "amusnet" => Ok(json!({})),
        "hacksaw" | "pragmatic" | "reelkingdom" | "redtiger" | "netent" | "belatra" => Ok(json!({})),
        "elk" if game.id == "propaganda-2" => Ok(json!({"game_id":"10276","xdm":"0"})),
        "microgaming" if game.id == "3rd-base" => Ok(json!({})),
        "kagaming" => Ok(json!({})),
        "playngo" => crate::adapters::playngo::embedded_settings(game),
        "hardfire-kalamba" if game.id == "9blazingcashpots50k" => Ok(json!({})),
        "nolimit" if game.id == "SixFeetUnder" => Ok(json!({})),
        "yggdrasil" if game.id == "7301" => Ok(json!({"coin":"0.1","amount":"1","stake":"1"})),
        "endorphina" => endorphina_catalog(
            include_bytes!("../../demo-dashboard/endorphina/catalog.json"),
            game,
        ),
        "peterandsons" => {
            peterandsons_binding(include_bytes!("../bindings/peterandsons.json"), game)
        }
        "playson" => playson_binding(include_bytes!("../bindings/playson.json"), game),
        _ => bail!("no embedded binding for {provider}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn game(id: &str, name: &str) -> Game {
        Game {
            id: id.into(),
            name: name.into(),
            ready: true,
            block_reason: String::new(),
            modes: vec![],
        }
    }
    #[test]
    fn rejects_mismatched_identity_duplicates_and_untrusted_url() {
        let record = json!({"id":"1","name":"Test","slug":"test","source":"official_public_page","play_url":"https://endorphina.com/es/juegos/test/play"});
        let one = serde_json::to_vec(&json!([record])).unwrap();
        assert_eq!(
            endorphina_catalog(&one, &game("1", "Test")).unwrap()["launch_url"],
            "https://endorphina.com/es/juegos/test/play"
        );
        assert!(endorphina_catalog(&one, &game("1", "Other")).is_err());
        assert!(
            endorphina_catalog(
                &serde_json::to_vec(&json!([record, record])).unwrap(),
                &game("1", "Test")
            )
            .is_err()
        );
        let mut bad = record.clone();
        bad["play_url"] = json!("https://endorphina.com.evil.invalid/es/juegos/test/play");
        assert!(
            endorphina_catalog(
                &serde_json::to_vec(&json!([bad])).unwrap(),
                &game("1", "Test")
            )
            .is_err()
        );
    }
    #[test]
    fn pinned_catalog_binds_all_published_games() {
        let repo = Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap();
        let inventory: crate::model::ProviderInventory = serde_json::from_slice(
            &fs::read(repo.join("docs/recolector/inventario/endorphina.json")).unwrap(),
        )
        .unwrap();
        for game in &inventory.games {
            if let Err(e) = from_repo(repo, "endorphina", game) {
                panic!("{}: {e:#}", game.id);
            }
        }
        assert_eq!(inventory.games.len(), 238);
    }
    #[test]
    fn pinned_catalog_accepts_crlf_and_rejects_changed_content() {
        let repo = Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap();
        let original =
            fs::read_to_string(repo.join("demo-dashboard/endorphina/catalog.json")).unwrap();
        let data = original.replace("\r\n", "\n").replace('\n', "\r\n");
        let entries: Vec<EndorphinaEntry> = serde_json::from_str(&data).unwrap();
        let game = game(&entries[0].id, &entries[0].name);
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("demo-dashboard/endorphina");
        fs::create_dir_all(&path).unwrap();
        fs::write(path.join("catalog.json"), &data).unwrap();
        assert!(from_repo(dir.path(), "endorphina", &game).is_ok());
        fs::write(
            path.join("catalog.json"),
            data.replace(&entries[0].name, "tampered"),
        )
        .unwrap();
        assert!(from_repo(dir.path(), "endorphina", &game).is_err());
    }
    #[test]
    fn peterandsons_resolves_reviewed_slot_from_repo() {
        let repo = Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap();
        let settings =
            from_repo(repo, "peterandsons", &game("abrakadabra", "Abrakadabra")).unwrap();
        assert_eq!(settings["wallet"], "demo");
        assert_eq!(settings["currency"], "eur");
        assert!(
            settings["verified_modes"]
                .as_array()
                .unwrap()
                .contains(&json!("main"))
        );
        assert!(from_repo(repo, "peterandsons", &game("gold-raiders", "Gold Raiders")).is_err());
        assert!(from_repo(repo, "peterandsons", &game("abrakadabra", "Wrong")).is_err());
    }

    #[test]
    fn peterandsons_reconciled_modes_make_valid_native_plans() {
        use crate::{adapters::NativeExecutor, engine::Executor, model::ProviderInventory};
        let repo = Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap();
        let inventory: ProviderInventory = serde_json::from_slice(
            &fs::read(repo.join("docs/recolector/inventario/peterandsons.json")).unwrap(),
        )
        .unwrap();
        let mut configured = 0;
        let mut validated = 0;
        for game in &inventory.games {
            let Ok(settings) = from_repo(repo, "peterandsons", game) else {
                continue;
            };
            configured += 1;
            for key in settings["verified_modes"].as_array().unwrap() {
                let mode = game
                    .modes
                    .iter()
                    .find(|mode| key.as_str() == Some(&mode.key))
                    .unwrap();
                NativeExecutor
                    .validate("peterandsons", game, mode, &settings)
                    .unwrap_or_else(|error| panic!("{}/{}: {error:#}", game.id, mode.key));
                validated += 1;
            }
        }
        assert_eq!((configured, validated), (70, 223));
    }

    #[test]
    fn playson_catalog_binding_schedules_all_reviewed_lucky_pots_modes() {
        use crate::{
            campaign::{PlanOptions, plan_all},
            model::{InventorySnapshot, ProviderInventory},
        };

        let repo = Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap();
        let provider: ProviderInventory = serde_json::from_slice(
            &fs::read(repo.join("docs/recolector/inventario/playson.json")).unwrap(),
        )
        .unwrap();
        let inventory = InventorySnapshot {
            id: "playson-test".into(),
            providers: vec![provider],
            sources: vec![],
        };
        let options = PlanOptions {
            games: vec!["lucky-pots-x1000".into()],
            ..PlanOptions::default()
        };
        let plan = plan_all(&inventory, repo, "playson-test", &options).unwrap();
        let modes: std::collections::BTreeSet<_> =
            plan.jobs.iter().map(|job| job.mode.as_str()).collect();
        assert_eq!(
            modes,
            ["Spin", "Ante:1.5", "Ante:2", "Buy:0", "Buy:1"].into()
        );
    }

    #[test]
    fn missing_evidence_is_not_guessed() {
        let d = tempfile::tempdir().unwrap();
        let g = game("id", "Name");
        assert!(from_repo(d.path(), "peterandsons", &g).is_err());
        assert!(from_repo(d.path(), "playson", &g).is_err());
        assert_eq!(from_repo(d.path(), "hacksaw", &g).unwrap(), json!({}));
        let path = d.path().join("demo-dashboard/endorphina");
        fs::create_dir_all(&path).unwrap();
        fs::write(path.join("catalog.json"), "[]").unwrap();
        assert!(from_repo(d.path(), "endorphina", &g).is_err());
    }
}
