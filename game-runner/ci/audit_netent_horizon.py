"""Bind Horizon modes whose WebSocket requests, debits and close agree."""
import argparse
import base64
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import parse_qsl, urlsplit

from audit_netent_geco import read

CONTINUATIONS = {"respin", "freespin", "featureexecution", "jackpotpayout"}
HOST = "showcase.evo-games.com"


def records(path):
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        yield json.loads(line, parse_float=Decimal)


def public_binding(game, bootstrap):
    config = None
    config_version = None
    for event in records(game / Path(bootstrap["trace"]).name):
        url = urlsplit(event.get("url", ""))
        if url.hostname != HOST:
            continue
        if event.get("kind") == "http" and url.path == "/config" and event.get("status") == 200:
            config = event["response_body"]
            config_version = dict(parse_qsl(url.query)).get("client_version")
            continue
        if config is None or event.get("kind") != "ws_open" or url.path != "/public/horizon":
            continue
        template = urlsplit(config["wsUrl"])
        query = dict(parse_qsl(url.query))
        original = dict(parse_qsl(template.query))
        if (url.scheme != "wss" or template.path != url.path or template.netloc
                or set(original) != {"EVOSESSIONID", "tableId", "gameType"}
                or any(query.get(k) != v for k, v in original.items())
                or not query.get("balanceId", "").startswith("demo-")
                or query["tableId"] != config["table_id"] or config["userType"] != 0
                or config["game_provider"] != "netent" or config["game_engine"] != "slots"
                or config.get("currencyDecimals") != 2 or not config_version):
            return None
        return {"table_id": query["tableId"], "game_type": query["gameType"],
                "client_version": query["client_version"], "config_version": config_version}, config
    return None


def trace_rounds(path, table):
    """Decouple roots using AppInfo, matching replyTo and the demo wallet."""
    wallet = initial = active = pending = None
    rounds = []
    for event in records(path):
        packet = json.loads(event["data"], parse_float=Decimal)
        body = packet.get("payload", packet)
        kind = body.get("type")
        if event["direction"] == "sent":
            if kind == "AppInfo":
                wallet = initial = active = pending = None
            elif kind == "SlotsCall":
                details = body["details"]
                if "play" in details:
                    active = {"wallet": wallet, "initial": initial, "requests": [], "results": [], "debits": []}
                    rounds.append(active)
                if active is not None:
                    pending = packet["id"]
                    active["requests"].append(details)
            continue
        if kind == "balanceUpdated":
            args = body["args"]
            balances = [v for v in args["balances"] if str(v["id"]).startswith("demo-")]
            if args.get("tableId") != table or len(balances) != 1:
                active = pending = None
                continue
            wallet = balances[0]
            if active is not None:
                active["debits"].append(wallet)
        elif kind == "SlotsResult":
            params = body["details"]["params"]
            if pending is None and initial is None and params.get("stakeIncrements"):
                initial = params
            elif active is not None and pending is not None and packet.get("replyTo") == pending:
                active["results"].append(params)
                pending = None
        elif kind in {"connection.kickout", "SlotsError", "error", "Error"}:
            wallet = initial = active = pending = None
    return rounds


