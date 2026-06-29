#!/usr/bin/env python3
"""
KEV/CVE triage — Prometheus beat #7, Layer 1 (digest-only).

Fetches the CISA Known Exploited Vulnerabilities catalogue, scores recent
additions, and writes a prioritised shortlist to 00-Inbox/_research/ for
Prometheus to fold into its digest's "bulletin-worthy" line. Read-the-web +
write-note only — takes NO consequential action, never drafts/sends a bulletin
(that's the deferred Layer 2, human-gated).

Origin: borrowed *pattern* (exploited × recency priority scoring) from
OpenThreat (hoodinformatik/OpenThreat, AGPL). The AGPL web app is NOT vendored —
this is a dependency-free stdlib reimplementation.

SCORING NOTE: CISA KEV carries no CVSS. OpenThreat's "exploited × CVSS × recency"
becomes, on KEV-only inputs: exploited (the whole catalogue is, by definition)
× recency × ransomware-campaign flag × due-date urgency, plus a COARSE
"broadly-deployed vendor" relevance lens. This is a newsworthiness heuristic, NOT
an asset-inventory match — the harness has no CMDB to match against, and doesn't
need one (a KEV bulletin self-targets: it asks each recipient to check their own
stack). Tune the vendor lens with `--vendors`. CVSS enrichment would need NVD —
deferred by design (KEV-only).

Security posture (CISO lens):
  - Egress: one outbound GET to cisa.gov (documented purpose). No other network.
  - No secrets read, no credentials, no LLM call (deterministic).
  - Write-path confined to 00-Inbox/_research/ (Prometheus zone; on the
    validate-write-path allowlist). Never writes elsewhere.
  - Untrusted-data discipline: KEV fields are rendered as data; only scalar
    fields (IDs, dates, flags) drive logic — free-text (shortDescription) is
    truncated and never executed/parsed for instructions.
  - Unattended use is GATED: run on-demand / inside /prometheus first; pass
    /owasp-agentic-review + /secure-code-review + a shadow window before any
    scheduled run (same gates as the rest of Prometheus).

CLI:
    python kev-fetch.py --days 14 --top 10           # write shortlist to _research/
    python kev-fetch.py --dry-run                      # print, don't write
    python kev-fetch.py --out /path/to/file.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"

# Coarse "broadly-deployed vendor" lens — a newsworthiness heuristic, substring-
# matched (lowercase) against vendorProject + product. Ships with a sensible
# default (widely-run vendors); override with `--vendors <file>` (one term per
# line, '#' comments) to match the software your org or its customers run.
_DEFAULT_VENDORS = {
    "microsoft", "cisco", "fortinet", "ivanti", "citrix", "vmware", "broadcom",
    "palo alto", "paloalto", "apache", "oracle", "atlassian", "gitlab", "github",
    "progress", "adobe", "google", "chrome", "mozilla", "firefox", "linux",
    "kernel", "openssl", "nginx", "f5", "sonicwall", "zoho", "jetbrains",
    "wordpress", "php", "node", "docker", "kubernetes", "elastic", "jenkins",
    "samba", "openssh", "windows", "exchange", "sharepoint", "outlook", "azure",
}
VENDORS = set(_DEFAULT_VENDORS)


def load_vendors(path: str) -> set:
    """Read a vendor-lens override file (one lowercase term per line, '#' comments).
    Returns the built-in default on any failure."""
    try:
        terms = set()
        with open(path, encoding="utf-8") as f:
            for line in f:
                t = line.split("#", 1)[0].strip().lower()
                if t:
                    terms.add(t)
        return terms or set(_DEFAULT_VENDORS)
    except Exception:
        return set(_DEFAULT_VENDORS)


def fetch_kev(timeout: int = 25) -> dict | None:
    """One documented outbound GET to CISA. Returns parsed JSON or None."""
    try:
        req = urllib.request.Request(KEV_URL, headers={"User-Agent": "kev-triage/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (fixed gov URL)
            return json.load(r)
    except Exception as e:
        print(f"[kev-fetch] fetch failed: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def _days_since(date_str: str, now: datetime) -> int | None:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (now - d).days
    except Exception:
        return None


def _is_deployed(vendor: str, product: str) -> bool:
    hay = f"{vendor} {product}".lower()
    return any(v in hay for v in VENDORS)


def _clean(s: str, cap: int = 60) -> str:
    """Sanitize an external (KEV-sourced) string before embedding in the digest:
    strip pipes/newlines/control chars so it can't break the markdown table or
    ride an injection into the trusted _research note. Isolation Discipline:
    KEV is data, not instructions."""
    s = str(s or "")
    s = "".join(c for c in s if c.isprintable() and c not in "|")
    s = s.replace("\n", " ").replace("\r", " ").strip()
    return (s[:cap] + "…") if len(s) > cap else s


def score_entry(v: dict, now: datetime) -> tuple[int, dict]:
    """Return (score, reasons) for one KEV entry. KEV-available signals only."""
    score = 0
    reasons = []
    added = _days_since(v.get("dateAdded", ""), now)
    if added is not None:
        if added <= 2:
            score += 4; reasons.append("added <=2d")
        elif added <= 7:
            score += 3; reasons.append("added <=7d")
        elif added <= 14:
            score += 2; reasons.append("added <=14d")
        elif added <= 30:
            score += 1; reasons.append("added <=30d")
    if str(v.get("knownRansomwareCampaignUse", "")).strip().lower() == "known":
        score += 4; reasons.append("ransomware")
    due = _days_since(v.get("dueDate", ""), now)
    if due is not None and due >= -1:  # due within ~now or overdue
        score += 2; reasons.append("due-now/overdue")
    if _is_deployed(v.get("vendorProject", ""), v.get("product", "")):
        score += 2; reasons.append("broadly-deployed")
    return score, {"days_since_added": added, "reasons": reasons}


def build_shortlist(data: dict, window_days: int, top: int, now: datetime) -> list[dict]:
    out = []
    for v in data.get("vulnerabilities", []):
        added = _days_since(v.get("dateAdded", ""), now)
        if added is None or added > window_days:
            continue
        score, meta = score_entry(v, now)
        out.append({"v": v, "score": score, "meta": meta})
    out.sort(key=lambda x: (x["score"], x["v"].get("dateAdded", "")), reverse=True)
    return out[:top]


def render_markdown(rows: list[dict], data: dict, window_days: int, now: datetime) -> str:
    today = now.strftime("%Y-%m-%d")
    fm = (
        "---\n"
        "type: kev-digest\n"
        f"date: {today}\n"
        f"catalog_version: {data.get('catalogVersion', '?')}\n"
        f"window_days: {window_days}\n"
        f"entries_in_window: {len(rows)}\n"
        "source: CISA Known Exploited Vulnerabilities\n"
        "trust: trusted\n"
        "---\n\n"
    )
    body = [f"# KEV triage — {today}\n\n",
            f"Top {len(rows)} of CISA KEV additions in the last {window_days} days "
            f"(catalogue {data.get('catalogVersion','?')}, {data.get('count','?')} total). "
            "Score = recency × ransomware × due-date × broadly-deployed lens. "
            "No CVSS (KEV-only). For triage → bulletin-worthy?\n\n",
            "| Score | CVE | Vendor / Product | Added | Ransomware | Due | Why |\n",
            "|---|---|---|---|---|---|---|\n"]
    for r in rows:
        v = r["v"]
        ransom = "🔴 known" if str(v.get("knownRansomwareCampaignUse","")).lower() == "known" else "—"
        cve = _clean(v.get("cveID", ""), 20)
        vp = _clean(f"{v.get('vendorProject','')}/{v.get('product','')}", 48)
        added = _clean(v.get("dateAdded", ""), 12)
        due = _clean(v.get("dueDate", ""), 12)
        body.append(
            f"| {r['score']} | {cve} | {vp} | {added} | {ransom} | {due} | "
            f"{', '.join(r['meta']['reasons'])} |\n"
        )
    body.append("\n_Layer 1: digest-only. Bulletin drafting (Layer 2) is human-gated — never auto-sent._\n")
    return fm + "".join(body)


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="CISA KEV triage shortlist (Prometheus beat #7).")
    ap.add_argument("--days", type=int, default=14, help="lookback window for dateAdded")
    ap.add_argument("--top", type=int, default=10, help="max entries to surface")
    ap.add_argument("--out", default=None, help="output path (default: 00-Inbox/_research/kev-<date>.md)")
    ap.add_argument("--vendors", default=None, help="override file for the broadly-deployed vendor lens (one term per line, '#' comments)")
    ap.add_argument("--dry-run", action="store_true", help="print to stdout, don't write")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

    if args.vendors:
        global VENDORS
        VENDORS = load_vendors(args.vendors)

    now = datetime.now(timezone.utc)
    data = fetch_kev()
    if data is None:
        return 2  # fail-soft; caller (Prometheus) notes the gap

    rows = build_shortlist(data, args.days, args.top, now)
    md = render_markdown(rows, data, args.days, now)

    if args.dry_run:
        print(md)
        return 0

    # Write-path confined to 00-Inbox/_research/ (Prometheus zone).
    out = args.out
    if out is None:
        root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        out = os.path.join(root, "00-Inbox", "_research", f"kev-{now.strftime('%Y-%m-%d')}.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[kev-fetch] wrote {len(rows)} entries -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
