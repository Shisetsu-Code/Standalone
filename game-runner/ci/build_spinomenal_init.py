"""Export reviewed public Spinomenal configuration without demo session state."""
import argparse
import json
from pathlib import Path


CORE = "https://rgs-ld-demo-core.spinomenal.com/api/"
ROUTES = {
    "StartUrl": "StartSlotMachine",
    "ProcessUrl": "ProcessSlotMachine",
    "BuyFeatureUrl": "BuyFeature",
    "PickFreeSpinsUrl": "PickFreeSpins",
    "FreeSpinsGambleUrl": "Gamble",
}
OFFER_FIELDS = {
    "BuyFeatures": ("BuyFeatureCost", "FreeSpinAmount", "FreeSpinType", "BuyFeatureType"),
    "BuyBonusOptions": ("BuyFeatureCost", "BonusType"),
}


def export(root, bindings):
    result = {}
    for index in sorted((root / "inventory").glob("*.json")):
        row = json.loads(index.read_bytes())
        game = row.get("gameCode")
        if game not in bindings:
            continue
        source = json.loads((root / "inventory-private" / index.name).read_bytes())
        data = source["Result"]
        info = data["GameInfo"]
        if (source["ResultInfo"]["Code"] != 0
                or info.get("GameName") != row.get("returnedName")
                or not any(attempt.get("gameCode") == game and attempt.get("status") == 200
                           and attempt.get("resultCode") == 0 for attempt in row["attempts"])):
            raise ValueError(f"unverified public configuration: {game}")
        routes = {key: data["Urls"][key] for key, route in ROUTES.items()
                  if data["Urls"].get(key) == CORE + route}
        if not {"StartUrl", "ProcessUrl"}.issubset(routes):
            raise ValueError(f"missing reviewed service route: {game}")
        public = {"BuyFeatureCost": info.get("BuyFeatureCost")}
        if isinstance(info.get("BuyFeatureLayouts"), dict):
            public["BuyFeatureLayouts"] = {"LayoutType": info["BuyFeatureLayouts"].get("LayoutType")}
        for key, fields in OFFER_FIELDS.items():
            public[key] = [{field: offer[field] for field in fields if field in offer}
                           for offer in info.get(key) or []]
        entry = {"GameInfo": public, "Urls": routes}
        if game in result and result[game] != entry:
            raise ValueError(f"conflicting public configurations: {game}")
        result[game] = entry
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("archive", "bindings", "output"):
        parser.add_argument(argument, type=Path)
    args = parser.parse_args()
    bindings = json.loads(args.bindings.read_bytes())
    public = export(args.archive, bindings)
    if set(public) != set(bindings):
        raise ValueError("public configuration coverage differs from the reviewed bindings")
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(public, output, sort_keys=True, separators=(",", ":"))
        output.write("\n")
    print(f"{len(public)} public game configurations")
