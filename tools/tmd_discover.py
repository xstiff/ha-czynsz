#!/usr/bin/env python3
"""Ręczne rozpoznawanie API tomojdom.pl (Weles3).

Użycie:
  tmd_discover.py login                 — numer użytkownika + hasło (getpass) → JWT w .secrets/tmd_tokens.json
  tmd_discover.py token                 — dekoduje zapisany JWT (bez podpisu)
  tmd_discover.py js                    — pobiera moduły JS aplikacji i wypisuje endpointy API
  tmd_discover.py call <ścieżka> [json] — POST na serwer użytkownika, odpowiedź do .secrets/discovery/

Format wywołań (z WlsCore/store.js): zawsze POST, treść JSON (bez parametrów: `null`),
nagłówki `Authorization: Bearer <JWT>`, `Test: 0`, `x-weles-seq`.
"""

from __future__ import annotations

import base64
import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import LWPCookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / ".secrets"
TOKENS = SECRETS / "tmd_tokens.json"
COOKIES = SECRETS / "tmd_cookies.lwp"
DISCOVERY = SECRETS / "discovery"
JS_DIR = DISCOVERY / "js"

MAIN = "https://main.tomojdom.pl"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"


def _write_secret(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    os.chmod(path, 0o600)


# Token ma claim `fingerprint` — serwer wiąże go z ciasteczkiem ustawianym przy logowaniu.
JAR = LWPCookieJar(str(COOKIES))
if COOKIES.exists():
    JAR.load(ignore_discard=True, ignore_expires=True)
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(JAR))


def _save_cookies() -> None:
    SECRETS.mkdir(parents=True, exist_ok=True)
    JAR.save(ignore_discard=True, ignore_expires=True)
    os.chmod(COOKIES, 0o600)


def _request(url: str, body=None, token: str | None = None, raw: bool = False):
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json", "User-Agent": UA, "x-weles-seq": "1",
               "Origin": "https://tomojdom.pl", "Referer": "https://tomojdom.pl/"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["Test"] = "0"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with OPENER.open(req, timeout=30) as resp:
            content = resp.read()
            ctype = resp.headers.get("content-type", "")
            status = resp.status
    except urllib.error.HTTPError as err:
        content = err.read()
        ctype = err.headers.get("content-type", "")
        status = err.code
    _save_cookies()
    if raw:
        return status, ctype, content
    text = content.decode("utf-8", "replace")
    try:
        return status, json.loads(text)
    except ValueError:
        return status, text


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def decode_jwt(token: str) -> dict:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def server_url(srv: str | None) -> str:
    """Odpowiednik getFullUrl z logon.js."""
    if not srv:
        return MAIN
    m = re.match(r"^https://([^.]+)\.(e-adm|tomojdom)\.pl(/|$)", srv)
    name = m.group(1) if m else srv
    if name in ("libra", "scorpio", "sagittarius"):
        return MAIN
    return f"https://{name}.tomojdom.pl"


def load_tokens() -> dict:
    if not TOKENS.exists():
        sys.exit("Brak .secrets/tmd_tokens.json — uruchom najpierw: tmd_discover.py login")
    return json.loads(TOKENS.read_text())


def cmd_login() -> None:
    # Bez terminala (np. `!` w Claude Code) dane bierzemy ze zmiennych TMD_USER / TMD_PASS.
    user = os.environ.get("TMD_USER") or input("Numer użytkownika: ").strip()
    password = os.environ.get("TMD_PASS") or getpass.getpass("Hasło: ")
    status, resp = _request(f"{MAIN}/login/OsLogInPass", {"User": int(user), "Pass": password})
    if status != 200 or not isinstance(resp, list):
        sys.exit(f"Logowanie nieudane: HTTP {status}: {str(resp)[:300]}")
    token = resp[2]
    claims = decode_jwt(token)
    _write_secret(TOKENS, {"user": int(user), "srv": resp[1], "jwt": token,
                           "change_pass": resp[3], "len": len(resp)})
    # Zapamiętujemy tylko kształt odpowiedzi (bez wartości) do analizy.
    print(f"OK. Serwer: {resp[1]!r}, wymagana zmiana hasła: {resp[3]!r}, pól w odpowiedzi: {len(resp)}")
    print(f"Klucze JWT: {sorted(claims)}")
    print(f"aud: {claims.get('aud')}, ttl: {claims.get('ttl')} min")
    print("Ciasteczka:", [(c.domain, c.name, c.discard) for c in JAR])


def cmd_token() -> None:
    tok = load_tokens()
    claims = decode_jwt(tok["jwt"])
    for k, v in claims.items():
        print(f"{k}: {str(v)[:120]}")


IMPORT_RE = re.compile(r"""(?:from\s*|import\s*\(\s*)["'](\.{1,2}/[^"']+\.js)["']""")
ENDPOINT_RE = re.compile(r"""n\("(/[^"]+)","([^"]*)\"""")


def cmd_js() -> None:
    # Moduły JS są publiczne, więc token nie jest wymagany (bez niego bierzemy /app/).
    aud = decode_jwt(load_tokens()["jwt"]).get("aud", "") if TOKENS.exists() else ""
    origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(aud)) if aud else "https://tomojdom.pl"
    html = _get(aud or "https://tomojdom.pl/app/")
    JS_DIR.mkdir(parents=True, exist_ok=True)
    (JS_DIR / "app.html").write_text(html)
    entries = re.findall(r'entrypoint="([^"]+)"', html)
    print(f"aud: {aud}\nentrypoint: {entries}")
    queue = [f"{origin}/jsnew/es/{e.lstrip('/')}" for e in entries]
    seen: set[str] = set()
    endpoints: dict[str, tuple[str, str]] = {}
    while queue:
        url = queue.pop()
        if url in seen:
            continue
        seen.add(url)
        try:
            src = _get(url)
        except urllib.error.URLError as err:
            print(f"  ! {url}: {err}")
            continue
        rel = url.split("/jsnew/es/", 1)[-1]
        out = JS_DIR / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(src)
        for imp in IMPORT_RE.findall(src):
            queue.append(urllib.parse.urljoin(url, imp))
        for path, desc in ENDPOINT_RE.findall(src):
            endpoints[path] = (desc, rel)
    print(f"Pobrano {len(seen)} modułów do {JS_DIR.relative_to(ROOT)}")
    lines = [f"{p}\t{d}\t{f}" for p, (d, f) in sorted(endpoints.items())]
    (DISCOVERY / "endpoints.tsv").write_text("\n".join(lines))
    print("\n".join(lines))


def cmd_call(path: str, body_json: str | None) -> None:
    tok = load_tokens()
    body = json.loads(body_json) if body_json else None
    base = server_url(tok.get("srv"))
    status, ctype, content = _request(f"{base}{path}", body, tok["jwt"], raw=True)
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", path.strip("/")) or "root"
    ext = ".json" if "json" in ctype or content[:1] in (b"[", b"{") else ".bin"
    out = DISCOVERY / f"{name}{ext}"
    out.write_bytes(content)
    os.chmod(out, 0o600)
    print(f"HTTP {status} {ctype} {len(content)} B → {out.relative_to(ROOT)}")


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == "login":
        cmd_login()
    elif cmd == "token":
        cmd_token()
    elif cmd == "js":
        cmd_js()
    elif cmd == "call" and len(sys.argv) >= 3:
        cmd_call(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
