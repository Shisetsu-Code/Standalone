"""Audit saved single-step GECO normal rounds with the standalone Rust executable."""
import argparse
import json
import re
import subprocess
import tempfile
from collections import Counter
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

OWNER_FIELDS = ("sessid", "gameId", "ne_balance_id", "ne_mode", "ne_currency")


def audit_launch(campaign):
    counts = Counter()
    pending = []
    bindings = {}
    for game in sorted(campaign.iterdir()):
        bootstrap = game / "bootstrap.json"
        if not bootstrap.is_file():
            continue
        record = read(bootstrap)
        if record.get("family") != "geco_http":
            continue
        counts["geco"] += 1
        native = urlsplit(record["initialization"]["native_url"])
        params = query(native.geturl())
        trace = game / Path(record["trace"]).name
        matched = False
        same_session = False
        if trace.is_file():
            with trace.open(encoding="utf-8-sig") as stream:
                for line in stream:
                    row = json.loads(line)
                    target = urlsplit(row.get("url", ""))
                    if (row.get("kind"), row.get("status"), target.hostname, target.path) != (
                        "http", 200, "showcase.evo-games.com", "/config"
                    ):
                        continue
                    config = row.get("response_body") or {}
                    launch = config.get("wrappedLaunchParams") or {}
                    if not params.get("sessid") or params["sessid"] != config.get("bare_session_id"):
                        continue
                    same_session = True
                    same_tokens = all(params.get(key) and params[key] == launch.get(key) for key in (
                        "gameId", "ne_currency", "ne_device", "ne_casinoId",
                        "ne_evo_token", "ne_evo_token1", "ne_evo_token2",
                    ))
                    table = query(target.geturl()).get("table_id")
                    matched = bool(
                        same_tokens and params["sessid"] == launch.get("sessionId")
                        and native.hostname == target.hostname
                        and native.path == "/public/rng/dragon/servlet/CasinoGameServlet;jsession=" + params["sessid"]
                        and re.fullmatch(r"demo-[A-Za-z0-9_=-]{1,256}", params.get("ne_balance_id", ""))
                        and params.get("ne_mode") == "demo" and table and config.get("table_id") == table
                        and config.get("game_provider") == "netent" and config.get("game_engine") == "geco"
                        and config.get("userType") == 0 and config.get("currencyDecimals") == 2
                        and config.get("currencyCode") == params.get("ne_currency")
                    )
                    if matched:
                        break
        counts["same_session_config"] += same_session
        if matched:
            counts["matched"] += 1
            bindings[game.name] = {"table_id": table, "game_id": params["gameId"]}
        else:
            pending.append(game.name)
    return {"counts": dict(counts), "pending": pending}, bindings


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def query(url):
    return dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))


def owner(url):
    target = urlsplit(url)
    values = query(url)
    if target.scheme != "https" or values.get("ne_mode") != "demo":
        return None
    if not all(values.get(key) for key in OWNER_FIELDS):
        return None
    return (target.netloc, target.path.split(";")[0], *(values[key] for key in OWNER_FIELDS))


def initializations(game, native):
    canonical = owner(native["native_url"])
    sessions = {canonical: native["parameters"]}
    ambiguous = set()
    for trace in game.glob("bootstrap-*.jsonl"):
        for line in trace.read_text(encoding="utf-8-sig").splitlines():
            row = json.loads(line)
            if row.get("kind") != "legacy_http" or row.get("status") != 200:
                continue
            url = row["url"]
            if "CasinoGameServlet" not in urlsplit(url).path or query(url).get("action") != "init":
                continue
            key = owner(url)
            if key is None:
                continue
            fields = dict(parse_qsl(row["response_text"], keep_blank_values=True))
            if key in sessions and dict(parse_qsl(public_fields(sessions[key], "round"))) != dict(parse_qsl(public_fields(fields, "round"))):
                # Keep distinct starts separate. The canonical bootstrap has a
                # timestamp and can be preferred only for its own exact owner.
                if key != canonical:
                    ambiguous.add(key)
            else:
                sessions.setdefault(key, fields)
    return {key: fields for key, fields in sessions.items() if key is not None and key not in ambiguous}


def packets(path):
    pending = None
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        row = json.loads(line)
        if row["kind"] == "sending":
            pending = row
        elif row["kind"] == "received" and pending is not None:
            yield pending, row
            pending = None


