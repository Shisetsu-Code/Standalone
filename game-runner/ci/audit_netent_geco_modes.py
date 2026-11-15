"""Build GECO mode bindings from source-reviewed, reconciled demo captures."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import parse_qsl, urlsplit

from audit_netent_geco import audit_launch, initializations, owner, packets, read

# Each path was observed with the same bytes as the reviewed client. The
# runtime checks that SHA-256 again before sending a wager.
ASSETS = {
    "bee-hive-bonanza": "/games/beehivebonanza-client/init.js",
    "busters-bones": "/games/bustersbones-client/init.js",
    "cupcakes": "/games/cupcakes-client/init.js",
    "funk-master": "/games/funkmaster-client/main.js",
    "koi-princess": "/games/koiprincess_mobile_html/game/javascript/main.js",
    "let-it-burn": "/games/letitburn-client/init.js",
    "milkshake-xxxtreme": "/games/milkshakeextreme-client/init.js",
    "secret-of-the-stones": "/games/secretofthestones_mobile_html/game/javascript/main.js",
    "space-wars-2-powerpoints": "/games/spacewars2-client/main.js",
    "superstars": "/games/superstars-client/init.js",
    "victorious": "/games/victorious_mobile_html/game/javascript/main.js",
}


def rounds(game, bootstrap):
    starts = initializations(game, bootstrap["initialization"])
    balances = {key: value["credit"] for key, value in starts.items()}
    active = None
    active_key = None
    for sending, received in packets(game / "geco-financial-trace.jsonl"):
        key = owner(sending["url"])
        if key not in starts or received.get("status") != 200:
            active = None
            continue
        params = dict(parse_qsl(urlsplit(sending["url"]).query, keep_blank_values=True))
        response = dict(parse_qsl(received["text"], keep_blank_values=True))
        if "credit" not in response or response.get("errorcode") not in (None, "", "0"):
            active = None
            continue
        if params.get("action") in ("spin", "featurebuy"):
            active = starts[key], balances[key], []
            active_key = key
        if active is None or active_key != key:
            active = None
            continue
        active[2].append((params, response))
        if response.get("gameover") == "true":
            balances[key] = response["credit"]
            yield active
            active = None


def matches(case, mode, profile, captured, minimum_bet, spin_parameters):
    opening, credit, steps = captured
    if len(steps) != len(case["steps"]) or Decimal(credit) != Decimal(case["before"]) * 100:
        return False
    selected = {**spin_parameters(minimum_bet(opening)), **mode.get("params", {})}
    first = steps[0][0]
    if first["action"] != mode["action"] or any(first.get(k) != str(v) for k, v in selected.items()):
        return False
    previous = None
    allowed = {"drop", "freespin", "respin", "initfreespin", *profile.get("free_actions", [])}
    for (sent, received), saved in zip(steps, case["steps"]):
        if received.get("playforfun") != "true":
            return False
        if previous and (sent["action"] not in allowed or sent["action"] != previous["nextaction"]):
            return False
        if any(received.get(key) != saved.get(expected) for key, expected in (
            ("nextaction", "next_action"), ("gameover", "game_over"), ("credit", "credit_cents"),
        )):
            return False
        previous = received
    cost = Decimal(minimum_bet(opening)["cost_cents"]) * Decimal(str(mode["factor"]))
    after = Decimal(previous["credit"])
    won = Decimal(previous["totalwin.cents"])
    return (previous["nextaction"] == "spin" and previous.get("gameRoundId")
            and previous["gameRoundId"] != opening.get("gameRoundId")
            and ("bet.mathMode" not in first or first["bet.mathMode"] == previous.get("mathMode"))
            and cost > 0 and won >= 0 and Decimal(credit) - cost + won == after
            and cost == 100 * Decimal(case["cost"]) and won == 100 * Decimal(case["win"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("contracts", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.contracts.resolve()))
    from geco_contract import minimum_bet, spin_parameters

    profiles = read(args.contracts / "geco-profiles-reviewed.json")
    _, launch = audit_launch(args.archive / "campaign")
    result, unresolved = {}, []
    for slug, path in ASSETS.items():
        game = args.archive / "campaign" / slug
        bootstrap = read(game / "bootstrap.json")
        profile = profiles[slug]
        digest = profile["source_sha256"]
        if hashlib.sha256((args.archive / "scripts" / (digest + ".js")).read_bytes()).hexdigest() != digest:
            raise ValueError("captured source does not match profile: " + slug)
        evidence = list(rounds(game, bootstrap))
        cases = {item["mode"]: item for item in read(game / "geco-financial-checkpoint.json")["cases"]
                 if item.get("passed") is True and item.get("state") == "verified"}
        modes = {}
        for mode in profile["modes"]:
            key = mode["mode"]
            if key == "Spin":
                continue
            case = cases.get(key)
            if case is None or not any(matches(case, mode, profile, row, minimum_bet, spin_parameters) for row in evidence):
                unresolved.append([slug, key])
                continue
            modes[key] = {"action": mode["action"], "factor": str(mode["factor"]),
                          "params": {key: str(value) for key, value in mode.get("params", {}).items()}}
        if modes:
            result[slug] = {**launch[slug], "source_path": path, "source_sha256": digest,
                            "modes": modes, "free_actions": profile.get("free_actions", [])}
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps({"games": len(result), "modes": sum(len(p["modes"]) for p in result.values()),
                      "unresolved": unresolved}))


if __name__ == "__main__":
    main()
