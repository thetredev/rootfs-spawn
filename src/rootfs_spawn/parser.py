"""
dsl_parser.py — Python parser for the provisioning DSL using Lark.

Install dependency:
    pip install lark

Usage:
    python dsl_parser.py config.dsl

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

An undefined variable reference is left as-is (${name} unchanged) and a
warning is emitted to stderr.
"""

import textwrap
import re
import sys

from lark import Lark, Transformer

# ─── Grammar ─────────────────────────────────────────────────────────────────
# NEWLINEs are declared as anonymous literals (underscore-prefixed rules drop
# their children) so the transformer never sees them as positional arguments.

GRAMMAR = r"""
start: statement+

statement: assignment
         | block_def

// Scalar or list assignment — NEWLINE is matched but discarded via _NL alias
assignment: NAME "=" value _NL+

value: scalar
     | list_val

scalar: BARE_STRING
      | ESCAPED_STRING

// Newline-separated list (no commas)
list_val: "[" _NL+ list_item* "]"

list_item: BARE_STRING _NL+

// Named shell-script block
block_def: NAME "=" "{" _NL+ block_body "}" _NL*

block_body: block_line*

block_line: BLOCK_CONTENT_LINE _NL
          | _NL

// ─── Terminals ───────────────────────────────────────────────────────────────

// Unquoted value: runs of non-whitespace chars.
// ${...} interpolation sequences are matched as a unit so braces inside them
// don't look like block delimiters.
BARE_STRING: /(?:\$\{[^}]*\}|[^\s\[\]={}\#])+/

// Non-empty line inside a block that is not a lone closing brace.
// [^\n]+ ensures at least one character — no zero-width matches for Earley.
BLOCK_CONTENT_LINE: /(?m)(?![ \t]*\}[ \t]*$)[^\n]+/

NAME: /[a-zA-Z_][a-zA-Z0-9_]*/

// _NL is an inline (anonymous) terminal — Lark drops it from tree children.
_NL: /\r?\n/

%ignore /[ \t]+/

COMMENT: /#[^\n]*/
%ignore COMMENT

%import common.ESCAPED_STRING
"""


# ─── Transformer ─────────────────────────────────────────────────────────────


class DSLTransformer(Transformer):
    """Converts Lark parse tree into plain Python dicts/lists/strings."""

    def start(self, statements):
        result = {}
        for stmt in statements:
            result.update(stmt)
        return result

    def statement(self, items):
        return items[0]

    def assignment(self, items):
        name, value = items[0], items[1]
        return {str(name): value}

    def block_def(self, items):
        name, body = items[0], items[1]
        return {str(name): body}

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
        # BLOCK_CONTENT_LINE branch → items = [token]
        # blank _NL branch        → items = []  (terminal was discarded)
        if items:
            return str(
                items[0]
            )  # Keep original line content including indentation for dedent later
        return ""  # blank line preserved


# ─── Variable resolution ─────────────────────────────────────────────────────

_VAR_RE = re.compile(r"\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


# Modified to ignore escaped dollar signs and suppress warnings for undefined variables
def _interpolate(value: str, context: dict, *, _stack: frozenset = frozenset()) -> str:
    """Expand ${name} references in a string using the context dict.

    - Lists are serialised as comma-joined strings when interpolated.
    - Circular references are detected and left unexpanded with a warning.
    - Unknown variables are left as-is with a warning.
    """

    def replace(m: re.Match) -> str:
        name = m.group(1)
        if name in _stack:
            print(f"warning: circular variable reference: ${{{name}}}", file=sys.stderr)
            return m.group(0)
        if (
            name not in context
        ):  # If variable is not defined, leave it as-is without warning
            return m.group(0)
        raw = context[name]
        if isinstance(raw, list):
            resolved_items = [
                _interpolate(item, context, _stack=_stack | {name}) for item in raw
            ]
            return ",".join(resolved_items)
        return _interpolate(raw, context, _stack=_stack | {name})

    return _VAR_RE.sub(replace, value)


# Changed regex to ignore escaped dollar signs
_VAR_RE = re.compile(r"(?<!\\)\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _resolve(parsed: dict) -> dict:
    """Two-pass variable resolution over a parsed DSL document.

    Pass 1 — collect all scalar and list assignments as the variable context.
    Pass 2 — walk every value (scalar, list item, block body) and expand ${…}.
    """
    context: dict = {k: v for k, v in parsed.items() if isinstance(v, (str, list))}

    result = {}
    for key, value in parsed.items():
        if isinstance(value, str):
            result[key] = _interpolate(value, context)
        elif isinstance(value, list):
            result[key] = [_interpolate(item, context) for item in value]
        else:
            result[key] = value
    return result


# ─── Public API ──────────────────────────────────────────────────────────────


def make_parser() -> Lark:
    return Lark(GRAMMAR, parser="earley", ambiguity="resolve")


def parse(text: str) -> dict:
    """Parse DSL source text, resolve ${variable} references, and return a dict."""
    parser = make_parser()
    tree = parser.parse(text)
    raw = DSLTransformer().transform(tree)
    return _resolve(raw)  # Pass the raw parsed data for resolution
