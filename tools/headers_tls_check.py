"""Edge checks for the maintenance calendar: TLS + headers (M3), DNS (Q4), Observatory (Q5), uptime reader (C1).

    py tools/headers_tls_check.py tls          # M3 monthly: cert days-to-expiry, HTTP->HTTPS, header diff, mixed content
    py tools/headers_tls_check.py dns          # Q4 quarterly: records point at GitHub Pages, no wildcard, TXT, Enforce HTTPS
    py tools/headers_tls_check.py observatory  # Q5 quarterly: MDN HTTP Observatory v2 (refuses unless MAINT_OBSERVATORY_OK=1)
    py tools/headers_tls_check.py uptime       # C1 reader for the W2 digest (needs UPTIMEROBOT_API_KEY, read-only key)

Every run writes one receipt through tools/maint_receipt.py (PASS / FINDINGS n / UNKNOWN <why>) and its evidence
under `.maint/` (git-ignored). Exit 0 = PASS, 1 = FINDINGS, 2 = UNKNOWN. UNKNOWN never rounds to PASS: a probe that
could not run (no network, no gh, no key, no OK) is UNKNOWN, never a pass.

Sources (read 2026-10-31):
- GitHub Pages apex A/AAAA and the www CNAME target `<owner>.github.io`, and "do not use wildcard DNS records":
  docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site
- Verification TXT name `_github-pages-challenge-<owner>.<domain>`:
  docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/verifying-your-custom-domain-for-github-pages
- Observatory v2: `POST https://observatory-api.mdn.mozilla.net/api/v2/scan?host=<host>`, "the scan history for each
  domain is public": developer.mozilla.org/en-US/observatory/docs/faq and github.com/mdn/mdn-http-observatory/wiki
- UptimeRobot getMonitors (`POST https://api.uptimerobot.com/v2/getMonitors`, api_key in the body,
  custom_uptime_ratios=7, status 0 paused / 1 not checked yet / 2 up / 8 seems down / 9 down; a read-only key works
  with every get* method): uptimerobot.com/api/legacy/

The 14-day certificate threshold is [ASSUMED] and Daniel's to rule (CALENDAR M3).
No secrets are printed or written: the UptimeRobot key and the TXT record's value never leave memory.
"""
from __future__ import annotations

import argparse
import datetime as dt
import http.client
import json
import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import maint_receipt  # noqa: E402
import site_pages  # noqa: E402

TOOL = "headers_tls_check.py"
HOST = "b4him.com"
OWNER = "Sobevista"
REPO_SLUG = "Sobevista/b4him"
UA = "b4him-maint"
CERT_S1_DAYS = 14  # [ASSUMED] threshold, Daniel's to rule
ROUTE_S1 = "Release Manager + Daniel"
ROUTE_SITE = "Site Maintainer"
ROUTE_DNS = "Daniel (registrar)"

# GitHub's documented Pages addresses (managing-a-custom-domain page, read 2026-10-31).
PAGES_A = {"185.199.108.153", "185.199.109.153", "185.199.110.153", "185.199.111.153"}
PAGES_AAAA = {"2606:50c0:8000::153", "2606:50c0:8001::153", "2606:50c0:8002::153", "2606:50c0:8003::153"}

OBSERVATORY_URL = "https://observatory-api.mdn.mozilla.net/api/v2/scan"
ANALYZE_URL = "https://observatory-api.mdn.mozilla.net/api/v2/analyze"
#: Q5's row text: frame-ancestors "cannot be fixed that way [a meta tag]: a known limit, recorded and not re-filed every
#: quarter". Observatory's x-frame-options test passes only on an X-Frame-Options header or a CSP frame-ancestors
#: directive, and GitHub Pages lets the site set neither [ASSUMED: the test-name mapping].
KNOWN_LIMIT_TESTS = {"x-frame-options": "needs an X-Frame-Options header or CSP frame-ancestors; GitHub Pages cannot "
                                        "set response headers and frame-ancestors is ignored in a <meta> CSP"}
KNOWN_LIMITS = "q5_known_limits.json"
UPTIMEROBOT_URL = "https://api.uptimerobot.com/v2/getMonitors"
UR_STATUS = {0: "paused", 1: "not checked yet", 2: "up", 8: "seems down", 9: "down"}

