"""Red Tiger public-demo bootstrap using a fresh HTTP session."""
import json
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit
from uuid import uuid4

from collection_launch import check_launch_response, finish_launch

_ENTRY_ORIGIN = "https://fansite.evo-games.com"
_ISSUER = "https://jinx.prod.cmsevo.com/api/v1/oss/token/demo"
_CLIENT_VERSION = "6.20261113.73039.67536-2dc7fa4ff6-r2"
_CLIENT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) hardfire/1.5.1 Chrome/152.0.7977.130 Electron/44.5.1 Safari/537.36"
)
# Public frontend identifier from the official demo issuer request.
_PUBLIC_FRONTEND = "ATp3ZRaTE2u22oTM6GXmHtkgWYc6F8vZ"


def official_url(url, allow_frontend=False):
    parsed = urlsplit(url)
    path = parsed.path
    if parsed.scheme != "https" or parsed.netloc != "fansite.evo-games.com" or not (
        path == "/entry" or (allow_frontend and path.startswith("/frontend/evo/"))
    ):
        raise ValueError("redtiger_unexpected_entry_redirect")
    return path


def _templates():
    override = os.environ.get("REDTIGER_DEMO_TEMPLATE_HAR")
    if not override:
        headers = [{"name": key, "value": value} for key, value in {
            "accept": "*/*", "accept-language": "es", "user-agent": _CLIENT_UA,
        }.items()]
        query = urlencode({"client_version": _CLIENT_VERSION})
        return {
            ("POST", "/api/v1/oss/token/demo"): {
                "headers": headers + [{"name": key, "value": value} for key, value in {
                    "origin": "https://redtiger.com", "referer": "https://redtiger.com/",
                    "x-api-key": _PUBLIC_FRONTEND,
                }.items()],
                "postData": {"text": json.dumps({"demo": {"language": "en-GB", "currency": "VC0"}})},
            },
            ("GET", "/setup"): {
                "headers": headers, "url": f"{_ENTRY_ORIGIN}/setup?device=desktop&wrapped=false&locale=en-GB&{query}",
            },
            ("GET", "/config"): {"headers": headers, "url": f"{_ENTRY_ORIGIN}/config?{query}"},
            ("POST", "/platform/game/settings"): {
                "headers": headers, "postData": {"text": json.dumps({"listenToFrontend": True})},
            },
        }
    path = Path(override)
    if not path.is_file():
        raise ValueError("redtiger_demo_template_missing")
    wanted = {("POST", "/api/v1/oss/token/demo"), ("GET", "/setup"),
              ("GET", "/config"), ("POST", "/platform/game/settings")}
    result = {}
    for entry in json.loads(path.read_text(encoding="utf-8-sig"))["log"]["entries"]:
        request = entry["request"]
        parsed = urlsplit(request["url"])
        for method, suffix in wanted:
            key = (method, suffix)
            if request["method"] == method and parsed.path.endswith(suffix) and entry["response"]["status"] == 200:
                result.setdefault(key, request)
    if result.keys() != wanted:
        raise ValueError("redtiger_demo_template_incomplete")
    return result


def _headers(request, names):
    return {h["name"]: h["value"] for h in request["headers"] if h["name"].lower() in names.split()}