def reconcile(row, receipt, special=None):
    initial, opening = row["initial"], row["wallet"]
    requests, responses = row["requests"], row["results"]
    if (not initial or not opening or not requests or len(requests) != len(responses)
            or len(requests) != len(receipt.get("steps", [])) or requests != receipt.get("requests", [])):
        return False
    play = requests[0].get("play", {})
    key = receipt["mode"]
    protocol = initial.get("protocolVersion", 1)
    if special is not None:
        requested = {"stake": play.get("stake"), "betCode": special["bet_code"], "game": special["game"]}
        if protocol != 1 or play != requested or initial.get("game", {}).get("featureBuyEnabled") is not True:
            return False
        factor = Decimal(special["factor"])
        if field := special.get("factor_field"):
            value = initial["game"]
            for key_part in field.split("."):
                value = value.get(key_part) if isinstance(value, dict) else None
            if value is None or Decimal(value) != factor:
                return False
    elif set(play) != {"stake", "betCode"} or play["betCode"] != key:
        return False
    elif protocol == 2:
        factor = initial.get("costFactors", {}).get(key)
        if key != "Spin" and initial.get("featuresEnabled") is not True:
            return False
    elif protocol == 1 and key == "Spin":
        factor = 1
    else:
        return False
    if factor is None or initial.get("nextAction") != "spin" or min(initial["stakeIncrements"]) != play["stake"]:
        return False
    last = responses[-1]
    native_round = last.get("gameRoundId")
    if (not native_round or last.get("nextAction") != "spin" or last.get("wins", {}).get("pending")
            or any(r.get("gameRoundId") != native_round for r in responses)
            or not matches_continuations(requests[1:], responses, special)):
        return False
    if any(changed["id"] != opening["id"] for changed in row["debits"]):
        return False
    before = Decimal(opening["amount"])
    cost = Decimal(factor) * Decimal(play["stake"])
    reported = Decimal(last["wins"]["total"])
    with localcontext() as exact:
        exact.prec = 80
        win = reported.quantize(Decimal("0.01"))
        if reported < 0 or abs(reported - win) >= Decimal("1e-24") or (reported != 0 and win == 0):
            return False
    debit = next((Decimal(v["amount"]) for v in row["debits"] if Decimal(v["amount"]) != before), before)
    final = Decimal(row["debits"][-1]["amount"]) if row["debits"] else before
    return (cost > 0 and win >= 0 and before - debit == cost and final == before - cost + win
            and (before, cost, win, final) == tuple(Decimal(receipt[key]) for key in ("before", "cost", "win", "after")))


def matches_continuations(requests, responses, special):
    choice = (special or {}).get("jungle_choice")
    finn = (special or {}).get("finn_choice")
    decisions = 0
    for request, previous in zip(requests, responses):
        action = previous.get("nextAction")
        if action in CONTINUATIONS:
            if request != {"continue": {}}:
                return False
            continue
        if action != "userdecision" or (choice is None and finn is None):
            return False
        if finn is not None:
            game = previous.get("game", {})
            offer = {"id": finn["id"], "keysToUnlock": finn["keys"]}
            if (decisions or offer not in game.get("freeSpins", []) or game.get("totalKeys", -1) < finn["keys"]
                    or request != {"continue": {"game": {"select": finn["id"]}}}):
                return False
            decisions += 1
            continue
        animal = previous.get("game", {}).get("featuredAnimal")
        if decisions == 0 and animal is None:
            payload = {"featureBuy": False, "animal": choice["animal"]}
        elif decisions == 1 and isinstance(animal, dict) and str(animal.get("id")) == choice["animal"]:
            payload = {"featureBuy": False, "gamble": choice["gamble"]}
        else:
            return False
        if request != {"continue": {"game": payload}}:
            return False
        decisions += 1
    return decisions == (2 if choice else 1 if finn else 0)


def source_integrities(campaign):
    trusted = set()
    expression = re.compile(r'"js/(ne[^"/]+\.js)"\s*:\s*"(sha384-[A-Za-z0-9+/=]+)"')
    for path in sorted(campaign.glob("*/bootstrap.json")):
        bootstrap = read(path)
        if bootstrap.get("family") != "horizon":
            continue
        for event in records(path.parent / Path(bootstrap["trace"]).name):
            url = urlsplit(event.get("url", ""))
            if url.hostname == HOST and url.path.startswith("/frontend/evo/") and event.get("status") == 200:
                trusted.update(expression.findall(event.get("response_text", "")))
    return trusted