# Headers that change on every response; they are kept in the snapshot but not diffed.
VOLATILE = {"date", "age", "expires", "last-modified", "etag", "x-served-by", "x-cache", "x-cache-hits", "x-timer",
            "x-github-request-id", "x-fastly-request-id", "via", "x-proxy-cache", "content-length", "cf-ray"}


def repo() -> Path:
    return maint_receipt.REPO


def maint() -> Path:
    return maint_receipt.maint_dir()


def today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def _rel(p: Path) -> str:
    """Evidence as maint_receipt wants it: `.maint/<path inside the maintenance dir>` (MAINT_DIR may sit elsewhere)."""
    try:
        return ".maint/" + p.resolve().relative_to(maint().resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def _write_json(p: Path, obj) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return p


class Result:
    """Collects findings and unknowns for one row, then writes the receipt."""

    def __init__(self, row: str):
        self.row, self.findings, self.unknowns, self.notes = row, [], [], []

    def find(self, severity: str, subject: str, detail: str = "", route_to: str = ROUTE_SITE):
        self.findings.append({"severity": severity, "subject": subject, "detail": detail, "route_to": route_to})

    def unknown(self, why: str):
        self.unknowns.append(why)

    def close(self, evidence: Path | None, extra_why: str = "") -> dict:
        for f in self.findings:
            maint_receipt.write_finding(self.row, f["severity"], f["subject"], f["detail"], f["route_to"])
        parts = [extra_why] if extra_why else []
        if self.findings:
            outcome, n = "FINDINGS", len(self.findings)
            parts.append("; ".join(f"{f['severity']} {f['subject']}" for f in self.findings))
            if self.unknowns:
                parts.append("also UNKNOWN: " + "; ".join(self.unknowns))
        elif self.unknowns:
            outcome, n = "UNKNOWN", None
            parts.append("; ".join(self.unknowns))
        else:
            outcome, n = "PASS", 0
        return maint_receipt.write_receipt(self.row, outcome, n=n, why=" | ".join(p for p in parts if p),
                                           evidence=_rel(evidence) if evidence else None, tool=TOOL)


# ---------------------------------------------------------------- network probes (tests replace these)

class LocalNetworkError(Exception):
    """The probe could not even resolve the name: the machine's network, not the site. UNKNOWN, never S1."""


def probe_cert(host: str, timeout: float = 15) -> dict:
    """Verified TLS handshake on 443. Returns {"not_after": str, "issuer": str}. Raises ssl.SSLError on a bad cert."""
    try:
        socket.getaddrinfo(host, 443)
    except socket.gaierror as e:
        raise LocalNetworkError(f"cannot resolve {host}: {e}") from e
    ctx = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            cert = tls.getpeercert()
    issuer = ", ".join("=".join(kv) for rdn in cert.get("issuer", ()) for kv in rdn)
    return {"not_after": cert["notAfter"], "issuer": issuer}


def probe_http(url: str, method: str = "HEAD", timeout: float = 20) -> dict:
    """One request without following redirects. Returns {"status": int, "headers": {lower: value}}."""
    u = urllib.parse.urlsplit(url)
    try:
        socket.getaddrinfo(u.hostname, None)
    except socket.gaierror as e:
        raise LocalNetworkError(f"cannot resolve {u.hostname}: {e}") from e
    cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
    conn = cls(u.hostname, u.port, timeout=timeout)
    try:
        conn.request(method, u.path or "/", headers={"User-Agent": UA, "Cache-Control": "no-cache"})
        r = conn.getresponse()
        r.read()
        headers: dict[str, str] = {}
        for k, v in r.getheaders():
            k = k.lower()
            headers[k] = f"{headers[k]}, {v}" if k in headers else v
        return {"status": r.status, "headers": headers}
    finally:
        conn.close()


def git_grep_http(root: Path) -> list[str]:
    """`git grep` for http:// in tracked HTML/CSS. Returns raw `path:line:text` lines. Raises on a git failure."""
    p = subprocess.run(["git", "-C", str(root), "grep", "-n", "-I", "-i", "http://", "--", "*.html", "*.htm", "*.css"],
                       capture_output=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    if p.returncode == 1:
        return []
    if p.returncode != 0:
        raise RuntimeError(f"git grep exit {p.returncode}: {p.stderr.strip()[:200]}")
    return p.stdout.splitlines()


def resolve(name: str, rtype: str) -> tuple[str, list[str]]:
    """("ok"|"nxdomain"|"noanswer"|"error", values). dnspython when installed, else Resolve-DnsName."""
    try:
        import dns.resolver  # type: ignore
    except ImportError:
        return _resolve_ps(name, rtype)
    try:
        ans = dns.resolver.resolve(name, rtype, raise_on_no_answer=False, lifetime=10)
    except dns.resolver.NXDOMAIN:
        return "nxdomain", []
    except Exception as e:  # NoNameservers, LifetimeTimeout, ...
        return "error", [f"{type(e).__name__}: {e}"[:200]]
    vals = []
    for rr in ans.rrset or []:
        if rtype == "TXT":
            vals.append(b"".join(rr.strings).decode("utf-8", "replace"))
        else:
            vals.append(rr.to_text())
    # resolve() follows CNAMEs for A/AAAA; for a CNAME query, only the record at the name itself is kept.
    return ("ok" if vals else "noanswer"), vals


def _resolve_ps(name: str, rtype: str) -> tuple[str, list[str]]:
    cmd = (f"try {{ Resolve-DnsName -Name '{name}' -Type {rtype} -DnsOnly -ErrorAction Stop | "
           f"Where-Object {{ $_.Type -eq '{rtype}' }} | "
           f"Select-Object IPAddress,NameHost,Strings | ConvertTo-Json -Compress }} "
           f"catch {{ 'ERR:' + $_.CategoryInfo.Reason + ':' + $_.Exception.Message }}")
    p = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True,
                       encoding="utf-8", errors="replace")
    out = p.stdout.strip()
    if out.startswith("ERR:"):
        return ("nxdomain", []) if "does not exist" in out else ("error", [out[:200]])
    if not out:
        return "noanswer", []
    data = json.loads(out)
    data = data if isinstance(data, list) else [data]
    vals = []
    for d in data:
        if d.get("IPAddress"):
            vals.append(d["IPAddress"])
        elif d.get("NameHost"):
            vals.append(d["NameHost"].rstrip(".") + ".")
        elif d.get("Strings"):
            vals.append("".join(d["Strings"]))
    return ("ok" if vals else "noanswer"), vals


def gh_pages(slug: str) -> tuple[str, dict | str]:
    """("ok", json) from `gh api repos/<slug>/pages`, or ("unknown", why). Never prints the token."""
    if not shutil.which("gh"):
        return "unknown", "gh not installed"
    p = subprocess.run(["gh", "api", f"repos/{slug}/pages"], capture_output=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8", "GH_PROMPT_DISABLED": "1"})
    if p.returncode != 0:
        return "unknown", f"gh api exit {p.returncode}: {p.stderr.strip().splitlines()[-1][:160] if p.stderr.strip() else ''}"
    try:
        return "ok", json.loads(p.stdout)
    except json.JSONDecodeError:
        return "unknown", "gh api returned non-JSON"


def http_post(url: str, data: bytes | None, headers: dict, timeout: float = 60) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=data if data is not None else b"", method="POST",
                                 headers={"User-Agent": UA, **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def http_get(url: str, timeout: float = 60) -> tuple[int, bytes]:
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


# ---------------------------------------------------------------- M3 tls

SUBRESOURCE = re.compile(
    r"""(?:\b(?:src|srcset|data|poster|background|action|formaction)\s*=\s*["']?[^"'>]*?http://"""
    r"""|<link\b[^>]*\bhref\s*=\s*["']?http://"""
    r"""|url\(\s*["']?http://"""
    r"""|@import\s+["']http://)""", re.I)


def served(path: str) -> bool:
    """GitHub Pages (Jekyll) never serves a path with a component starting with '.' or '_' (tools/site_pages.py)."""
    return site_pages.is_served(path)


def mixed_content(lines: list[str]) -> list[dict]:
    hits = []
    for line in lines:
        path, _, rest = line.partition(":")
        lineno, _, text = rest.partition(":")
        if not served(path):
            continue
        for m in SUBRESOURCE.finditer(text):
            hits.append({"path": path, "line": int(lineno) if lineno.isdigit() else None, "match": m.group(0)[:160]})
    return hits


def previous_snapshot(dirp: Path, day: dt.date) -> Path | None:
    older = sorted(p for p in dirp.glob("*.json") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem) and p.stem < day.isoformat())
    return older[-1] if older else None


def diff_headers(old: dict, new: dict) -> list[dict]:
    keys = sorted((set(old) | set(new)) - VOLATILE)
    return [{"header": k, "was": old.get(k), "now": new.get(k)} for k in keys if old.get(k) != new.get(k)]


def run_tls(host: str = HOST, day: dt.date | None = None, now: dt.datetime | None = None) -> dict:
    day = day or today()
    now = now or dt.datetime.now(dt.timezone.utc)
    res = Result("M3")
    ev: dict = {"host": host, "date": day.isoformat(), "threshold_days": CERT_S1_DAYS, "threshold_assumed": True}

    # 1. certificate
    try:
        cert = probe_cert(host)
        expires = dt.datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["not_after"]), dt.timezone.utc)
        days = (expires - now).total_seconds() / 86400
        ev["cert"] = {"not_after": cert["not_after"], "issuer": cert["issuer"], "days_left": round(days, 1)}
        if days < CERT_S1_DAYS:
            res.find("S1", f"certificate expires in {days:.1f} days", f"notAfter {cert['not_after']}", ROUTE_S1)
    except LocalNetworkError as e:
        ev["cert"] = {"error": str(e)}
        res.unknown(f"cert: {e}")
    except ssl.SSLError as e:
        ev["cert"] = {"error": f"{type(e).__name__}: {e}"}
        res.find("S1", "HTTPS failing: TLS handshake did not verify", str(e)[:200], ROUTE_S1)
    except TimeoutError as e:                  # a timeout says nothing about the site: this machine's path to it
        ev["cert"] = {"error": f"timeout: {e}"}
        res.unknown(f"cert: connect timed out ({e or 'no answer'})")
    except OSError as e:
        ev["cert"] = {"error": f"{type(e).__name__}: {e}"}
        res.find("S1", "HTTPS failing: cannot connect on 443", str(e)[:200], ROUTE_S1)

    # 2. HTTP -> HTTPS redirect, and the HTTPS page itself
    try:
        r = probe_http(f"http://{host}/")
        loc = r["headers"].get("location", "")
        ev["redirect"] = {"status": r["status"], "location": loc}
        if r["status"] not in (301, 308) or not loc.lower().startswith(f"https://{host}"):
            res.find("S1", "HTTP does not redirect permanently to HTTPS", f"status {r['status']} location {loc!r}",
                     ROUTE_S1)
    except LocalNetworkError as e:
        res.unknown(f"redirect: {e}")
    except OSError as e:
        ev["redirect"] = {"error": f"{type(e).__name__}: {e}"}
        res.unknown(f"redirect: port 80 probe failed ({type(e).__name__})")

    headers = None
    try:
        r = probe_http(f"https://{host}/", method="GET")
        ev["https"] = {"status": r["status"]}
        headers = r["headers"]
        if r["status"] != 200:
            res.find("S1", f"HTTPS home page returns {r['status']}", "", ROUTE_S1)
    except LocalNetworkError as e:
        res.unknown(f"https: {e}")
    except TimeoutError as e:
        ev["https"] = {"error": f"timeout: {e}"}
        res.unknown(f"https: GET / timed out ({e or 'no answer'})")
    except (ssl.SSLError, OSError) as e:
        ev["https"] = {"error": f"{type(e).__name__}: {e}"}
        if not any(f["subject"].startswith("HTTPS failing") for f in res.findings):
            res.find("S1", "HTTPS failing: GET / did not complete", str(e)[:200], ROUTE_S1)

    # 3. header snapshot + diff against the previous one
    hdir = maint() / "headers"
    if headers is not None:
        snap = _write_json(hdir / f"{day.isoformat()}.json", {"host": host, "url": f"https://{host}/", "headers": headers})
        ev["header_snapshot"] = _rel(snap)
        prev = previous_snapshot(hdir, day)
        if prev is None:
            ev["header_diff"] = "no previous snapshot: this one is the baseline"
        else:
            old = json.loads(prev.read_text(encoding="utf-8")).get("headers", {})
            changes = diff_headers(old, headers)
            ev["header_diff"] = {"against": _rel(prev), "changes": changes}
            for c in changes:
                res.find("S3", f"response header {c['header']} changed since {prev.stem}",
                         f"was {c['was']!r} now {c['now']!r}", ROUTE_SITE)
    else:
        ev["header_snapshot"] = None

    # 4. mixed content in the served tree
    try:
        hits = mixed_content(git_grep_http(repo()))
        ev["mixed_content"] = hits
        for h in hits:
            res.find("S2", f"http:// subresource in {h['path']}:{h['line']}", h["match"], ROUTE_SITE)
    except (OSError, RuntimeError) as e:
        ev["mixed_content"] = {"error": str(e)}
        res.unknown(f"mixed content: {e}")

    out = _write_json(maint() / "audits" / f"{day.isoformat()}_tls.json", ev)
    days_txt = f"cert {ev['cert']['days_left']} days left" if "days_left" in ev.get("cert", {}) else ""
    return res.close(out, days_txt)


