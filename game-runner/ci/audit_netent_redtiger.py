"""Bind the archived NetEnt HTML5 HTTP receipts to their demo launch and mode."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def rows(path):
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        yield json.loads(line)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def audit(path, slug, public_id, keys, protocol):
    bootstrap = read(path / "bootstrap.json")
    checkpoint = read(path / "http-financial-checkpoint.json")
    initialization = bootstrap["initialization"]
    require(bootstrap["slug"] == checkpoint["slug"] == slug
            and bootstrap["family"] == checkpoint["family"] == "redtiger_http"
            and initialization["success"] is True, "archive identity")
    trace = path / Path(bootstrap["trace"]).name
    start = settings = None
    configs = []
    user, game = initialization["result"]["user"], initialization["result"]["game"]
    for row in rows(trace):
        url = urlsplit(row.get("url", ""))
        if row.get("status") != 200 or url.scheme != "https":
            continue
        body = row.get("response_body")
        if (url.netloc == "games.evolution.com" and url.path == "/wp-json/games/v1/start"
                and parse_qs(url.query).get("id") == [public_id]):
            start = row
        if url.netloc == "showcase.evo-games.com" and url.path == "/config" and isinstance(body, dict):
            configs.append(body)
        if (url.netloc.endswith(".redtiger.cash") and url.path.endswith("/platform/game/settings")
                and row.get("method") == "POST" and body == initialization):
            settings = (url, json.loads(row["request_body"]))
    require(start and settings, "public issuer or settings missing")
    endpoint, init_request = settings
    native_game = init_request["gameId"]
    require(init_request["playMode"] == "demo" and init_request["userData"]["userType"] == "U"
            and all(user.get(key) for key in ("token", "sessionId", "userId")), "bootstrap demo wallet")
    tables = set()
    for config in configs:
        launch = config.get("wrappedLaunchParams", {})
        if (config.get("base_game_id") == launch.get("gameId") == native_game
                and config.get("game_provider") == "extendednetent" and config.get("userType") == 0
                and launch.get("token") == init_request.get("sessionId")
                and config.get("wrapper_token") == init_request["custom"]["context"]["ne_evo_token"]
                and launch.get("baseUrl", "").rstrip("/") + "/platform/game/settings" == endpoint.geturl()):
            tables.add(config["table_id"])
    require(len(tables) == 1, "ambiguous demo table")
    modes, _ = protocol.mode_plan(game)
    offered = {item["mode"]: item for item in modes}
    minimum = min(Decimal(str(value)) for value in user["stakes"]["types"])
    expected = {case["mode"]: case for case in checkpoint["cases"] if case.get("passed") is True}
    wire = path / "http-financial-trace.jsonl"
    previous = user["balance"]["cash"]
    currency = user["currency"]["code"]
    pending = None
    verified = {}
    for row in rows(wire):
        if row["kind"] == "sending":
            require(pending is None, "unanswered request")
            url = urlsplit(row["url"])
            require((url.scheme, url.netloc, url.path) == (
                "https", endpoint.netloc, endpoint.path.removesuffix("settings") + "spin"
            ), "spin endpoint differs from settings owner")
            pending = row["body"]
            continue
        require(row["kind"] == "received" and pending is not None and row["status"] == 200,
                "unpaired or failed response")
        response = row["body"]
        require(response["success"] is True, "spin declined")
        returned = response["result"]["user"]
        require(pending["gameId"] == native_game
                and pending["token"] == user["token"] and pending["sessionId"] == user["sessionId"]
                and pending["userData"]["userId"] == returned["userId"] == user["userId"],
                "spin changed session or user")
        mode = next((item for item in offered.values() if item["id"] == pending["gameMode"]), None)
        require(mode is not None, "unoffered mode")
        receipt = protocol.reconcile_mode(pending, response, previous, mode, configuration=game)
        key = mode["mode"]
        if key in keys:
            saved = expected.get(key)
            require(saved and receipt["passed"] and Decimal(str(pending["stake"])) == minimum
                    and all(Decimal(saved[k]) == Decimal(receipt[k]) for k in ("before", "after", "cost", "win")),
                    "historical receipt differs")
            require(key not in verified, "ambiguous mode receipt")
            verified[key] = {"id": mode["id"], "kind": mode["kind"], "factor": mode["factor"],
                             "currency": currency, "minimum": str(minimum)}
        previous = receipt["after"]
        user = {**user, **{key: returned[key] for key in ("token", "sessionId") if returned.get(key)}}
        pending = None
    require(pending is None and verified.keys() == set(keys), "incomplete archived mode coverage")
    return {
        "game": slug, "public_game_id": public_id, "native_table": tables.pop(), "native_game": native_game,
        "modes": verified, "financial_sha256": hashlib.sha256(wire.read_bytes()).hexdigest(),
        "launch_sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("archive", "contracts", "launch", "plan", "output"):
        parser.add_argument(argument, type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.contracts.resolve()))
    import http_modes

    launch = read(args.launch)
    targets = {}
    for row in read(args.plan)["coverage"]["omitted_modes"]:
        slug = row["game"]
        if row["provider"] == "netent" and launch.get(slug, {}).get("family") == "redtiger_http":
            targets.setdefault(slug, []).append(row["mode"])
    verified, pending = [], {}
    for slug, keys in targets.items():
        try:
            verified.append(audit(args.archive / "campaign" / slug, slug, launch[slug]["public_game_id"], keys, http_modes))
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as error:
            pending[slug] = str(error) if type(error) is ValueError else type(error).__name__
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump({"verified": verified, "pending": pending}, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"games": len(verified), "modes": sum(len(x["modes"]) for x in verified), "pending": pending}))


if __name__ == "__main__":
    main()
