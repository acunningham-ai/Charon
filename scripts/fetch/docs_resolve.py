#!/usr/bin/env python3
"""
docs_resolve.py — package name -> official docs URL(s) + resolved version.

WHY THIS EXISTS
  A docs-lookup tool's value is resolve-library-id -> fetch-versioned-docs,
  killing stale AI-generated API code. The crawling backends of such tools are
  typically proprietary/closed. This rebuilds ONLY the resolve step natively,
  with ZERO external dependency: hit the PUBLIC package registries (npm / PyPI)
  JSON APIs, parse the canonical docs/homepage/repository URLs and the current
  version, and hand the chosen URL to the sibling fetcher web_fetch_md.py (which
  does the actual fetch, SSRF-guarded, untrusted-output).

  Degraded vs a full docs service: we surface the docs *URL* + version, we do
  NOT ship a pre-crawled/cleaned doc corpus. The fetch quality is whatever
  web_fetch_md.py gets from the live page. That trade is deliberate.

BORROW-NOT-VENDOR
  No third-party docs code, no MCP server, no API key. Only public registry
  metadata.

SAFETY
  - Reuses ssrf_ok() from web_fetch_md.py (single source of truth for the guard).
  - Package name is validated + URL-encoded before it touches a URL path (a
    hostile name can't path-traverse or host-inject the registry URL).
  - Egress is to fixed public registry hosts only; honest UA; no secrets/auth.
  - Every candidate URL is ssrf_ok-checked before it's emitted, so we never
    suggest an internal/metadata URL to the caller.
  - Read-only: emits JSON to stdout; writes nothing.

USAGE
  python scripts/fetch/docs_resolve.py --package <name> [--ecosystem npm|pypi|auto] [--version X] [--json]

EXIT CODES
  0 ok (resolved) · 1 not found / refused / error / missing optional dependency
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

# Reuse the SSRF guard + UA + timeouts from the sibling fetcher — one source of
# truth for the safety logic (importing runs only constant/def code; main() is
# __name__-guarded).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from web_fetch_md import ssrf_ok, USER_AGENT, CONNECT_TIMEOUT, READ_TIMEOUT  # noqa: E402

REGISTRY_MAX_BYTES = 25 * 1024 * 1024
DEPS_HINT = (
    "docs resolve needs the `requests` dependency — "
    "`pip install -r requirements-ingest.txt`"
)
# Package-name allowlist: npm scoped (@scope/name), npm/pypi plain names.
_NAME_RE = re.compile(r"^@?[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)?$")


def _get_json(url: str):
    """Guarded GET of a registry JSON endpoint -> parsed dict, or raise."""
    if not ssrf_ok(url):
        raise ValueError(f"refused non-public registry URL: {url}")
    import requests
    with requests.get(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        stream=True, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), allow_redirects=False,
    ) as r:
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise ValueError(f"registry returned HTTP {r.status_code}")
        chunks, total = [], 0
        for chunk in r.iter_content(64 * 1024):
            total += len(chunk)
            if total > REGISTRY_MAX_BYTES:
                raise ValueError("registry response exceeds size cap")
            chunks.append(chunk)
    return json.loads(b"".join(chunks).decode("utf-8", errors="replace"))


def _clean_repo_url(url: str) -> str:
    """Normalise a repository URL (strip git+, .git, git:// -> https)."""
    if not url:
        return ""
    url = url.strip()
    url = re.sub(r"^git\+", "", url)
    url = re.sub(r"^git://", "https://", url)
    url = re.sub(r"^ssh://git@", "https://", url)
    url = re.sub(r"\.git$", "", url)
    return url


def _rank_candidates(pairs):
    """pairs: list of (label, url). De-dupe, ssrf-filter, order by doc-likeness."""
    seen, out = set(), []
    # Priority: explicit docs > homepage > repository.
    priority = {"documentation": 0, "docs": 0, "homepage": 1, "home": 1,
                "repository": 2, "source": 2}
    def keyfn(p):
        return priority.get(p[0].lower(), 3)
    for label, url in sorted(pairs, key=keyfn):
        url = (url or "").strip()
        if not url or url in seen:
            continue
        if not url.lower().startswith(("http://", "https://")):
            continue
        if not ssrf_ok(url):
            continue
        seen.add(url)
        out.append({"label": label, "url": url})
    return out


def resolve_pypi(pkg: str, version: str | None):
    data = _get_json(f"https://pypi.org/pypi/{quote(pkg, safe='')}/json")
    if data is None:
        return None
    info = data.get("info", {}) or {}
    releases = list((data.get("releases") or {}).keys())
    latest = info.get("version", "")
    resolved = version or latest
    pairs = []
    for label, url in (info.get("project_urls") or {}).items():
        pairs.append((label, url))
    if info.get("home_page"):
        pairs.append(("homepage", info["home_page"]))
    if info.get("docs_url"):
        pairs.append(("documentation", info["docs_url"]))
    return {
        "ecosystem": "pypi",
        "package": pkg,
        "resolved_version": resolved,
        "latest_version": latest,
        "version_valid": (version in releases) if version else True,
        "available_versions": len(releases),
        "docs_candidates": _rank_candidates(pairs),
        "registry_url": f"https://pypi.org/pypi/{quote(pkg, safe='')}/json",
    }


def resolve_npm(pkg: str, version: str | None):
    data = _get_json(f"https://registry.npmjs.org/{quote(pkg, safe='')}")
    if data is None:
        return None
    versions = list((data.get("versions") or {}).keys())
    latest = (data.get("dist-tags") or {}).get("latest", "")
    resolved = version or latest
    vdata = (data.get("versions") or {}).get(resolved, {}) or {}
    pairs = []
    hp = vdata.get("homepage") or data.get("homepage")
    if hp:
        pairs.append(("homepage", hp))
    repo = vdata.get("repository") or data.get("repository")
    if isinstance(repo, dict):
        pairs.append(("repository", _clean_repo_url(repo.get("url", ""))))
    elif isinstance(repo, str):
        pairs.append(("repository", _clean_repo_url(repo)))
    return {
        "ecosystem": "npm",
        "package": pkg,
        "resolved_version": resolved,
        "latest_version": latest,
        "version_valid": (version in versions) if version else True,
        "available_versions": len(versions),
        "docs_candidates": _rank_candidates(pairs),
        "registry_url": f"https://registry.npmjs.org/{quote(pkg, safe='')}",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Resolve a package to its docs URL(s).")
    ap.add_argument("--package", required=True)
    ap.add_argument("--ecosystem", choices=["npm", "pypi", "auto"], default="auto")
    ap.add_argument("--version", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    def emit(s):
        print(json.dumps(s) if args.json else "\n".join(f"{k}: {v}" for k, v in s.items()))

    # Optional-dependency check up front (requests is the only extra needed).
    try:
        import requests  # noqa: F401
    except Exception:
        emit({"ok": False, "error": DEPS_HINT})
        return 1

    pkg = args.package.strip()
    if not _NAME_RE.match(pkg):
        emit({"ok": False, "error": f"invalid package name: {pkg!r}"})
        return 1

    order = {"npm": [resolve_npm], "pypi": [resolve_pypi],
             "auto": [resolve_pypi, resolve_npm]}[args.ecosystem]
    result = None
    for fn in order:
        try:
            result = fn(pkg, args.version)
        except Exception as e:
            emit({"ok": False, "error": f"{fn.__name__} failed: {type(e).__name__}: {e}"})
            return 1
        if result is not None:
            break

    if result is None:
        emit({"ok": False, "package": pkg, "ecosystem": args.ecosystem,
              "error": "package not found in the checked registry(ies)"})
        return 1
    if not result["docs_candidates"]:
        result["note"] = ("no public docs/homepage/repository URL published in "
                          "registry metadata — try a web search for the docs site")
    result["ok"] = True
    emit(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