# ---------------------------------------------------------------- Q4 dns

def _norm(name: str) -> str:
    return name.lower().rstrip(".")


def run_dns(host: str = HOST, owner: str = OWNER, slug: str = REPO_SLUG, day: dt.date | None = None) -> dict:
    day = day or today()
    res = Result("Q4")
    ev: dict = {"host": host, "date": day.isoformat(), "pages_a": sorted(PAGES_A), "pages_aaaa": sorted(PAGES_AAAA)}
    pages_target = f"{owner.lower()}.github.io"

    def q(name, rtype):
        st, vals = resolve(name, rtype)
        ev.setdefault("records", {})[f"{name} {rtype}"] = {"status": st, "values": vals if rtype != "TXT" else len(vals)}
        if st == "error":
            res.unknown(f"{name} {rtype}: {vals[0] if vals else 'lookup error'}")
        return st, vals

    # apex
    st, a = q(host, "A")
    if st == "ok":
        stray = sorted(set(a) - PAGES_A)
        if stray:
            res.find("S1", f"{host} A points outside GitHub Pages: {', '.join(stray)}", "", ROUTE_DNS)
    elif st in ("nxdomain", "noanswer"):
        res.find("S1", f"{host} has no A record", st, ROUTE_DNS)
    st, aaaa = q(host, "AAAA")
    if st == "ok":
        stray = sorted({x.lower() for x in aaaa} - PAGES_AAAA)
        if stray:
            res.find("S1", f"{host} AAAA points outside GitHub Pages: {', '.join(stray)}", "", ROUTE_DNS)
    st, cn = q(host, "CNAME")
    if st == "ok" and cn:
        res.find("S2", f"{host} apex carries a CNAME ({cn[0]})", "an apex CNAME is not the documented Pages setup",
                 ROUTE_DNS)

    # www
    www = f"www.{host}"
    st, cn = q(www, "CNAME")
    if st == "ok":
        if _norm(cn[0]) != pages_target:
            res.find("S1", f"{www} CNAME points at {cn[0]}, not {pages_target}", "dangling or misdirected", ROUTE_DNS)
    elif st in ("nxdomain", "noanswer"):
        st2, a2 = q(www, "A")
        if st2 == "ok":
            stray = sorted(set(a2) - PAGES_A)
            if stray:
                res.find("S1", f"{www} A points outside GitHub Pages: {', '.join(stray)}", "", ROUTE_DNS)
            else:
                res.find("S3", f"{www} uses A records, not the documented CNAME to {pages_target}", "", ROUTE_DNS)
        elif st2 == "nxdomain":
            res.find("S3", f"{www} does not exist", "GitHub recommends configuring www too", ROUTE_DNS)

    # wildcard: a random label must not resolve
    label = "maint-" + secrets.token_hex(6)
    probe = f"{label}.{host}"
    st, vals = resolve(probe, "A")
    st_c, vals_c = resolve(probe, "CNAME")
    ev["wildcard_probe"] = {"name": probe, "A": st, "CNAME": st_c}
    if st == "ok" or st_c == "ok":
        res.find("S1", f"wildcard record: random label {probe} resolves", ", ".join(vals + vals_c)[:200], ROUTE_DNS)
    elif "error" in (st, st_c):
        res.unknown(f"wildcard probe: {(vals or vals_c or ['lookup error'])[0]}")

    # verification TXT (presence only; the value is not recorded)
    txt_name = f"_github-pages-challenge-{owner.lower()}.{host}"
    st, txt = q(txt_name, "TXT")
    if st in ("nxdomain", "noanswer"):
        res.find("S2", f"verification TXT {txt_name} is missing", "an unverified domain is open to takeover", ROUTE_DNS)

    # Enforce HTTPS (from the Pages API)
    st, pages = gh_pages(slug)
    if st != "ok":
        ev["pages_api"] = {"status": "UNKNOWN", "why": pages}
        res.unknown(f"Enforce HTTPS: {pages}")
    else:
        ev["pages_api"] = {k: pages.get(k) for k in ("cname", "https_enforced", "status", "build_type",
                                                      "protected_domain_state", "pending_domain_unverified_at")}
        if pages.get("https_enforced") is not True:
            res.find("S2", "Enforce HTTPS is off in the Pages settings", f"https_enforced={pages.get('https_enforced')}",
                     ROUTE_DNS)
        if _norm(pages.get("cname") or "") != _norm(host):
            res.find("S1", f"Pages custom domain is {pages.get('cname')!r}, not {host}", "", ROUTE_S1)

    out = _write_json(maint() / "audits" / f"{day.isoformat()}_dns.json", ev)
    return res.close(out)


