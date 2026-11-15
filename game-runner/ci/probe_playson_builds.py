"""Compare public Playson builds with the bindings in a reviewed plan."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from itertools import islice
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

import requests


LAUNCH_HOST = "xplatformwl-lrs.box-int-54f2g.com"
ASSET_HOST = "games.box-int-54f2g.com"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def fetch(session, url, host, path_prefix):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != host
            or parsed.fragment or not parsed.path.startswith(path_prefix)):
        raise ValueError("unreviewed public resource")
    with session.get(url, allow_redirects=False, timeout=(8, 20), stream=True) as response:
        if response.status_code != 200:
            raise ValueError(f"{host}: HTTP {response.status_code}")
        body = bytearray()
        for part in response.iter_content(65536):
            body.extend(part)
            if len(body) > 16 * 1024 * 1024:
                raise ValueError("public resource exceeds size limit")
        return bytes(body)


def inspect(binding, modes, dest, source_tools):
    slug = binding["slug"]
    row = {"game": slug, "modes": modes}
    stage = "public_launch"
    try:
        with requests.Session() as session:
            html = fetch(session, binding["launch_url"], LAUNCH_HOST, "/launch").decode("utf-8")
            cfg, game_url, launcher_url = source_tools.parse_launch(html, binding["expected_native_title"])
            if cfg["game"] != binding["native_game"] or cfg.get("wlCode") != "demomode":
                raise ValueError("public demo identity changed")
            path = "/dgm/games/" + binding["native_game"] + "/"
            stage = "native_source"
            game = fetch(session, game_url, ASSET_HOST, path)
            game_sha = hashlib.sha256(game).hexdigest()
            row["source_sha256"] = game_sha
            row["matches_source"] = game_sha == binding["source_sha256"]
            stage = "native_launcher_source"
            launcher = fetch(session, launcher_url, ASSET_HOST, path)
            launch_sha = hashlib.sha256(launcher).hexdigest()
            row["launcher_sha256"] = launch_sha
            row["matches_launcher"] = launch_sha == binding.get("launcher_sha256")
            stage = "review_build"
            for sha, content in ((game_sha, game), (launch_sha, launcher)):
                asset = dest / (sha + ".js")
                if not asset.exists():
                    asset.write_bytes(content)
            row["engine_version"], row["debug"] = source_tools.native_build(html, launcher.decode("utf-8"))
            row["native_multiplier"] = source_tools.native_game_multiplier(launcher.decode("utf-8"))
            row["builder"] = source_tools.inspect_bet_builders(game.decode("utf-8"))
            row["status"] = "unchanged" if row["matches_source"] and row["matches_launcher"] else "changed"
    except requests.RequestException as error:
        row.update(status="error", stage=stage, error=type(error).__name__)
    except (ValueError, KeyError, AttributeError, StopIteration) as error:
        row.update(status="error", stage=stage, error=str(error))
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contracts", type=Path)
    parser.add_argument("bindings", type=Path)
    parser.add_argument("historical_plan", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--skip", action="append", default=[])
    args = parser.parse_args()
    sys.path.insert(0, str(args.contracts.resolve()))
    import playson_source

    bindings = read(args.bindings)
    modes = {}
    for row in read(args.historical_plan)["coverage"]["omitted_modes"]:
        if row["provider"] == "playson" and row["game"] not in args.skip:
            modes.setdefault(row["game"], []).append(row["mode"])
    args.output.mkdir()
    rows = []
    groups = iter(modes.items())
    with ThreadPoolExecutor(max_workers=2) as executor:
        while wave := list(islice(groups, 2)):
            batch = list(executor.map(
                lambda entry: inspect(bindings[entry[0]], entry[1], args.output, playson_source),
                wave,
            ))
            rows.extend(batch)
            if any(row.get("error", "").endswith(("HTTP 403", "HTTP 429", "HTTP 503")) for row in batch):
                rows.extend({"game": slug, "modes": keys, "status": "deferred"} for slug, keys in groups)
                break
    (args.output / "builds.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    for row in rows:
        print(row["game"], row["status"], len(row["modes"]),
              row.get("debug", {}).get("build_version", row.get("error", "")), flush=True)


if __name__ == "__main__":
    main()
