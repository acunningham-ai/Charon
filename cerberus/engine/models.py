"""Data shapes for the Cerberus rule engine.

Pure dataclasses + enums. No business logic, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Severity(Enum):
    """Finding severity. String forms match Cisco's signature YAMLs (case-insensitive)."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @classmethod
    def from_str(cls, value: str) -> "Severity":
        try:
            return cls(value.lower())
        except ValueError as exc:
            raise ValueError(
                f"unknown severity {value!r}; expected one of {[s.value for s in cls]}"
            ) from exc


class FileType(Enum):
    """File type for routing rules to applicable targets.

    Extension-based today (see ``signatures.detect_file_type``);
    Magika-upgraded in v0.7 chunk 5.
    """

    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    BASH = "bash"
    MARKDOWN = "markdown"
    YAML = "yaml"
    JSON = "json"
    TEXT = "text"          # wildcard — any successfully-read text file
    MANIFEST = "manifest"  # semantic label — chunk 8 wires routing
    BINARY = "binary"
    OTHER = "other"

    @classmethod
    def from_str(cls, value: str) -> "FileType":
        try:
            return cls(value.lower())
        except ValueError as exc:
            raise ValueError(
                f"unknown file_type {value!r}; expected one of {[t.value for t in cls]}"
            ) from exc


@dataclass(frozen=True)
class SignatureRule:
    """A single signature rule loaded from a YAML signatures file.

    ``patterns`` and ``exclude_patterns`` are tuples of compiled ``re.Pattern``
    objects (kept untyped here to avoid the deprecated ``typing.Pattern``).
    """

    id: str
    category: str
    severity: Severity
    patterns: tuple
    exclude_patterns: tuple
    file_types: frozenset
    description: str
    remediation: Optional[str]
    pack: str
    source_file: str


@dataclass(frozen=True)
class Finding:
    """A single detection result against a target file."""

    rule_id: str
    pack: str
    category: str
    severity: Severity
    path: str
    line: int
    matched_text: str
    description: str
    remediation: Optional[str]