def public_fields(fields, round_marker):
    allowed = {
        "playforfun", "gameover", "nextaction", "allowedactions", "credit",
        "totalwin.cents", "denomination.all", "betlevel.all", "bl.standard",
        "error", "errorcode", "gameId",
    }
    result = {
        key: value for key, value in fields.items()
        if key in allowed or (key.startswith("bl.i") and key.endswith((".line", ".id", ".coins")))
    }
    if fields.get("gameRoundId"):
        result["gameRoundId"] = round_marker
    return urlencode(result)


def compare(runner, folder, initial, terminal, request, saved, currency):
    start_file = folder / "init.txt"
    close_file = folder / "close.txt"
    # The caller has already matched the launch and request on native game and owner.
    if initial.get("gameId", request["gameId"]) != request["gameId"]:
        return None
    start = dict(initial, gameId=request["gameId"])
    start_file.write_text(public_fields(start, "initial-round"), encoding="utf-8")
    same_round = initial.get("gameRoundId") == terminal.get("gameRoundId")
    close_file.write_text(
        public_fields(terminal, "initial-round" if same_round else "terminal-round"),
        encoding="utf-8",
    )
    run = subprocess.run(
        [str(runner), "audit-geco", str(start_file), str(close_file), currency],
        capture_output=True, text=True, timeout=15,
    )
    if run.returncode:
        return None
    outcome = json.loads(run.stdout)
    amounts_match = all(
        Decimal(outcome[actual]) == Decimal(saved[expected])
        for actual, expected in (
            ("balance_before", "before"), ("balance_after", "after"),
            ("cost", "cost"), ("payout", "win"),
        )
    )
    parameters = outcome["native_data"]["bet"]
    if not amounts_match or not all(request.get(key) == value for key, value in parameters.items()):
        return None
    if outcome["network_requests"] != 0 or outcome["native_closed"] is not True:
        return None
    return outcome


def audit(runner, campaign):
    counts = Counter()
    pending = []
    matched = set()
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        for game in sorted(campaign.iterdir()):
            bootstrap = game / "bootstrap.json"
            trace = game / "geco-financial-trace.jsonl"
            checkpoint = game / "geco-financial-checkpoint.json"
            if not all(path.is_file() for path in (bootstrap, trace, checkpoint)):
                continue
            record = read(bootstrap)
            if record["family"] != "geco_http":
                continue
            saved = next((
                item for item in read(checkpoint)["cases"]
                if item["mode"] == "Spin" and item.get("passed") and len(item.get("steps", [])) == 1
            ), None)
            if saved is None:
                continue

            native = record["initialization"]
            canonical = owner(native["native_url"])
            other_sessions = None
            counts["eligible"] += 1
            match = None
            for sending, received in packets(trace):
                request = query(sending["url"])
                if request.get("action") != "spin" or received.get("status") != 200:
                    continue
                key = owner(sending["url"])
                if key is None:
                    continue
                if key == canonical:
                    initial = native["parameters"]
                else:
                    if other_sessions is None:
                        other_sessions = initializations(game, native)
                    initial = other_sessions.get(key)
                if initial is None:
                    continue
                terminal = dict(parse_qsl(received["text"], keep_blank_values=True))
                if (terminal.get("errorcode") == "998"
                        and set(terminal) <= {"errorcode", "evo-error-code", "traceId"}):
                    counts["historical_error_998"] += 1
                    continue
                match = compare(
                    runner, folder, initial, terminal, request, saved,
                    request["ne_currency"],
                )
                # The first accepted spin belongs to the bootstrap's opening wallet.
                break
            if match is None:
                pending.append(game.name)
            else:
                counts["matched"] += 1
                matched.add(game.name)
                counts["nonzero_payout"] += Decimal(match["payout"]) > 0
    return {"counts": dict(counts), "pending": pending}, matched


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runner", type=Path)
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--bindings-output", type=Path)
    args = parser.parse_args()
    report, matched = audit(args.runner.resolve(), args.campaign)
    report["launch_contract"], launch = audit_launch(args.campaign)
    if args.bindings_output:
        reviewed = {slug: launch[slug] for slug in sorted(matched & launch.keys())}
        with args.bindings_output.open("x", encoding="utf-8") as stream:
            json.dump(reviewed, stream, indent=2)
            stream.write("\n")
    print(json.dumps(report, indent=2))