def bootstrap(session, table, journal):
    """Return fresh session data. Capture templates supply only public launch fields."""
    if not isinstance(table, str) or not table or not table.isascii() or not table.isalnum():
        raise ValueError("invalid_redtiger_table_id")
    templates = _templates()

    def call(method, url, **kwargs):
        response = session.request(method, url, timeout=15, allow_redirects=False, **kwargs)
        parsed = urlsplit(url)
        journal.event(event="redtiger_http_bootstrap", method=method, host=parsed.hostname,
                      path=parsed.path, status=response.status_code, reference=response.headers.get("akamai-grn"))
        if response.status_code in (403, 429, 503):
            if response.status_code != 403 or "challenge" not in response.headers.get("cf-mitigated", "").lower():
                check_launch_response(response.status_code)
        return response

    def require_ok(response):
        if response.status_code != 200:
            raise BootstrapStatus(response.status_code)
        return response

    launch = f"https://redtiger.com/demo/{table}?showNavbar=true"
    require_ok(call("GET", launch))
    issuer = templates["POST", "/api/v1/oss/token/demo"]
    defaults = json.loads(issuer["postData"]["text"])["demo"]
    body = {"demo": {k: defaults[k] for k in ("language", "currency")}, "game": {"tableId": table}}
    launch_headers = _headers(issuer, "origin referer user-agent x-api-key accept accept-language")
    config = require_ok(call("POST", _ISSUER, json=body, headers=launch_headers)).json()
    url = urljoin(_ENTRY_ORIGIN + "/", config["entryEmbedded"])
    for hop in range(4):
        path = official_url(url, allow_frontend=hop > 0)
        response = call("GET", url, headers={
            **_headers(issuer, "user-agent"), "Referer": launch,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "iframe",
        })
        if not response.is_redirect:
            require_ok(response)
            if path.startswith("/frontend/evo/"):
                break
            raise ValueError("redtiger_frontend_not_reached")
        url = urljoin(url, response.headers["Location"])
    else:
        raise ValueError("redtiger_entry_redirect_limit")

    for path in ("/setup", "/config"):
        request = templates["GET", path]
        fields = {"client_version", "device", "wrapped", "locale", "table_id"}
        query = {key: table if key == "table_id" else value
                 for key, value in parse_qsl(urlsplit(request["url"]).query) if key in fields}
        if path == "/config":
            query["table_id"] = table
        response = require_ok(call("GET", f"{_ENTRY_ORIGIN}{path}?{urlencode(query)}",
                                   headers={**_headers(request, "accept accept-language user-agent sec-fetch-site sec-fetch-dest sec-fetch-mode"),
                                            "Referer": url}))
    config = response.json()
    launch_params = config["wrappedLaunchParams"]
    game = launch_params["gameId"]
    if config.get("table_id") != table or not game or config.get("base_game_id") != game:
        raise ValueError("redtiger_demo_game_identity_changed")
    base = launch_params["baseUrl"].rstrip("/")
    parsed = urlsplit(base)
    if (parsed.scheme != "https" or not (parsed.hostname or "").endswith(".redtiger.cash")
            or parsed.netloc != parsed.hostname or parsed.query or parsed.fragment):
        raise ValueError("redtiger_demo_settings_origin_invalid")
    request = templates["POST", "/platform/game/settings"]
    listen = json.loads(request["postData"]["text"])["listenToFrontend"]
    params = dict(token=None, playMode="demo", sessionId=launch_params["token"], gameId=game,
                  listenToFrontend=listen,
                  custom={"siteId": launch_params["casino"], "context": {"ne_evo_token": launch_params["ne_evo_token"]}},
                  userData={"userId": "0", "fingerprint": uuid4().hex,
                            "lang": launch_params["lang"], "channel": launch_params["channel"]})
    if not params["sessionId"]:
        raise ValueError("redtiger_demo_session_missing")
    endpoint = base + "/platform/game/settings"
    native_headers = _headers(request, "origin user-agent")
    native_headers["origin"] = f"{parsed.scheme}://{parsed.netloc}"
    answer = require_ok(call("POST", endpoint, json=params, headers=native_headers)).json()
    user = (answer.get("result") or {}).get("user") or {}
    if answer.get("success") is not True or not user.get("token") or user.get("userId") is None:
        raise ValueError("redtiger_demo_identity_unverified")
    journal.event(event="verified_demo_bootstrap", bootstrap={
        "config_response": config, "settings_request": {"url": endpoint, "body": params},
        "settings_response": answer,
    })
    finish_launch()
    return base, native_headers, params, answer["result"]


class BootstrapStatus(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(f"remote_demo_bootstrap_http_{status}")