# ---------------------------------------------------------------- Q5 observatory

def run_observatory(host: str = HOST, day: dt.date | None = None) -> dict:
    """The scan history is public (MDN Observatory FAQ), so it runs only after Daniel's one-time OK."""
    day = day or today()
    res = Result("Q5")
    if os.environ.get("MAINT_OBSERVATORY_OK") != "1":
        return maint_receipt.write_receipt("Q5", "UNKNOWN", why="awaiting Daniel's one-time OK", tool=TOOL)
    url = f"{OBSERVATORY_URL}?{urllib.parse.urlencode({'host': host})}"
    try:
        status, body = http_post(url, None, {"Accept": "application/json"})
    except OSError as e:
        return maint_receipt.write_receipt("Q5", "UNKNOWN", why=f"observatory unreachable: {type(e).__name__}", tool=TOOL)
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        data = {"error": "non-json", "message": body[:200].decode("utf-8", "replace")}
    out = _write_json(maint() / "audits" / f"{day.isoformat()}_observatory.json", {"http_status": status, **data})
    if status != 200 or data.get("error"):
        res.unknown(f"observatory {status}: {data.get('error')} {data.get('message', '')}".strip())
        return res.close(out)
    failed = data.get("tests_failed")
    if not isinstance(failed, int):
        res.unknown("observatory response has no tests_failed")
        return res.close(out)
    summary = f"grade {data.get('grade')} score {data.get('score')} tests_failed {failed}/{data.get('tests_quantity')}"
    if not failed:
        return res.close(out, summary)
    # Name the failing tests: the v2 analyze endpoint returns the recent scan's tests keyed by name (src/api/v2/
    # analyze + utils.hydrateTests in mdn/mdn-http-observatory). It reuses the scan just made; nothing new is public.
    names = None
    try:
        st, body2 = http_get(f"{ANALYZE_URL}?{urllib.parse.urlencode({'host': host})}")
        tests = json.loads(body2.decode("utf-8", "replace")).get("tests") if st == 200 else None
        if isinstance(tests, dict):
            names = sorted(k for k, v in tests.items() if isinstance(v, dict) and v.get("pass") is False)
    except (OSError, ValueError):
        names = None
    _write_json(maint() / "audits" / f"{day.isoformat()}_observatory_tests.json", {"failed_tests": names})
    if names is None:                          # cannot tell the known limit from a new failure: file it all
        res.find("S3", f"Observatory {summary}", f"{data.get('details_url')} (failing tests could not be named, so "
                 "the known frame-ancestors limit is not separated out)", ROUTE_SITE)
        return res.close(out, summary)
    known_file = maint() / KNOWN_LIMITS
    known = json.loads(known_file.read_text(encoding="utf-8")) if known_file.is_file() else {}
    notes = []
    for t in names:
        if t in KNOWN_LIMIT_TESTS:
            if t in known:                     # filed once already: recorded, not re-filed every quarter
                notes.append(f"{t}: known limit, filed {known[t]['filed']}, not re-filed")
                continue
            res.find("S3", f"Observatory {t} fails: a known GitHub Pages limit", KNOWN_LIMIT_TESTS[t], ROUTE_SITE)
            known[t] = {"filed": day.isoformat(), "why": KNOWN_LIMIT_TESTS[t]}
        else:
            res.find("S3", f"Observatory test {t} fails", f"{data.get('details_url')}", ROUTE_SITE)
    _write_json(known_file, known)
    return res.close(out, "; ".join([summary] + notes))


