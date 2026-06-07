"""SARIF 2.1.0 output for Cerberus findings.

Converts the engine's ``Finding`` dataclass into the OASIS SARIF 2.1.0
schema so Cerberus can publish results into GitHub Code Scanning,
SonarQube, any CI / SAST consumer that speaks SARIF.

Zero external deps — emits a plain Python dict that can be JSON-dumped.

Reference: SARIF 2.1.0 spec at
https://docs.oasis-open.org/sarif/sarif/v2.1.0/cs01/sarif-v2.1.0-cs01.html
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Optional

from cerberus.engine.models import Finding, Severity


_TOOL_NAME = "Cerberus"
_TOOL_VERSION = "0.7.0"
_INFORMATION_URI = "https://github.com/acunningham-ai/Charon"
_SARIF_VERSION = "2.1.0"
_SARIF_SCHEMA = (
    "https://docs.oasis-open.org/sarif/sarif/v2.1.0/cos02/schemas/sarif-schema-2.1.0.json"
)


def _severity_to_level(severity: Severity) -> str:
    """Map Cerberus severity → SARIF level."""
    return {
        Severity.CRITICAL: "error",
        Severity.HIGH:     "error",
        Severity.MEDIUM:   "warning",
        Severity.LOW:      "note",
        Severity.INFO:     "note",
    }.get(severity, "warning")


def findings_to_sarif(
    findings: Iterable[Finding],
    *,
    tool_name: str = _TOOL_NAME,
    tool_version: str = _TOOL_VERSION,
    information_uri: str = _INFORMATION_URI,
    base_uri: Optional[str] = None,
) -> dict:
    """Convert an iterable of Findings into a SARIF 2.1.0 dict.

    ``base_uri`` (optional) is the SRCROOT used by SARIF consumers to
    interpret relative artifact URIs. Set it to the scan-target root
    so GitHub Code Scanning + similar tools resolve paths correctly.
    """
    findings_list = list(findings)

    # Deduplicate rule definitions: each unique rule_id appears once in
    # tool.driver.rules; results reference by ruleId.
    rules_index: dict = {}
    rules_list: List[dict] = []
    for f in findings_list:
        if f.rule_id in rules_index:
            continue
        rule_idx = len(rules_list)
        rules_index[f.rule_id] = rule_idx
        rules_list.append({
            "id": f.rule_id,
            "shortDescription": {"text": f.description[:120]},
            "fullDescription": {"text": f.description},
            **({"help": {"text": f.remediation, "markdown": f.remediation}} if f.remediation else {}),
            "properties": {
                "category": f.category,
                "pack": f.pack,
                "severity": f.severity.value,
            },
            "defaultConfiguration": {"level": _severity_to_level(f.severity)},
        })

    results: List[dict] = []
    for f in findings_list:
        artifact_location = {"uri": f.path}
        if base_uri:
            artifact_location["uriBaseId"] = "SRCROOT"
        results.append({
            "ruleId": f.rule_id,
            "ruleIndex": rules_index[f.rule_id],
            "level": _severity_to_level(f.severity),
            "message": {"text": f.description},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": artifact_location,
                        "region": {
                            "startLine": max(f.line, 1),
                            "snippet": {"text": f.matched_text[:200]},
                        },
                    }
                }
            ],
            "properties": {
                "pack": f.pack,
                "category": f.category,
                "severity_cerberus": f.severity.value,
            },
        })

    run: dict = {
        "tool": {
            "driver": {
                "name": tool_name,
                "version": tool_version,
                "informationUri": information_uri,
                "rules": rules_list,
            }
        },
        "results": results,
    }
    if base_uri:
        run["originalUriBaseIds"] = {"SRCROOT": {"uri": base_uri}}

    return {
        "$schema": _SARIF_SCHEMA,
        "version": _SARIF_VERSION,
        "runs": [run],
    }


def write_sarif(
    findings: Iterable[Finding],
    output_path: Path,
    *,
    tool_name: str = _TOOL_NAME,
    tool_version: str = _TOOL_VERSION,
    information_uri: str = _INFORMATION_URI,
    base_uri: Optional[str] = None,
) -> None:
    """Convert findings to SARIF and write JSON to ``output_path``."""
    sarif = findings_to_sarif(
        findings,
        tool_name=tool_name,
        tool_version=tool_version,
        information_uri=information_uri,
        base_uri=base_uri,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(sarif, indent=2), encoding="utf-8")


def validate_sarif_shape(sarif: dict) -> List[str]:
    """Quick structural validation. Returns a list of issues; empty == valid.

    Not a full schema validation (that'd need jsonschema + the SARIF JSON
    schema, which we don't ship). Checks the fields a downstream consumer
    actually needs.
    """
    issues: List[str] = []
    if sarif.get("version") != _SARIF_VERSION:
        issues.append(f"version != {_SARIF_VERSION!r}")
    if not isinstance(sarif.get("runs"), list) or not sarif["runs"]:
        issues.append("runs must be a non-empty list")
        return issues
    run = sarif["runs"][0]
    if "tool" not in run or "driver" not in run.get("tool", {}):
        issues.append("runs[0].tool.driver missing")
    driver = run.get("tool", {}).get("driver", {})
    for field in ("name", "version", "informationUri", "rules"):
        if field not in driver:
            issues.append(f"runs[0].tool.driver.{field} missing")
    if not isinstance(run.get("results"), list):
        issues.append("runs[0].results must be a list")
    else:
        for i, result in enumerate(run["results"]):
            for field in ("ruleId", "level", "message", "locations"):
                if field not in result:
                    issues.append(f"runs[0].results[{i}].{field} missing")
                    break
            if not isinstance(result.get("locations"), list) or not result["locations"]:
                issues.append(f"runs[0].results[{i}].locations must be non-empty list")
                continue
            loc = result["locations"][0]
            if "physicalLocation" not in loc:
                issues.append(f"runs[0].results[{i}].locations[0].physicalLocation missing")
    return issues
