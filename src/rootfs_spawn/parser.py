# TODO: This code was written entirely by Claude Code.
#       It works for now, but it still needs to be reviewed and optimized.

"""
parser.py — Python parser for the provisioning DSL using Lark.

Install dependency:
    pip install lark

Usage:
    python -m rootfs_spawn.parser config.rootfs

Variable interpolation
----------------------
Any ${name} reference in a scalar value, list item, or block body is resolved
against the scalar assignments defined in the same file.  Resolution is
recursive: if `packages_cache_dir` itself contains `${release}`, that is
expanded first before `packages_cache_dir` is substituted elsewhere.

Lists are joined with commas when interpolated into a string, e.g.:
    packages = [systemd curl]
    spawn = { debootstrap --include=${packages} }
    → "debootstrap --include=systemd,curl"

An undefined variable reference is left as-is (${name} unchanged).

Output format
-------------
`parse()` returns an ordered list of Statement namedtuples so that duplicate
statement names and their relative order are preserved exactly as written in
the .rootfs file.  Each Statement has:
    kind  — "imports" | "assignment" | "block"
    name  — key name (for assignment/block), None for imports
    value — list[str] of import paths | str scalar | list[str] | str block body
"""

import textwrap
import re
import sys
from pathlib import Path
from typing import NamedTuple

from lark import Lark, Transformer

# ─── Grammar ─────────────────────────────────────────────────────────────────

_GRAMMAR_PATH = Path(__file__).parent / "grammar.lark"
GRAMMAR = _GRAMMAR_PATH.read_text()


# ─── AST types ───────────────────────────────────────────────────────────────


class Statement(NamedTuple):
    kind: str  # "imports" | "assignment" | "block"
    name: str | None
    value: object  # list[str] | str


# ─── Transformer ─────────────────────────────────────────────────────────────


class DSLTransformer(Transformer):
    """Converts Lark parse tree into an ordered list of Statement objects."""

    def start(self, statements):
        return list(statements)

    def statement(self, items):
        return items[0]

    def imports_stmt(self, items):
        return Statement(kind="imports", name=None, value=[str(p) for p in items])

    def imports_item(self, items):
        return str(items[0])

    def assignment(self, items):
        name, value = str(items[0]), items[1]
        return Statement(kind="assignment", name=name, value=value)

    def block_def(self, items):
        name, body = str(items[0]), items[1]
        return Statement(kind="block", name=name, value=body)

    def value(self, items):
        return items[0]

    def scalar(self, items):
        s = str(items[0])
        if s.startswith('"') and s.endswith('"'):
            return s[1:-1]
        return s

    def list_val(self, items):
        return [str(i) for i in items]

    def list_item(self, items):
        return str(items[0])

    def block_body(self, lines):
        joined_lines = "\n".join(line for line in lines if line is not None)
        return textwrap.dedent(joined_lines).strip()

    def block_line(self, items):
        if items:
            return str(items[0])
        return ""  # blank line preserved


# ─── Variable resolution ─────────────────────────────────────────────────────

_VAR_RE = re.compile(r"(?<!\\)\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _interpolate(value: str, context: dict, *, _stack: frozenset = frozenset()) -> str:
    """Expand ${name} references in a string using the context dict."""

    def replace(m: re.Match) -> str:
        name = m.group(1)
        if name in _stack:
            print(f"warning: circular variable reference: ${{{name}}}", file=sys.stderr)
            return m.group(0)
        if name not in context:
            return m.group(0)
        raw = context[name]
        if isinstance(raw, list):
            resolved_items = [
                _interpolate(item, context, _stack=_stack | {name}) for item in raw
            ]
            return ",".join(resolved_items)
        return _interpolate(raw, context, _stack=_stack | {name})

    return _VAR_RE.sub(replace, value)


# ─── Import expansion ────────────────────────────────────────────────────────


def _expand_imports(
    statements: list[Statement],
    search_path: Path,
    _seen: frozenset[Path] = frozenset(),
) -> list[Statement]:
    """Replace every imports Statement with the statements from the referenced
    fragment files, resolved relative to search_path.  Glob paths (ending /*)
    expand to all files in the named directory, sorted by name."""
    result = []
    lark = make_parser()
    for stmt in statements:
        if stmt.kind != "imports":
            result.append(stmt)
            continue
        for import_path in stmt.value:  # type: ignore[union-attr]
            if import_path.endswith("/*"):
                dir_path = search_path / import_path[:-2]
                paths = sorted(p for p in dir_path.iterdir() if p.is_file())
            else:
                paths = [search_path / import_path]
            for path in paths:
                path = path.resolve()
                if path in _seen:
                    raise ValueError(f"circular import: {path}")
                fragment = path.read_text()
                tree = lark.parse(fragment)
                raw = DSLTransformer().transform(tree)
                expanded = _expand_imports(raw, search_path, _seen | {path})
                result.extend(expanded)
    return result


# ─── Merge ───────────────────────────────────────────────────────────────────


def merge(statements: list[Statement]) -> dict[str, object]:
    """Merge an ordered statement list into a single dict, C #include-style:

    - scalars: last definition wins.
    - lists: all lists with the same name are concatenated in document order.
    - blocks: all bodies with the same name are concatenated in document order,
      separated by a blank line.

    Variable interpolation is performed after merging so that ${var} references
    see the fully merged values.
    """
    raw: dict[str, object] = {}

    for stmt in statements:
        if stmt.kind == "block":
            existing = raw.get(stmt.name)  # type: ignore[arg-type]
            if existing is None:
                raw[stmt.name] = str(stmt.value)  # type: ignore[index]
            else:
                raw[stmt.name] = f"{existing}\n\n{stmt.value}"  # type: ignore[index]
        elif stmt.kind == "assignment":
            if isinstance(stmt.value, list):
                existing = raw.get(stmt.name)  # type: ignore[arg-type]
                if isinstance(existing, list):
                    raw[stmt.name] = existing + stmt.value  # type: ignore[index]
                else:
                    raw[stmt.name] = list(stmt.value)  # type: ignore[index]
            else:
                raw[stmt.name] = stmt.value  # type: ignore[index]

    context = {k: v for k, v in raw.items() if isinstance(v, (str, list))}
    result: dict[str, object] = {}
    for key, value in raw.items():
        if isinstance(value, str):
            result[key] = _interpolate(value, context)
        elif isinstance(value, list):
            result[key] = [_interpolate(str(i), context) for i in value]
        else:
            result[key] = value
    return result


# ─── Public API ──────────────────────────────────────────────────────────────


def make_parser() -> Lark:
    return Lark(GRAMMAR, parser="earley", ambiguity="resolve")


def parse(text: str, search_path: Path | None = None) -> list[Statement]:
    """Parse DSL source text and expand imports into an ordered statement list.

    Variable interpolation is deferred to merge() so ${var} references see
    the fully merged values.

    search_path: directory used to resolve import paths (default: cwd).
    """
    if search_path is None:
        search_path = Path.cwd()  # imports resolved relative to cwd by default
    lark = make_parser()
    tree = lark.parse(text)
    raw = DSLTransformer().transform(tree)
    return _expand_imports(raw, search_path)
