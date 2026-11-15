use crate::model::{InventorySnapshot, InventorySource, ProviderInventory, sha256};
use anyhow::{Context, Result, bail, ensure};
use serde::Deserialize;
use serde_json::Value;
use std::{
    collections::HashSet,
    fs,
    path::{Component, Path},
};

#[derive(Deserialize)]
struct Entry {
    id: String,
    path: String,
    games: usize,
    modes: usize,
    sha256: String,
}

pub fn load_manifest(path: &Path) -> Result<InventorySnapshot> {
    let entries: Vec<Entry> =
        serde_json::from_slice(&fs::read(path).context("read inventory manifest")?)
            .context("parse inventory manifest")?;
    ensure!(!entries.is_empty(), "empty inventory manifest");
    let base = path.parent().unwrap_or(Path::new(".")).canonicalize()?;
    let mut providers = Vec::new();
    let mut sources = Vec::new();
    let mut semantic = Vec::<Value>::new();
    let mut ids = HashSet::new();
    for entry in entries {
        ensure!(
            !entry.id.trim().is_empty() && ids.insert(entry.id.clone()),
            "empty or duplicate provider id: {}",
            entry.id
        );
        let relative = Path::new(&entry.path);
        ensure!(
            !relative.is_absolute()
                && relative
                    .components()
                    .all(|c| matches!(c, Component::Normal(_))),
            "unsafe inventory path: {}",
            entry.path
        );
        let file = base
            .join(relative)
            .canonicalize()
            .with_context(|| format!("inventory path {}", entry.path))?;
        ensure!(
            file.starts_with(&base),
            "inventory path escapes manifest directory"
        );
        let bytes = fs::read(&file)?;
        let actual = sha256(&bytes);
        let representation = if actual.eq_ignore_ascii_case(&entry.sha256) {
            "exact"
        } else {
            // Historical publication used CRLF bytes; normalize only line endings, never content.
            let text = std::str::from_utf8(&bytes).context("inventory is not UTF-8")?;
            let lf = text.replace("\r\n", "\n");
            let crlf = lf.replace('\n', "\r\n");
            if sha256(crlf.as_bytes()).eq_ignore_ascii_case(&entry.sha256)
                || sha256(lf.as_bytes()).eq_ignore_ascii_case(&entry.sha256)
            {
                "historical_crlf"
            } else {
                bail!("inventory hash mismatch for {}", entry.id)
            }
        };
        let value: Value = serde_json::from_slice(&bytes).context("parse provider JSON")?;
        let provider: ProviderInventory = serde_json::from_value(value.clone())
            .with_context(|| format!("parse provider {}", entry.id))?;
        ensure!(
            provider.id == entry.id,
            "provider id mismatch: {}",
            entry.id
        );
        ensure!(
            provider.games.len() == entry.games,
            "game count mismatch for {}",
            entry.id
        );
        let mut games = HashSet::new();
        let mut modes = 0usize;
        for game in &provider.games {
            ensure!(
                !game.id.trim().is_empty() && games.insert(&game.id),
                "empty or duplicate game id in {}",
                entry.id
            );
            let mut keys = HashSet::new();
            for mode in &game.modes {
                ensure!(
                    !mode.key.trim().is_empty() && keys.insert(&mode.key),
                    "empty or duplicate mode key in {}/{}",
                    entry.id,
                    game.id
                );
                modes += 1;
            }
        }
        ensure!(modes == entry.modes, "mode count mismatch for {}", entry.id);
        semantic.push(value);
        sources.push(InventorySource {
            provider: entry.id,
            path: entry.path,
            actual_sha256: actual,
            declared_sha256: entry.sha256,
            hash_representation: representation.into(),
        });
        providers.push(provider);
    }
    Ok(InventorySnapshot {
        id: sha256(&serde_json::to_vec(&semantic)?),
        providers,
        sources,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn published_inventory_loads() {
        let p = Path::new(env!("CARGO_MANIFEST_DIR")).join("../docs/recolector/inventario.json");
        assert_eq!(load_manifest(&p).unwrap().providers.len(), 35);
    }
    #[test]
    fn rejects_tampered_content_and_paths() {
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path();
        fs::write(p.join("a.json"), br#"{"id":"a","name":"A","games":[]}"#).unwrap();
        fs::write(
            p.join("index.json"),
            r#"[{"id":"a","path":"a.json","games":0,"modes":0,"sha256":"bad"}]"#,
        )
        .unwrap();
        assert!(load_manifest(&p.join("index.json")).is_err());
        fs::write(
            p.join("index.json"),
            r#"[{"id":"a","path":"../a.json","games":0,"modes":0,"sha256":"bad"}]"#,
        )
        .unwrap();
        assert!(load_manifest(&p.join("index.json")).is_err());
    }
    #[test]
    fn historical_crlf_has_same_semantic_id() {
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path();
        let lf = "{\n  \"id\": \"a\", \"name\": \"A\", \"games\": []\n}\n";
        let crlf = lf.replace('\n', "\r\n");
        fs::write(p.join("a.json"), lf).unwrap();
        let index = serde_json::json!([{"id":"a","path":"a.json","games":0,"modes":0,"sha256":sha256(crlf.as_bytes())}]);
        fs::write(p.join("index.json"), serde_json::to_vec(&index).unwrap()).unwrap();
        let first = load_manifest(&p.join("index.json")).unwrap();
        assert_eq!(first.sources[0].hash_representation, "historical_crlf");
        fs::write(p.join("a.json"), crlf).unwrap();
        let second = load_manifest(&p.join("index.json")).unwrap();
        assert_eq!(second.sources[0].hash_representation, "exact");
        assert_eq!(first.id, second.id);
    }
}
