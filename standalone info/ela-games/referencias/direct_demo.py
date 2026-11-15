"""Probe the remaining demo rounds using direct HTTP and Socket.IO."""
import json
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen

import websocket

HOST = "preprod.elaapi.com"


class Demo:
    def __init__(self, url):
        with urlopen(url, timeout=15) as response:
            target = urlsplit(response.url)
        if (target.scheme, target.hostname, target.path) != ("https", HOST, "/launcher/"):
            raise ValueError("Unexpected demo redirect")
        self.session = parse_qs(target.query)["session"][0]
        self.socket = websocket.create_connection(
            f"wss://{HOST}/gateway-game/socket.io/?" + urlencode(
                {"session": self.session, "EIO": 4, "transport": "websocket"}),
            timeout=15,
        )

    def receive(self):
        while True:
            frame = self.socket.recv()
            if frame.startswith("2"):
                self.socket.send("3" + frame[1:])
            else:
                return frame

    def event(self, name, request=None):
        data = {"session": self.session}
        if request is not None:
            data["request"] = request
        self.socket.send("420" + json.dumps([name, data]))
        while True:
            frame = self.receive()
            if frame.startswith("42["):
                event, body = json.loads(frame[2:])
                if event in ("message", "exception"):
                    return event, body

    def start(self):
        if not self.receive().startswith("0"):
            raise ValueError("Engine.IO handshake missing")
        self.socket.send("40")
        while not self.receive().startswith("40"):
            pass
        event, data = self.event("start")
        if event != "message" or data.get("sessionMode") != "DEMO":
            raise ValueError("DEMO mode not confirmed")
        return data

def verify(url, feature):
    row = {"url": url, "feature": feature, "transport": "http+ws", "steps": []}
    demo = Demo(url)
    try:
        config = demo.start()
        if feature not in config["buyFeatures"]:
            raise ValueError("Purchase variant changed")
        before = config["wallet"]["balance"]
        settings = config["result"]["settings"]
        bet = settings["bet"]["defaultBet"]
        stake_factor = settings["info"]["totalBetFactor"]
        request = {"action": "spin", "bet": bet, "buyFeature": feature["type"]}
        for _ in range(120):
            event, data = demo.event("play", request)
            result = data.get("result") or {}
            state = result.get("state") or {}
            mode = result.get("nextMode") or state.get("mode") or result.get("mode")
            options = result.get("interactive") or {}
            balance = (data.get("wallet") or {}).get("balance")
            row["steps"].append({"request": request, "event": event, "mode": mode,
                                 "balance": balance, "ended": result.get("ended"),
                                 "round_win": result.get("roundTotalWin"),
                                 "real_win": result.get("round_real_win"),
                                 "spin_uid": bool(data.get("spin_uid")),
                                 "options": list(options)})
            if event != "message" or not data.get("spin_uid"):
                row["status"] = "server_exception"
                row["code"] = data.get("code")
                return row
            if len(row["steps"]) == 1:
                row["initial_balance"] = before
                row["cost"] = bet * stake_factor * feature["betsCount"]
                row["stake_factor"] = stake_factor
                row["result_total_bet"] = result["totalBet"]
                row["entry_debit"] = before - balance
            if options:
                choice = "collect" if "collect" in options else next(iter(options))
                request = {"action": "pick", "bet": bet, "userInput": {"interactive": choice}}
            elif result.get("ended") is True and mode in (None, "base"):
                win = result.get("round_real_win", result.get("roundTotalWin"))
                row["expected_balance"] = before - row["cost"] + win
                row["status"] = ("verified" if balance == row["expected_balance"]
                                 and row["entry_debit"] == row["cost"] else "balance_mismatch")
                return row
            elif mode in {"freeSpin", "superFreeSpin", "reSpin", "freeSpinReSpin",
                          "superFreeSpinReSpin", "collect", "featureFreeSpin", "freeSpinIntro"}:
                request = {"action": mode, "bet": bet}
            else:
                row["status"] = "continuation_unknown"
                return row
        row["status"] = "step_limit"
        return row
    finally:
        demo.socket.close()


if __name__ == "__main__":
    from pathlib import Path

    root = Path(__file__).resolve().parent
    browser = [json.loads(line) for line in (root / "purchase-closures.jsonl").read_text().splitlines()]
    output = root / "purchase-http-ws.jsonl"
    direct = [json.loads(line) for line in output.read_text().splitlines()] if output.exists() else []
    rows = {(row["url"], row["feature"]["type"]): row for row in browser + direct}
    with output.open("a", encoding="utf-8") as report:
        for row in rows.values():
            if row["status"] == "verified":
                continue
            try:
                result = verify(row["url"], row["feature"])
            except (OSError, websocket.WebSocketException, ValueError) as error:
                result = {"url": row["url"], "feature": row["feature"],
                          "status": type(error).__name__}
            report.write(json.dumps(result) + "\n")
            report.flush()
            print(result["url"].rsplit("/", 1)[-1], result["feature"]["type"],
                  result["status"], result.get("expected_balance"), flush=True)

