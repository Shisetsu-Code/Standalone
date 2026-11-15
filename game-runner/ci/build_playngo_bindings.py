"""Embed the public launch identities and source hashes of reconciled slots."""
import argparse
import json
from pathlib import Path
import re


def read(path):
    return json.loads(path.read_bytes())


def collect(root, traces):
    catalog = {str(row["id"]): row for row in read(root / "catalog.json")}
    result = {}
    for inventory in sorted((root / "batches").glob("*/inventory.json")):
        slots = {str(row["id"]): row for row in read(inventory) if row.get("game_type") == "slot"}
        verified = set(read(inventory.with_name("audit.json"))["verified_case_ids"])
        for receipt in read(inventory.with_name("rounds.json")):
            game = str(receipt["id"])
            if game not in slots or receipt["case"] not in verified or receipt.get("status") != "completed":
                continue
            native_mode = receipt["case"].rsplit("--", 1)[-1]
            row = slots[game]
            if native_mode not in ("normal", "go-ultra") or native_mode not in row["modes"]:
                continue
            source, gid = row["source_sha256"], catalog[game]["gid"]
            if not gid and traces is not None:
                path = traces / inventory.parent.name / "traces" / (receipt["case"] + ".json")
                if path.is_file():
                    trace = read(path)
                    authority = trace["authority"]
                    if (trace["summary"]["case"] == receipt["case"]
                            and trace["summary"]["wallet_check"] == "match"
                            and str(authority["game_id"]) == game and authority["practice"] == 1
                            and authority["demo"] == 2 and trace["profile_proof"]["sha256"] == source):
                        gid = authority["gid"]
            if not isinstance(gid, str) or not re.fullmatch(r"[a-z0-9]+", gid):
                print(f"Missing reviewed public GID: {game} {native_mode}")
                continue
            if (not re.fullmatch(r"[0-9a-f]{64}", source)
                    or receipt["wallet_check"] != "match"
                    or receipt["balance_before_native"] - receipt["cost_native"] + receipt["win_native"]
                    != receipt["balance_after_native"]):
                raise ValueError(f"invalid reviewed binding: {game} {native_mode}")
            record = result.setdefault(game, {"gid": gid, "source_sha256": source, "modes": []})
            if record["gid"] != gid or record["source_sha256"] != source or native_mode in record["modes"]:
                raise ValueError(f"ambiguous reviewed binding: {game} {native_mode}")
            record["modes"].append(native_mode)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog_archive", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--traces", type=Path)
    options = parser.parse_args()
    records = collect(options.catalog_archive, options.traces)
    with options.output.open("x", encoding="utf-8") as file:
        json.dump(records, file, indent=2, sort_keys=True)
        file.write("\n")
    print(f"{len(records)} games / {sum(len(row['modes']) for row in records.values())} modes")
