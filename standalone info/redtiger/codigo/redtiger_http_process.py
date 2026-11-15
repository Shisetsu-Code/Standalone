"""One direct HTTP session for the owning Red Tiger demo round."""
import json
import ssl
import sys

import requests


MAX_BODY = 16 * 1024 * 1024


def main():
    with requests.Session() as session:
        session.trust_env = False
        # requests' certifi resource must stay addressable inside the standard-library ZIP.
        import pkgutil
        cafile = "redtiger-ca.pem"
        with open(cafile, "xb") as root_list:
            root_list.write(pkgutil.get_data("certifi", "cacert.pem"))
        session.verify = cafile
        for line in sys.stdin.buffer:
            q = json.loads(line)
            try:
                with session.request(q["method"], q["url"], headers=q["headers"],
                                     data=q["body"] if q["body"] else None,
                                     timeout=q["timeout"], allow_redirects=False, stream=True) as response:
                    payload = bytearray()
                    headers = {k.lower(): v for k, v in response.headers.items()}
                    try:
                        for part in response.iter_content(65536):
                            room = MAX_BODY - len(payload)
                            payload.extend(part[:room])
                            if len(part) > room:
                                headers["x-evidencia-body-completeness"] = "size_limit"
                                break
                    except requests.RequestException:
                        headers["x-evidencia-body-completeness"] = "interrupted"
                    result = {"status": response.status_code, "headers": headers,
                              "set_cookies": response.raw.headers.getlist("Set-Cookie"),
                              "body": payload.decode("utf-8", errors="replace")}
            except (requests.RequestException, ssl.SSLError) as error:
                result = {"error": type(error).__name__}
            print(json.dumps(result, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
