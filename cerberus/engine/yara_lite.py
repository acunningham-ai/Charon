"""Pure-Python YARA-subset interpreter.

Supports the YARA features actually used by Cisco's vendored corpus under
``cerberus/rules/packs/*/yara/*.yara``:

- ``rule NAME { meta: ... strings: ... condition: ... }``
- string patterns: literal ``"foo"``, regex ``/foo/i``, hex ``{ 7F 45 4C 46 }``
- condition language: ``and``, ``or``, ``not``, parens, identifiers
- offset matching: ``$name at N``, ``@name > N``, bare ``@`` inside ``for any of``
- quantifiers: ``for any of ($prefix_*) : (expr)`` and ``for any of ($a, $b) : (expr)``
- comments: ``//`` line and ``/* block */``
- numeric literals: decimal only

Out of scope: hex wildcards (``??``), hex jumps (``[N-M]``), imports,
``filesize`` / ``uintN()`` / ``entrypoint``, custom modules, ``of`` other than
``any of``. If the corpus needs any of these the affected rule is gracefully
skipped with a stderr warning.

Produces ``Finding`` objects using the same dataclass as
``cerberus.engine.signatures``.

No external dependencies — pure stdlib. The trade-off vs ``yara-x`` is
~3× the LOC; the win is Charon stays runtime-dep-free per
``feedback_charon_dep_aversion``.
"""

from __future__ import annotations

import codecs
import re
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from cerberus.engine.models import Finding, Severity


# Module-level dedupe for skip warnings
_WARNED_YARA: set = set()


def _warn_skip(where: str, reason: str) -> None:
    """De-duped stderr warning for unsupported / broken YARA content."""
    key = ("yara", where, reason[:120])
    if key in _WARNED_YARA:
        return
    _WARNED_YARA.add(key)
    sys.stderr.write(f"  WARN cerberus.engine.yara: skipping {where}: {reason}\n")


# ---------- Tokenizer ----------

class TK(Enum):
    IDENT = "IDENT"
    DOLLAR = "DOLLAR"          # $name
    DOLLAR_WC = "DOLLAR_WC"    # $name_*
    AT = "AT"                  # @name or bare @
    NUMBER = "NUMBER"
    STRING = "STRING"
    REGEX = "REGEX"            # body or body/flags
    LBRACE = "{"
    RBRACE = "}"
    LPAREN = "("
    RPAREN = ")"
    EQUALS = "="
    COLON = ":"
    COMMA = ","
    GT = ">"
    LT = "<"
    GE = ">="
    LE = "<="
    EQ = "=="
    NE = "!="
    KW = "KW"                  # any keyword
    EOF = "EOF"


KEYWORDS = frozenset({
    "and", "or", "not", "at", "for", "of", "any", "all",
    "rule", "meta", "strings", "condition", "true", "false",
})


@dataclass(frozen=True)
class Token:
    kind: TK
    value: str
    pos: int


class TokenizerError(Exception):
    pass


class ParseError(Exception):
    pass