# ---------------------------------------------------------------- C1 uptime reader
HOME_URL = f"https://{HOST}/"
LESSON_URL = re.compile(rf"^https://{re.escape(HOST)}/lessons/[^/?#]+/?$")


def _same_url(a: str | None, b: str) -> bool:
    return bool(a) and a.strip().rstrip("/").lower() == b.rstrip("/").lower()


def coverage(monitors: list[dict]) -> dict:
    """{what the calendar names: the monitor that watches it, or None}, matched BY URL, not "any monitor up"."""
    home = next((m for m in monitors if _same_url(m.get("url"), HOME_URL)), None)
    lesson = next((m for m in monitors if LESSON_URL.match((m.get("url") or "").strip())), None)
    return {HOME_URL: home, "one lesson URL (https://b4him.com/lessons/<slug>/)": lesson}


def run_uptime(day: dt.date | None = None) -> dict:
    """Reads monitor status and 7-day uptime for the W2 digest line. Needs a READ-ONLY key in UPTIMEROBOT_API_KEY."""
    day = day or today()
    res = Result("C1")
    key = os.environ.get("UPTIMEROBOT_API_KEY")
    if not key:
        return maint_receipt.write_receipt("C1", "UNKNOWN", why="no UPTIMEROBOT_API_KEY", tool=TOOL)
    body = urllib.parse.urlencode({"api_key": key, "format": "json", "custom_uptime_ratios": "7"}).encode()
    del key
    try:
        status, raw = http_post(UPTIMEROBOT_URL, body, {"Content-Type": "application/x-www-form-urlencoded",
                                                        "Cache-Control": "no-cache"})
    except OSError as e:
        return maint_receipt.write_receipt("C1", "UNKNOWN", why=f"uptimerobot unreachable: {type(e).__name__}", tool=TOOL)
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        data = {}
    if status != 200 or data.get("stat") != "ok":
        err = data.get("error") or {}
        why = f"uptimerobot {status}: {err.get('type') if isinstance(err, dict) else 'error'}"
        return maint_receipt.write_receipt("C1", "UNKNOWN", why=why, tool=TOOL)
    monitors = []
    for m in data.get("monitors") or []:
        ratio = m.get("custom_uptime_ratio", m.get("custom_uptime_ratios"))
        monitors.append({"name": m.get("friendly_name"), "url": m.get("url"), "status": m.get("status"),
                         "status_text": UR_STATUS.get(m.get("status"), f"unknown code {m.get('status')}"),
                         "uptime_7d": str(ratio).split("-")[0] if ratio not in (None, "") else None})
    cover = coverage(monitors)
    out = _write_json(maint() / "audits" / f"{day.isoformat()}_uptime.json", {"monitors": monitors, "coverage": cover})
    if not monitors:
        res.unknown("no monitors on the account")
        return res.close(out)
    for need, m in cover.items():             # the calendar names the URLs: the home page AND one lesson
        if m is None:
            res.find("S2", f"no monitor watches {need}", "C1 needs a monitor on the home page and one on a lesson "
                     f"URL ({LESSON_URL.pattern}); found: " + ", ".join(str(x['url']) for x in monitors)[:300],
                     "Release Manager + Site Maintainer")
    lines = []
    for m in monitors:
        lines.append(f"{m['name']}: {m['status_text']}, last 7 days uptime {m['uptime_7d']}%")
        if m["status"] in (8, 9):
            res.find("S1", f"monitor {m['name']} is {m['status_text']}", m["url"] or "",
                     "Release Manager + Site Maintainer")
        elif m["status"] != 2:
            res.unknown(f"monitor {m['name']} is {m['status_text']}")
        if m["uptime_7d"] is None:
            res.unknown(f"monitor {m['name']} returned no 7-day ratio")
    return res.close(out, "; ".join(lines))


# ---------------------------------------------------------------- CLI

EXIT = {"PASS": 0, "FINDINGS": 1, "UNKNOWN": 2, "SKIP": 0}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("check", choices=["tls", "dns", "observatory", "uptime"])
    args = ap.parse_args(argv)
    fn = {"tls": run_tls, "dns": run_dns, "observatory": run_observatory, "uptime": run_uptime}[args.check]
    receipt = fn()
    print(json.dumps(receipt, ensure_ascii=False))
    return EXIT[receipt["outcome"]]


if __name__ == "__main__":
    sys.exit(main())