def reviewed_v1_modes(campaign, slug, bootstrap, config, profiles, integrities, constant_buys):
    if bootstrap.get("initialization", {}).get("protocolVersion", 1) != 1:
        return {}
    registered = profiles.get(slug)
    reviewed = {}
    for name, digest in sorted({(entry["name"], entry["sha256"]) for entry in bootstrap.get("scripts", [])}):
        if registered and registered["source_sha256"] != digest:
            continue
        raw = (campaign.parent / "scripts" / (digest + ".js")).read_bytes()
        integrity = "sha384-" + base64.b64encode(hashlib.sha384(raw).digest()).decode()
        if hashlib.sha256(raw).hexdigest() != digest or (name, integrity) not in integrities:
            continue
        modes = registered["modes"] if registered else constant_buys([raw.decode("utf-8")])
        if slug == "finn-and-the-candy-spin" and re.search(r'\{kind:"featurebuy"\},[A-Za-z_$][\w$]*\.x_\.FeatureBuy', raw.decode("utf-8")):
            game = bootstrap["initialization"]["game"]
            modes = [dict(mode="FeatureBuy:select=" + offer["id"], game={"kind": "featurebuy"},
                          factor=game["featureBuyMultiplier"], factor_field="featureBuyMultiplier",
                          finn_choice={"id": offer["id"], "keys": offer["keysToUnlock"]})
                     for offer in game["freeSpins"]]
        for mode in modes:
            key = mode["mode"]
            if not mode.get("game"):
                continue
            reviewed[key] = {"bet_code": key.split(":")[0], "game": mode["game"],
                             "factor": str(mode["factor"]), "factor_field": mode.get("factor_field"),
                             "asset": name, "integrity": integrity, "source_sha256": digest,
                             "frontend_app": config["frontend_app"], "game_version": config["game_version"]}
            if choice := mode.get("decision_profile"):
                if (slug != "jungle-spirit-megaways" or choice.get("animal") not in {"3", "4", "5", "6", "7"}
                        or type(choice.get("gamble")) is not bool):
                    del reviewed[key]
                    continue
                reviewed[key]["jungle_choice"] = choice
            if choice := mode.get("finn_choice"):
                reviewed[key]["finn_choice"] = choice
    return reviewed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--contracts", type=Path)
    args = parser.parse_args()
    bindings, missing = {}, []
    profiles, integrities = {}, set()
    if args.contracts:
        sys.path.insert(0, str(args.contracts.resolve()))
        from native_profiles import constant_buys
        profiles = read(args.contracts / "native-profiles-reviewed.json")
        integrities = source_integrities(args.campaign)
    for path in sorted(args.campaign.glob("*/bootstrap.json")):
        bootstrap = read(path)
        folder = path.parent
        if bootstrap.get("family") != "horizon" or not (folder / "financial-checkpoint.json").is_file():
            continue
        launcher = public_binding(folder, bootstrap)
        if not launcher:
            continue
        binding, config = launcher
        modes = []
        v1 = {}
        slug = folder.name
        attempts = [(folder, bootstrap, config)]
        extra_name = {"jungle-spirit-megaways": "choices-validation", "finn-and-the-candy-spin": "heartbeat-validation"}.get(slug)
        if extra_name:
            extra = args.campaign.parent / "independent-runs" / slug / extra_name
            if (extra / "bootstrap.json").is_file():
                extra_bootstrap = read(extra / "bootstrap.json")
                extra_launch = public_binding(extra, extra_bootstrap)
                if extra_launch and extra_launch[0] == binding:
                    attempts.append((extra, extra_bootstrap, extra_launch[1]))
        for evidence, attempt, launch_config in attempts:
            observed = trace_rounds(evidence / "financial-trace.jsonl", binding["table_id"])
            candidates = reviewed_v1_modes(args.campaign, slug, attempt, launch_config, profiles, integrities,
                                         constant_buys) if args.contracts else {}
            checkpoint = json.loads((evidence / "financial-checkpoint.json").read_text(encoding="utf-8-sig"), parse_float=Decimal)
            for receipt in checkpoint["cases"]:
                if receipt.get("passed") is not True or (evidence != folder and receipt["mode"] == "Spin"):
                    continue
                key = receipt["mode"]
                if any(reconcile(row, receipt) for row in observed):
                    modes.append(key)
                elif (special := candidates.get(key)) and any(reconcile(row, receipt, special) for row in observed):
                    modes.append(key)
                    v1[key] = special
                else:
                    missing.append((slug, key))
        if modes:
            bindings[folder.name] = dict(binding, modes=sorted(set(modes)))
            if v1:
                bindings[folder.name]["v1_modes"] = v1
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(bindings, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"games": len(bindings), "modes": sum(len(v["modes"]) for v in bindings.values()), "unmapped": len(missing)}))


if __name__ == "__main__":
    main()
