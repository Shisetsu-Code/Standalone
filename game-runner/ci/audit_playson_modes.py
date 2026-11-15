"""Recover Playson selectors from saved TEST XML and the reviewed client."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def source_binding(archive, slug, initial, proof, raw, inspect):
    cfg = initial["config"]
    if (not re.fullmatch(r"TEST\d+", cfg.get("key", "")) or cfg.get("wl") != "demomode"
            or cfg.get("wlCode") != "demomode" or cfg.get("server_url") != "https://demo.0y81pm-c-o6pywcq.com"):
        return None
    hash_ = proof["native_client_sha256"]
    source = archive / "scripts" / (hash_ + ".js")
    if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != hash_:
        return None
    native = inspect(source.read_text(encoding="utf-8-sig"))
    if not native.get("supported") or raw.get("source_sha256") != hash_:
        return None
    url = urlsplit(raw["launch_url"])
    if url.scheme != "https" or url.netloc != "xplatformwl-lrs.box-int-54f2g.com" or url.path != "/launch" or url.fragment:
        return None
    public = {key: raw[key] for key in ("slug", "launch_url", "engine_version", "debug", "source_sha256")}
    if public["slug"] != slug:
        return None
    public.update(expected_native_title=cfg["title"], native_game=cfg["game"],
                  observed_purchase_binding=native["purchase_binding"], observed_ante_binding=native["ante_binding"],
                  purchase_style=native["purchase_style"], bonus_round_counter=native["bonus_round_counter"])
    if native.get("choice_action"):
        public["choice_action"] = native["choice_action"]
    for key in ("native_multiplier", "launcher_sha256"):
        if raw.get(key) is not None:
            public[key] = raw[key]
    return public


def entries(wire, parse):
    rows = [json.loads(line) for line in wire.read_text(encoding="utf-8-sig").splitlines() if line]
    replies = {row["ordinal"]: row for row in rows if row["kind"] == "received"}
    for request in (row for row in rows if row["kind"] == "sending"):
        captured = replies.get(request["ordinal"])
        if not captured or captured["status"] != 200:
            yield request["ordinal"], None, None
            continue
        yield request["ordinal"], parse(request["body"]), parse(captured["body"])


def entry_style(request, case, source):
    buy = request.find("buy")
    ante = request.find("chance_booster")
    if case["kind"] == "normal":
        return buy is None and ante is None
    if case["kind"] == "ante":
        return source["observed_ante_binding"] and buy is None and ante is not None
    if not source["observed_purchase_binding"] or ante is not None or buy is None:
        return False
    style = source["purchase_style"]
    if style == "typed":
        return buy.get("freegame") == "true" and buy.get("type") is not None
    expected = {"fixed_zero": {"freegame": "true", "type": "0"}, "untyped_freegame": {"freegame": "true"},
                "untyped_bonus_game": {"bonus_game": "true"}}
    return buy.attrib == expected.get(style)


def next_control(previous, request, line, source, count, target):
    state, status = previous.find("state").get("current_state"), previous.get("status")
    command = request.get("command")
    bet = request.find("bet")
    if state == "choice":
        offered = previous.find(".//player_choice")
        selected = request.find("player_choice")
        if (command != "game" or source.get("choice_action") != "game" or offered is None
                or selected is None or bet is None or bet.get("cash") != str(line)):
            return None
        choices = offered.get("types", "").split(",")
        wanted = str(target) if target is not None else choices[0]
        return ("player_choice", wanted) if wanted in choices and selected.get("type") == wanted else None
    if status == "next":
        return ("cascade_next", None) if command == "next" and bet is not None and bet.get("cash") == str(line) else None
    if state == "bonus" and status in ("bonus", "ok"):
        action = request.find("action")
        expected = str(count + 1) if source["bonus_round_counter"] else None
        return ("bonus", None) if command == "bonus" and (action.get("round") if action is not None else None) == expected else None
    if state == "fs" and int(previous.find("game").get("bonus_games", "0")) > 0:
        return ("free_bet", None) if command == "bet" and bet is not None and bet.get("cash") == str(line) else None
    return None


def audit_mode(saved, pairs, initial, quote, source, contract):
    key, _, choice = saved["mode"].partition("/Choice:")
    target = int(choice) if choice else None
    before = None
    for offset, (_, request, reply) in enumerate(pairs):
        if reply is None:
            before = None
            continue
        game, wallet, state = reply.find("game"), reply.find("user_new"), reply.find("state")
        if wallet is None or state is None:
            continue
        opening = before
        before = contract.amount(wallet.get("cash")) if state.get("current_state") == "idle" and reply.get("status") in ("ok", "bet") else None
        if game is None or request.get("command") != "bet" or opening != saved["before_minor"]:
            continue
        try:
            case = contract.start_case(initial, reply, request, opening, quote_data=quote)
        except (ValueError, AttributeError, TypeError):
            continue
        if case["mode"] != key or case["cost_minor"] != saved["cost_minor"] or not case["minimum_observed"] or not entry_style(request, case, source):
            continue
        previous = reply
        bonus = 0
        seen_choice = False
        for _, continuation, result in pairs[offset + 1:]:
            if previous.find("state").get("current_state") == "idle":
                break
            if continuation is None or result.find("user_new") is None:
                break
            if continuation.get("command") == "sync":
                session = previous.get("session")
                if (session and continuation.get("session") == result.get("session") == session
                        and result.get("command") == "sync" and result.get("status") == "ok"
                        and result.find("user_new").get("cash") == previous.find("user_new").get("cash")):
                    continue
                break
            if result.find("state") is None or (result.find("game") is None
                    and (continuation.get("command") != "bonus" or result.find("bonus") is None)):
                break
            follow = next_control(previous, continuation, case["line_bet_minor"], source, bonus, target)
            if not follow:
                break
            kind, selected = follow
            if selected is not None and result.find("game").get("player_choice_type") != selected:
                break
            seen_choice |= selected is not None
            bonus += kind == "bonus"
            previous = result
            case["steps"].append(contract.snapshot(result, kind))
        contract.settle(case)
        if (case["passed"] and len(case["steps"]) == len(saved["steps"]) and (target is None or seen_choice)
                and all(case[field] == saved[field] for field in ("before_minor", "after_minor", "cost_minor", "win_minor"))):
            return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("contracts", type=Path)
    parser.add_argument("bindings", type=Path)
    parser.add_argument("plan", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.contracts.resolve()))
    import playson_contract as contract
    from playson_source import inspect_bet_builders

    a = args.archive
    active = read(args.bindings)
    fallback = {row["slug"]: row for row in read(a / "resolved-new-bindings.json")}
    added, missing = [], []
    for omit in read(args.plan)["coverage"]["omitted_modes"]:
        if omit["provider"] != "playson":
            continue
        slug, key = omit["game"], omit["mode"]
        source_file = a / "bindings" / (slug + ".json")
        raw = read(source_file) if source_file.is_file() else fallback.get(slug)
        possible = [a / "campaign" / slug, *sorted((a / "independent-runs" / slug).iterdir())]
        for folder in possible:
            required = [folder / name for name in ("financial-checkpoint.json", "initialization-private.json", "private-wire.jsonl")]
            if not raw or not all(path.is_file() for path in required):
                continue
            proof, saved_init = read(required[0]), read(required[1])
            saved = next((case for case in proof["cases"] if case["mode"] == key and case.get("passed") is True
                          and not case.get("demo_reconnect_adjustment_minor")), None)
            if not saved:
                continue
            record = source_binding(a, slug, saved_init, proof, raw, inspect_bet_builders)
            if record is None or (slug in active and active[slug]["source_sha256"] != record["source_sha256"]):
                continue
            initial = contract.parse(saved_init["text"])
            wallet = initial.find("user_new")
            observed_currency = wallet.get("currency") or wallet.get("currency_code") or wallet.get("currency-id")
            # Match the published public TEST currency, also used when the response omits it.
            if observed_currency not in (None, "EUR"):
                continue
            record.update(currency="EUR", currency_decimals=2)
            if proof["quote"].get("ante_domain_origin") == "native_client_config":
                record["native_ante_multipliers"] = proof["quote"]["ante_multipliers"]
            try:
                q = contract.quote(initial, record.get("native_multiplier"), record.get("native_ante_multipliers"))
                pairs = list(entries(required[2], contract.parse))
                passed = audit_mode(saved, pairs, initial, q, record, contract)
                # Some archived TEST games accepted a bare bonus command even when
                # their client could attach a counter. Require the full same-mode receipt.
                bare_bonus = not passed and record["bonus_round_counter"] and audit_mode(
                    saved, pairs, initial, q, {**record, "bonus_round_counter": False}, contract
                )
            except (ValueError, TypeError, AttributeError, OSError):
                continue
            if not passed and not bare_bonus:
                continue
            if slug in active:
                record = {**record, **active[slug]}
            record["verified_modes"] = sorted(set(record.get("verified_modes", [])) | {key})
            if bare_bonus:
                record["bare_bonus_modes"] = sorted(set(record.get("bare_bonus_modes", [])) | {key})
            parent, separator, target = key.partition("/Choice:")
            if separator:
                record.setdefault("extra_choice_modes", []).append({"mode": key, "base_mode": parent, "target_choice": int(target)})
            active[slug] = record
            added.append([slug, key])
            break
        else:
            missing.append([slug, key])
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(active, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"added": len(added), "selectors": added, "unmapped": missing}))


if __name__ == "__main__":
    main()