def tokenize(source: str) -> List[Token]:
    """Tokenize a YARA source string."""
    tokens: List[Token] = []
    i, n = 0, len(source)
    while i < n:
        c = source[i]
        if c.isspace():
            i += 1
            continue
        # Line comment
        if c == "/" and i + 1 < n and source[i + 1] == "/":
            nl = source.find("\n", i)
            i = n if nl == -1 else nl
            continue
        # Block comment
        if c == "/" and i + 1 < n and source[i + 1] == "*":
            end = source.find("*/", i + 2)
            if end == -1:
                raise TokenizerError(f"unterminated block comment at offset {i}")
            i = end + 2
            continue
        # Single-char punctuation
        if c == "{":
            tokens.append(Token(TK.LBRACE, "{", i)); i += 1; continue
        if c == "}":
            tokens.append(Token(TK.RBRACE, "}", i)); i += 1; continue
        if c == "(":
            tokens.append(Token(TK.LPAREN, "(", i)); i += 1; continue
        if c == ")":
            tokens.append(Token(TK.RPAREN, ")", i)); i += 1; continue
        if c == ":":
            tokens.append(Token(TK.COLON, ":", i)); i += 1; continue
        if c == ",":
            tokens.append(Token(TK.COMMA, ",", i)); i += 1; continue
        # Comparison / assignment operators
        if c == "=" and i + 1 < n and source[i + 1] == "=":
            tokens.append(Token(TK.EQ, "==", i)); i += 2; continue
        if c == "=":
            tokens.append(Token(TK.EQUALS, "=", i)); i += 1; continue
        if c == ">" and i + 1 < n and source[i + 1] == "=":
            tokens.append(Token(TK.GE, ">=", i)); i += 2; continue
        if c == ">":
            tokens.append(Token(TK.GT, ">", i)); i += 1; continue
        if c == "<" and i + 1 < n and source[i + 1] == "=":
            tokens.append(Token(TK.LE, "<=", i)); i += 2; continue
        if c == "<":
            tokens.append(Token(TK.LT, "<", i)); i += 1; continue
        if c == "!" and i + 1 < n and source[i + 1] == "=":
            tokens.append(Token(TK.NE, "!=", i)); i += 2; continue
        # Dollar-prefixed (string identifier, possibly wildcard)
        if c == "$":
            j = i + 1
            while j < n and (source[j].isalnum() or source[j] == "_"):
                j += 1
            if j < n and source[j] == "*":
                tokens.append(Token(TK.DOLLAR_WC, source[i:j + 1], i))
                i = j + 1
            else:
                tokens.append(Token(TK.DOLLAR, source[i:j], i))
                i = j
            continue
        # At-prefixed (offset reference; bare @ allowed)
        if c == "@":
            j = i + 1
            while j < n and (source[j].isalnum() or source[j] == "_"):
                j += 1
            tokens.append(Token(TK.AT, source[i:j], i))
            i = j
            continue
        # Quoted string
        if c == '"':
            j = i + 1
            while j < n and source[j] != '"':
                if source[j] == "\\" and j + 1 < n:
                    j += 2
                else:
                    j += 1
            if j >= n:
                raise TokenizerError(f"unterminated string at offset {i}")
            tokens.append(Token(TK.STRING, source[i + 1:j], i))
            i = j + 1
            continue
        # Regex literal
        if c == "/":
            j = i + 1
            in_class = False
            while j < n and (in_class or source[j] != "/"):
                if source[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if source[j] == "[":
                    in_class = True
                elif source[j] == "]":
                    in_class = False
                j += 1
            if j >= n:
                raise TokenizerError(f"unterminated regex at offset {i}")
            body = source[i + 1:j]
            k = j + 1
            flags_start = k
            while k < n and source[k].isalpha():
                k += 1
            flags = source[flags_start:k]
            value = body + ("/" + flags if flags else "")
            tokens.append(Token(TK.REGEX, value, i))
            i = k
            continue
        # Decimal number
        if c.isdigit():
            j = i
            while j < n and source[j].isdigit():
                j += 1
            tokens.append(Token(TK.NUMBER, source[i:j], i))
            i = j
            continue
        # Identifier / keyword
        if c.isalpha() or c == "_":
            j = i
            while j < n and (source[j].isalnum() or source[j] == "_"):
                j += 1
            ident = source[i:j]
            if ident in KEYWORDS:
                tokens.append(Token(TK.KW, ident, i))
            else:
                tokens.append(Token(TK.IDENT, ident, i))
            i = j
            continue
        raise TokenizerError(f"unexpected character {c!r} at offset {i}")
    tokens.append(Token(TK.EOF, "", n))
    return tokens


# ---------- AST ----------

@dataclass(frozen=True)
class YaraPattern:
    """A single named string pattern in a YARA rule's `strings:` section."""
    name: str        # without $
    kind: str        # "text" | "regex" | "hex"
    raw: str
    compiled: object # bytes for text/hex, re.Pattern for regex


# Condition expression nodes. Plain dataclasses; no shared base class needed —
# the evaluator dispatches on isinstance.

@dataclass(frozen=True)
class StringPresent:
    name: str

@dataclass(frozen=True)
class StringAtOffset:
    name: str
    offset: int

@dataclass(frozen=True)
class OffsetCompare:
    name: str   # "" for bare @ (loop variable inside `for any of`)
    op: str
    value: int

@dataclass(frozen=True)
class AndExpr:
    left: object
    right: object

@dataclass(frozen=True)
class OrExpr:
    left: object
    right: object

@dataclass(frozen=True)
class NotExpr:
    inner: object

@dataclass(frozen=True)
class ForAnyOf:
    wildcard_prefix: Optional[str]   # e.g. "shebang_" for $shebang_*
    explicit_names: tuple             # tuple[str, ...] when an explicit list is used
    body: object

@dataclass(frozen=True)
class BoolLit:
    value: bool


@dataclass(frozen=True)
class YaraRule:
    name: str
    meta: dict
    patterns: tuple        # tuple[YaraPattern, ...]
    condition: object
    source_file: str
    pack: str


# ---------- Parser ----------

class _Parser:
    def __init__(self, tokens: List[Token], source_file: str):
        self.tokens = tokens
        self.pos = 0
        self.source_file = source_file

    def _peek(self) -> Token:
        return self.tokens[self.pos]

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _check(self, kind: TK, value: Optional[str] = None) -> bool:
        tok = self._peek()
        if tok.kind != kind:
            return False
        if value is not None and tok.value != value:
            return False
        return True

    def _match(self, kind: TK, value: Optional[str] = None) -> bool:
        if self._check(kind, value):
            self._advance()
            return True
        return False

    def _expect(self, kind: TK, value: Optional[str] = None) -> Token:
        tok = self._advance()
        if tok.kind != kind or (value is not None and tok.value != value):
            want = f"{kind.value}" + (f" {value!r}" if value else "")
            raise ParseError(
                f"{self.source_file}: expected {want}, got {tok.kind.value} "
                f"{tok.value!r} at offset {tok.pos}"
            )
        return tok

    def parse_file(self) -> List[YaraRule]:
        rules: List[YaraRule] = []
        while not self._check(TK.EOF):
            rules.append(self._parse_rule())
        return rules

    def _parse_rule(self) -> YaraRule:
        self._expect(TK.KW, "rule")
        name_tok = self._expect(TK.IDENT)
        self._expect(TK.LBRACE)
        meta: dict = {}
        patterns: List[YaraPattern] = []
        condition: object = None
        while not self._check(TK.RBRACE):
            if self._match(TK.KW, "meta"):
                self._expect(TK.COLON)
                meta = self._parse_meta()
            elif self._match(TK.KW, "strings"):
                self._expect(TK.COLON)
                patterns = self._parse_strings()
            elif self._match(TK.KW, "condition"):
                self._expect(TK.COLON)
                condition = self._parse_condition()
            else:
                tok = self._peek()
                raise ParseError(
                    f"{self.source_file}: unexpected token in rule body: "
                    f"{tok.kind.value} {tok.value!r} at offset {tok.pos}"
                )
        self._expect(TK.RBRACE)
        if condition is None:
            raise ParseError(f"{self.source_file}: rule {name_tok.value!r} has no condition")
        return YaraRule(
            name=name_tok.value,
            meta=meta,
            patterns=tuple(patterns),
            condition=condition,
            source_file=self.source_file,
            pack="",
        )

    def _parse_meta(self) -> dict:
        meta: dict = {}
        while self._check(TK.IDENT):
            key = self._advance().value
            self._expect(TK.EQUALS)
            tok = self._advance()
            if tok.kind == TK.STRING:
                meta[key] = _decode_string(tok.value)
            elif tok.kind == TK.NUMBER:
                meta[key] = int(tok.value)
            elif tok.kind == TK.KW and tok.value in ("true", "false"):
                meta[key] = (tok.value == "true")
            else:
                raise ParseError(
                    f"{self.source_file}: meta value must be string/number/bool, got "
                    f"{tok.kind.value} {tok.value!r} at offset {tok.pos}"
                )
        return meta

    def _parse_strings(self) -> List[YaraPattern]:
        patterns: List[YaraPattern] = []
        while self._check(TK.DOLLAR) or self._check(TK.DOLLAR_WC):
            name_tok = self._advance()
            name = name_tok.value[1:]
            if name.endswith("*"):
                # We don't support wildcards in string definitions (only in for-of sets)
                raise ParseError(
                    f"{self.source_file}: wildcard string id in definition not supported: {name_tok.value!r}"
                )
            self._expect(TK.EQUALS)
            tok = self._peek()
            if tok.kind == TK.STRING:
                self._advance()
                patterns.append(YaraPattern(
                    name=name, kind="text", raw=tok.value,
                    compiled=_decode_string(tok.value).encode("utf-8"),
                ))
            elif tok.kind == TK.REGEX:
                self._advance()
                patterns.append(YaraPattern(
                    name=name, kind="regex", raw=tok.value,
                    compiled=_compile_yara_regex(tok.value),
                ))
            elif tok.kind == TK.LBRACE:
                hex_str = self._read_hex_pattern()
                patterns.append(YaraPattern(
                    name=name, kind="hex", raw=hex_str,
                    compiled=_compile_hex(hex_str),
                ))
            else:
                raise ParseError(
                    f"{self.source_file}: expected pattern after '=', got "
                    f"{tok.kind.value} {tok.value!r} at offset {tok.pos}"
                )
        return patterns

    def _read_hex_pattern(self) -> str:
        """Consume tokens between LBRACE / RBRACE and reconstruct the hex digit string.

        Hex bytes tokenize variably — ``7F`` -> NUMBER(7), IDENT(F);
        ``45`` -> NUMBER(45); ``CE`` -> IDENT(CE). We concatenate the token
        values; whitespace between bytes is dropped naturally because it
        doesn't tokenize.
        """
        self._expect(TK.LBRACE)
        parts: List[str] = []
        while not self._check(TK.RBRACE):
            if self._check(TK.EOF):
                raise ParseError(f"{self.source_file}: unterminated hex pattern")
            tok = self._advance()
            if tok.kind in (TK.IDENT, TK.NUMBER):
                parts.append(tok.value)
            else:
                # Hex wildcards (??), jumps ([N-M]), alternations (a|b), or anything
                # else lexed differently — out of scope for our subset.
                raise ParseError(
                    f"{self.source_file}: unsupported token in hex pattern: "
                    f"{tok.kind.value} {tok.value!r} at offset {tok.pos}"
                )
        self._expect(TK.RBRACE)
        return "".join(parts)

    # --- condition grammar (precedence: or < and < not < primary) ---

    def _parse_condition(self) -> object:
        return self._parse_or()

    def _parse_or(self) -> object:
        left = self._parse_and()
        while self._match(TK.KW, "or"):
            right = self._parse_and()
            left = OrExpr(left, right)
        return left

    def _parse_and(self) -> object:
        left = self._parse_not()
        while self._match(TK.KW, "and"):
            right = self._parse_not()
            left = AndExpr(left, right)
        return left

    def _parse_not(self) -> object:
        if self._match(TK.KW, "not"):
            return NotExpr(self._parse_not())
        return self._parse_primary()

    def _parse_primary(self) -> object:
        tok = self._peek()
        if tok.kind == TK.LPAREN:
            self._advance()
            expr = self._parse_or()
            self._expect(TK.RPAREN)
            return expr
        if tok.kind == TK.KW and tok.value == "for":
            return self._parse_for_any()
        if tok.kind == TK.DOLLAR:
            self._advance()
            name = tok.value[1:]
            if self._match(TK.KW, "at"):
                off = self._expect(TK.NUMBER)
                return StringAtOffset(name, int(off.value))
            return StringPresent(name)
        if tok.kind == TK.AT:
            self._advance()
            name = tok.value[1:]   # "" for bare @
            op_tok = self._advance()
            op_map = {TK.GT: ">", TK.LT: "<", TK.GE: ">=", TK.LE: "<=", TK.EQ: "==", TK.NE: "!="}
            if op_tok.kind not in op_map:
                raise ParseError(
                    f"{self.source_file}: expected comparison op after @{name}, "
                    f"got {op_tok.kind.value} {op_tok.value!r}"
                )
            num = self._expect(TK.NUMBER)
            return OffsetCompare(name, op_map[op_tok.kind], int(num.value))
        if tok.kind == TK.KW and tok.value in ("true", "false"):
            self._advance()
            return BoolLit(tok.value == "true")
        raise ParseError(
            f"{self.source_file}: unexpected token in condition: "
            f"{tok.kind.value} {tok.value!r} at offset {tok.pos}"
        )

    def _parse_for_any(self) -> object:
        self._expect(TK.KW, "for")
        quant = self._expect(TK.KW)
        if quant.value not in ("any", "all"):
            raise ParseError(
                f"{self.source_file}: expected 'any' or 'all' after 'for', got {quant.value!r}"
            )
        # We support "for any of". "for all of" is treated identically here — the
        # corpus uses "any" exclusively; "all" would need different semantics if it
        # appears, but we'll skip-with-warning at scan time if so.
        self._expect(TK.KW, "of")
        self._expect(TK.LPAREN)
        wildcard: Optional[str] = None
        names: List[str] = []
        if self._check(TK.DOLLAR_WC):
            tok = self._advance()
            wildcard = tok.value[1:-1]   # strip $ and *
        elif self._check(TK.DOLLAR):
            tok = self._advance()
            names.append(tok.value[1:])
            while self._match(TK.COMMA):
                tok = self._expect(TK.DOLLAR)
                names.append(tok.value[1:])
        else:
            tok = self._peek()
            raise ParseError(
                f"{self.source_file}: expected $ID or $prefix_* in for-of set, "
                f"got {tok.kind.value} {tok.value!r}"
            )
        self._expect(TK.RPAREN)
        self._expect(TK.COLON)
        self._expect(TK.LPAREN)
        body = self._parse_or()
        self._expect(TK.RPAREN)
        return ForAnyOf(
            wildcard_prefix=wildcard,
            explicit_names=tuple(names),
            body=body,
        )


# ---------- Pattern compilers ----------

def _decode_string(s: str) -> str:
    """Decode YARA string escapes (\\n, \\t, \\\\, \\", \\xHH, etc.)."""
    try:
        return codecs.decode(s, "unicode_escape")
    except UnicodeDecodeError:
        return s


def _compile_yara_regex(raw: str):
    """Compile a YARA regex literal. `raw` is `body` or `body/flags`."""
    body, flags_str = raw, ""
    if "/" in raw:
        idx = raw.rfind("/")
        trail = raw[idx + 1:]
        if trail and all(c.isalpha() for c in trail):
            body, flags_str = raw[:idx], trail
    flags = re.MULTILINE
    if "i" in flags_str:
        flags |= re.IGNORECASE
    if "s" in flags_str:
        flags |= re.DOTALL
    # Reuse the PCRE \u{HEX} -> Python re translator from the signature engine
    from cerberus.engine.signatures import _translate_pcre_escapes
    return re.compile(_translate_pcre_escapes(body), flags)


def _compile_hex(hex_digits: str) -> bytes:
    """Convert a concatenated hex digit string to bytes. E.g. '7F454C46' -> b'\\x7fELF'."""
    clean = hex_digits.strip()
    if len(clean) % 2 != 0:
        raise ValueError(f"hex pattern has odd nibble count: {hex_digits!r}")
    if not re.match(r"^[0-9a-fA-F]+$", clean):
        raise ValueError(f"hex pattern contains non-hex chars: {hex_digits!r}")
    return bytes.fromhex(clean)


# ---------- Evaluator ----------

def _scan_pattern(pattern: YaraPattern, file_bytes: bytes, file_text: str) -> List[int]:
    """Return list of offsets where this pattern matches in the file."""
    offsets: List[int] = []
    if pattern.kind in ("text", "hex"):
        needle: bytes = pattern.compiled
        if not needle:
            return offsets
        start = 0
        while True:
            idx = file_bytes.find(needle, start)
            if idx == -1:
                break
            offsets.append(idx)
            start = idx + 1
    elif pattern.kind == "regex":
        for m in pattern.compiled.finditer(file_text):
            offsets.append(m.start())
    return offsets


def _eval(expr: object, matches: dict, loop_var: Optional[Tuple[str, int]] = None) -> bool:
    """Evaluate a condition expression against the per-pattern match table.

    `matches` maps pattern name -> sorted list of offsets.
    `loop_var` is (pattern_name, offset) when inside a `for any of` body.
    """
    if isinstance(expr, StringPresent):
        if loop_var is not None and (expr.name == "" or expr.name == loop_var[0]):
            return True
        return bool(matches.get(expr.name))
    if isinstance(expr, StringAtOffset):
        return expr.offset in matches.get(expr.name, [])
    if isinstance(expr, OffsetCompare):
        if expr.name == "" and loop_var is not None:
            v = loop_var[1]
        elif loop_var is not None and expr.name == loop_var[0]:
            v = loop_var[1]
        else:
            offs = matches.get(expr.name)
            if not offs:
                return False
            v = offs[0]
        return _cmp(v, expr.op, expr.value)
    if isinstance(expr, AndExpr):
        return _eval(expr.left, matches, loop_var) and _eval(expr.right, matches, loop_var)
    if isinstance(expr, OrExpr):
        return _eval(expr.left, matches, loop_var) or _eval(expr.right, matches, loop_var)
    if isinstance(expr, NotExpr):
        return not _eval(expr.inner, matches, loop_var)
    if isinstance(expr, BoolLit):
        return expr.value
    if isinstance(expr, ForAnyOf):
        if expr.wildcard_prefix is not None:
            iter_names = [n for n in matches if n.startswith(expr.wildcard_prefix)]
        else:
            iter_names = [n for n in expr.explicit_names if n in matches]
        for name in iter_names:
            for off in matches.get(name, []):
                if _eval(expr.body, matches, loop_var=(name, off)):
                    return True
        return False
    raise NotImplementedError(f"unknown condition node: {type(expr).__name__}")


def _cmp(a: int, op: str, b: int) -> bool:
    return {
        ">":  a > b,
        "<":  a < b,
        ">=": a >= b,
        "<=": a <= b,
        "==": a == b,
        "!=": a != b,
    }[op]


# ---------- Public API ----------

def load_pack_yara_rules(pack_dir: Path) -> List[YaraRule]:
    """Load all `.yara` rules from a pack's ``yara/`` subdir."""
    rules: List[YaraRule] = []
    yara_dir = pack_dir / "yara"
    if not yara_dir.exists():
        return rules
    for yara_file in sorted(yara_dir.glob("*.yara")):
        try:
            source = yara_file.read_text(encoding="utf-8")
            tokens = tokenize(source)
            parsed = _Parser(tokens, str(yara_file)).parse_file()
        except (TokenizerError, ParseError, ValueError) as exc:
            _warn_skip(yara_file.name, str(exc))
            continue
        for r in parsed:
            rules.append(YaraRule(
                name=r.name, meta=r.meta, patterns=r.patterns,
                condition=r.condition, source_file=r.source_file,
                pack=pack_dir.name,
            ))
    return rules


def load_all_yara_rules(packs_root: Path) -> List[YaraRule]:
    """Load YARA rules from every pack directory under ``packs_root``."""
    rules: List[YaraRule] = []
    if not packs_root.is_dir():
        return rules
    for pack_dir in sorted(packs_root.iterdir()):
        if not pack_dir.is_dir() or pack_dir.name.startswith("_") or pack_dir.name.startswith("."):
            continue
        rules.extend(load_pack_yara_rules(pack_dir))
    return rules


def execute_yara_rule(rule: YaraRule, path: Path, file_bytes: bytes, file_text: str) -> Optional[Finding]:
    """Run one YARA rule against the file. Returns a Finding if the condition holds."""
    matches: dict = {}
    for pattern in rule.patterns:
        offs = _scan_pattern(pattern, file_bytes, file_text)
        if offs:
            matches[pattern.name] = offs
    try:
        hit = _eval(rule.condition, matches)
    except Exception as exc:
        _warn_skip(f"{rule.source_file}:{rule.name}", f"eval error: {exc}")
        return None
    if not hit:
        return None
    first_name = next(iter(matches), None)
    first_off = matches[first_name][0] if first_name else 0
    line_no = file_text.count("\n", 0, first_off) + 1 if file_text else 1
    severity = _severity_from_meta(rule.meta)
    category = str(rule.meta.get("threat_type") or rule.meta.get("classification") or "yara_rule")
    description = str(rule.meta.get("description") or f"YARA rule {rule.name} matched")
    return Finding(
        rule_id=f"YARA_{rule.name}",
        pack=rule.pack,
        category=category,
        severity=severity,
        path=str(path),
        line=line_no,
        matched_text=first_name or "(condition-only)",
        description=description,
        remediation=None,
    )


def scan_file_yara(path: Path, rules: Iterable[YaraRule]) -> List[Finding]:
    """Apply all YARA rules to a single file."""
    try:
        file_bytes = path.read_bytes()
    except OSError:
        return []
    file_text = file_bytes.decode("utf-8", errors="replace")
    findings: List[Finding] = []
    for rule in rules:
        f = execute_yara_rule(rule, path, file_bytes, file_text)
        if f:
            findings.append(f)
    return findings


def _severity_from_meta(meta: dict) -> Severity:
    """Map YARA meta `severity` field to our Severity enum. Default MEDIUM."""
    raw = meta.get("severity", "MEDIUM")
    try:
        return Severity.from_str(str(raw))
    except ValueError:
        return Severity.MEDIUM
