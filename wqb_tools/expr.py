"""Local (quota-free) helpers for Fast Expressions: lint/validate before simulating, template expansion."""
from __future__ import annotations

import itertools
import re
from typing import Any, Dict, Iterable, List, Sequence

_TOKEN = re.compile(
    r"\s*(?:(?P<num>\d+\.\d*|\.\d+|\d+(?:[eE][-+]?\d+)?)|(?P<id>[A-Za-z_][A-Za-z0-9_.]*)|(?P<str>\"[^\"]*\"|'[^']*')"
    r"|(?P<op>==|!=|<=|>=|&&|\|\||[-+*/^<>=!?:,;()\[\]{}%&|]))"
)
_LITERALS = {"true", "false", "nan", "NaN", "inf", "Inf", "NAN", "INF"}
_PLACEHOLDER = re.compile(r"<\s*([A-Za-z_][\w\-]*)\s*/>|\{([A-Za-z_]\w*)\}")


def strip_comments(expr: str) -> str:
    expr = re.sub(r"/\*.*?\*/", " ", expr, flags=re.S)
    return re.sub(r"(?m)#.*$", " ", expr)


def tokenize(expr: str) -> List[tuple]:
    text = strip_comments(expr)
    pos, out = 0, []
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            out.append(("bad", text[pos], pos))
            pos += 1
            continue
        kind = m.lastgroup
        out.append((kind, m.group(kind), m.start(kind)))
        pos = m.end()
    return out


def analyze_expression(expr: str) -> Dict[str, Any]:
    """Structural analysis: operators called, identifiers (fields / variables), keyword args, local variables."""
    toks = tokenize(expr)
    calls, idents, kwargs, local_vars, errors = [], [], [], [], []
    depth = 0
    for i, (kind, val, pos) in enumerate(toks):
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        prev = toks[i - 1] if i > 0 else None
        if kind == "bad":
            errors.append(f"unexpected character {val!r} at {pos}")
        elif kind == "op" and val == "(":
            depth += 1
        elif kind == "op" and val == ")":
            depth -= 1
            if depth < 0:
                errors.append(f"unbalanced ')' at {pos}")
                depth = 0
        elif kind == "id":
            if nxt and nxt[1] == "(":
                calls.append(val)
            elif nxt and nxt[1] == "=" and depth > 0:
                kwargs.append(val)
            elif nxt and nxt[1] == "=" and depth == 0 and (prev is None or prev[1] == ";"):
                local_vars.append(val)
            elif val not in _LITERALS:
                idents.append(val)
    if depth > 0:
        errors.append(f"{depth} unclosed '('")
    body = strip_comments(expr).strip()
    if body.endswith(";"):
        errors.append("expression ends with ';' (last statement must be the alpha value)")
    if re.search(r"\(\s*,|,\s*,|,\s*\)", body):
        errors.append("empty argument")
    return {
        "operators": sorted(set(calls)),
        "identifiers": sorted(set(idents) - set(local_vars)),
        "kwargs": sorted(set(kwargs)),
        "variables": sorted(set(local_vars)),
        "errors": errors,
        "operator_count": len(calls),
    }


def check_expression(
    expr: str,
    operators: Iterable[str] | None = None,
    fields: Iterable[str] | None = None,
    fetch_operators: bool = True,
) -> Dict[str, Any]:
    """Lint an expression before spending a simulation.
    operators: allowed operator names (default: fetched from /operators, cached)
    fields:    known data-field ids; if given, unknown identifiers are reported as errors, otherwise as info.
    Returns {'ok', 'errors', 'warnings', 'operators', 'identifiers', ...}."""
    info = analyze_expression(expr)
    errors = list(info["errors"])
    warnings: List[str] = []
    ops = set(operators) if operators is not None else None
    if ops is None and fetch_operators:
        try:
            from .meta import operator_names

            ops = set(operator_names(scope=None))
        except Exception:  # noqa: BLE001
            ops = None
            warnings.append("could not fetch operator list; operator names not validated")
    if ops is not None:
        unknown_ops = [o for o in info["operators"] if o not in ops]
        if unknown_ops:
            errors.append(f"unknown operators: {', '.join(unknown_ops)}")
        info["unknown_operators"] = unknown_ops
    if fields is not None:
        known = set(fields)
        unknown = [f for f in info["identifiers"] if f not in known]
        if unknown:
            errors.append(f"unknown data fields/identifiers: {', '.join(unknown)}")
        info["unknown_identifiers"] = unknown
    return {"ok": not errors, "errors": errors, "warnings": warnings, **{k: v for k, v in info.items() if k != "errors"}}


def template_placeholders(template: str) -> List[str]:
    """Names of placeholders in a template. Supports `<name/>` and `{name}`."""
    seen: List[str] = []
    for a, b in _PLACEHOLDER.findall(template):
        name = a or b
        if name not in seen:
            seen.append(name)
    return seen


def expand_template(template: str, values: Dict[str, Sequence[Any]], limit: int = 100_000) -> List[str]:
    """Cartesian expansion of a template.
        expand_template("ts_mean(<field/>, <d/>)", {"field": ["close", "vwap"], "d": [5, 20]})
        -> ['ts_mean(close, 5)', 'ts_mean(close, 20)', 'ts_mean(vwap, 5)', 'ts_mean(vwap, 20)']"""
    names = template_placeholders(template)
    missing = [n for n in names if n not in values]
    if missing:
        raise ValueError(f"no values for placeholders: {missing}")
    total = 1
    for n in names:
        total *= max(1, len(values[n]))
    if total > limit:
        raise ValueError(f"template expands to {total} expressions (> limit {limit})")
    out: List[str] = []
    for combo in itertools.product(*(values[n] for n in names)):
        mapping = dict(zip(names, combo))
        out.append(_PLACEHOLDER.sub(lambda m: str(mapping[m.group(1) or m.group(2)]), template))
    return list(dict.fromkeys(out))
