"""Full Fast-Expression validator (quota-free pre-flight before simulating).

Checks
  syntax      : complete parse (statements `a = ...;`, ternary, infix/unary ops, keyword args, comments)
  operators   : exists (live /operators list), REGULAR scope, argument count, keyword names, duplicates
  arguments   : lookback `d` / `lookback` must be positive integer constants; numeric / boolean / string kwargs are
                literals of the right kind; `group` arguments must be grouping fields, bucket(), densify() or
                group_cartesian_product()
  data fields : exist, are available in the chosen region / delay / universe, and their type (MATRIX / VECTOR / GROUP)
  types       : VECTOR fields must be reduced with a vec_* operator before any other use; vec_* only takes VECTOR
                input; GROUP fields used as data are flagged
Signatures are parsed from the platform's operator definitions, so new/changed operators are picked up automatically.
"""
from __future__ import annotations

import difflib
import json
import re
import threading
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .client import BrainClient, BrainError, get_client
from .expr import strip_comments, tokenize

GROUP_KEYWORDS = {"country", "industry", "subindustry", "currency", "market", "sector", "exchange"}
LITERALS = {"true": ("bool", True), "false": ("bool", False), "nan": ("num", float("nan")), "NaN": ("num", float("nan")),
            "inf": ("num", float("inf")), "True": ("bool", True), "False": ("bool", False)}
WINDOW_PARAMS = {"d", "lookback"}
BOOL_PARAMS = {"filter", "dense", "usestd", "constantcheck", "skipboth", "nangroup"}
STRING_PARAMS = {"driver", "ignore", "range", "buckets"}
GROUP_PARAMS = {"group", "g1", "g2"}
GROUP_RETURNING = {"bucket", "group_cartesian_product"}
INFIX_NAMES = {"<": "less", ">": "greater", "<=": "less_equal", ">=": "greater_equal", "==": "equal", "!=": "not_equal",
               "+": "add", "-": "subtract", "*": "multiply", "/": "divide", "^": "power", "&&": "and", "||": "or"}
_lock = threading.Lock()


# ------------------------------------------------------------------ operator signatures
def _split_params(text: str) -> List[str]:
    out, depth, cur, quote = [], 0, "", None
    for ch in text:
        if quote:
            cur += ch
            if ch == quote or (quote == "“" and ch == "”"):
                quote = None
            continue
        if ch in "\"'“":
            quote = ch
            cur += ch
        elif ch == "(":
            depth += 1
            cur += ch
        elif ch == ")":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def parse_signature(definition: str, name: str) -> Optional[Dict[str, Any]]:
    """'ts_backfill(x,lookback = d, k=1)' -> {'positional': ['x'], 'keywords': {'lookback': 'd', 'k': '1'},
    'order': ['x', 'lookback', 'k'], 'variadic': False}. Several 'or'-separated forms are merged."""
    forms = re.split(r"\s*\bor\b\s*", definition.replace("\r", ""))
    sig = {"positional": [], "keywords": {}, "order": [], "variadic": False, "min_positional": 0}
    found = False
    for form in forms:
        m = re.search(re.escape(name) + r"\s*\(", form)
        if not m:
            continue
        start, depth, i = m.end(), 1, m.end()
        while i < len(form) and depth:
            depth += {"(": 1, ")": -1}.get(form[i], 0)
            i += 1
        params = _split_params(form[start:i - 1])
        found = True
        pos = []
        for p in params:
            if "..." in p or ".." in p:
                sig["variadic"] = True
                p = p.replace("...", "").replace("..", "").strip()
                if not p:
                    continue
            if "=" in p:
                k, v = p.split("=", 1)
                k = k.strip()
                sig["keywords"][k] = v.strip()
                if k not in sig["order"]:
                    sig["order"].append(k)
            else:
                p = re.sub(r"^\w+\((\w+)\)$", r"\1", p)          # bucket(rank(x), ...) -> x
                p = p.replace(" ", "")
                pos.append(p)
        if len(pos) > len(sig["positional"]):
            sig["positional"] = pos
    if not found:
        return None
    sig["order"] = sig["positional"] + [k for k in sig["order"] if k not in sig["positional"]]
    sig["min_positional"] = len(sig["positional"])
    return sig


def operator_signatures(client: BrainClient | None = None) -> Dict[str, Dict[str, Any]]:
    """{operator name: signature + scope/category}, derived from the live operator list (cached 24h)."""
    from .meta import list_operators

    sigs = {}
    for op in list_operators(client):
        s = parse_signature(op.get("definition") or "", op["name"])
        if s is None:  # infix-only definitions such as 'input1 < input2'
            s = {"positional": ["input1", "input2"], "keywords": {}, "order": ["input1", "input2"], "variadic": False,
                 "min_positional": 2}
        s.update(scope=op.get("scope") or [], category=op.get("category"))
        sigs[op["name"]] = s
    return sigs


# ------------------------------------------------------------------ field info (shared cache)
_FIELD_INFO_VERSION = 2


def _listed_type(c: BrainClient, field_id: str, dataset_id: str | None, region: str, delay: int,
                 universe: str) -> Optional[str]:
    """Type of a field as the dataset listing reports it (None if not found / request failed)."""
    if not dataset_id:
        return None
    try:
        res = c.get("/data-fields", params={"instrumentType": "EQUITY", "region": region, "delay": delay,
                                            "universe": universe, "dataset.id": dataset_id, "search": field_id,
                                            "limit": 50}, raise_on_error=False)
    except BrainError:
        return None
    rows = (res.get("results") or []) if isinstance(res, dict) else []
    for row in rows:
        if row.get("id") == field_id:
            return row.get("type")
    return None


def field_info(fields: Iterable[str], region: str = "USA", delay: int = 1, universe: str = "TOP3000",
               client: BrainClient | None = None) -> Dict[str, Optional[Dict[str, Any]]]:
    """{field: {'type', 'dataset', 'available', 'description'} | None if the id is not a data field}.
    Uses GET /data-fields/{id}; results are cached on disk (availability is evaluated for the given scope).
    The detail endpoint reports some event-data fields as MATRIX while the dataset listing (and the simulator) treat
    them as VECTOR, so the type is cross-checked against the listing and the listing wins."""
    c = client or get_client()
    path = c.cache_dir / "field_info.json"
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
    out, changed = {}, False
    for f in dict.fromkeys(fields):
        entry = cache.get(f, "missing")
        if isinstance(entry, dict) and entry.get("v") != _FIELD_INFO_VERSION:
            entry = "missing"   # cached before the type cross-check existed
        if entry == "missing":
            try:
                info = c.get(f"/data-fields/{f}", params={"instrumentType": "EQUITY", "region": region, "delay": delay,
                                                          "universe": universe}, raise_on_error=False)
            except BrainError:
                info = None
            if isinstance(info, dict) and info.get("id"):
                ds = (info.get("dataset") or {}).get("id")
                entry = {"v": _FIELD_INFO_VERSION, "type": _listed_type(c, f, ds, region, delay, universe) or info.get("type"),
                         "dataset": ds, "description": (info.get("description") or "")[:200],
                         "scopes": [[d.get("region"), d.get("delay"), d.get("universe")] for d in info.get("data") or []]}
            else:
                entry = None
            cache[f], changed = entry, True
        if entry is None:
            out[f] = None
        else:
            scopes = entry.get("scopes") or []
            avail = (not scopes) or any(s[0] == region and s[1] == delay and s[2] == universe for s in scopes)
            out[f] = {"type": entry.get("type"), "dataset": entry.get("dataset"), "available": avail,
                      "description": entry.get("description")}
    if changed:
        with _lock:
            path.write_text(json.dumps(cache), encoding="utf-8")
    return out


# ------------------------------------------------------------------ parser
class _Parser:
    def __init__(self, text: str):
        self.toks = [t for t in tokenize(text)]
        self.i = 0
        self.errors: List[str] = []

    def peek(self, k: int = 0):
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else ("eof", "", -1)

    def take(self):
        t = self.peek()
        self.i += 1
        return t

    @staticmethod
    def _where(pos: int) -> str:
        return "at end of expression" if pos < 0 else f"at position {pos}"

    def expect(self, val: str):
        t = self.take()
        if t[1] != val:
            raise SyntaxError(f"expected '{val}' {self._where(t[2])}, got '{t[1] or 'end of expression'}'")
        return t

    def program(self) -> List[Dict[str, Any]]:
        stmts = []
        while self.peek()[0] != "eof":
            if self.peek()[1] == ";":
                self.take()
                continue
            if self.peek()[0] == "id" and self.peek(1)[1] == "=":
                name, pos = self.take()[1], self.peek()[2]
                self.take()
                stmts.append({"t": "assign", "name": name, "value": self.expr(), "pos": pos})
            else:
                stmts.append({"t": "expr", "value": self.expr()})
            if self.peek()[0] != "eof":
                self.expect(";")
        return stmts

    def expr(self):
        cond = self.binary(0)
        if self.peek()[1] == "?":
            pos = self.take()[2]
            a = self.expr()
            self.expect(":")
            b = self.expr()
            return {"t": "call", "name": "if_else", "args": [cond, a, b], "kwargs": {}, "pos": pos, "infix": "?"}
        return cond

    _LEVELS = [{"||"}, {"&&"}, {"<", ">", "<=", ">=", "==", "!="}, {"+", "-"}, {"*", "/", "%"}]

    def binary(self, level: int):
        if level == len(self._LEVELS):
            return self.unary()
        node = self.binary(level + 1)
        while self.peek()[0] == "op" and self.peek()[1] in self._LEVELS[level]:
            op, pos = self.take()[1:]
            rhs = self.binary(level + 1)
            node = {"t": "call", "name": INFIX_NAMES.get(op, op), "args": [node, rhs], "kwargs": {}, "pos": pos, "infix": op}
        return node

    def unary(self):
        t = self.peek()
        if t[0] == "op" and t[1] in ("-", "+", "!"):
            self.take()
            val = self.unary()
            if t[1] == "+":
                return val
            if t[1] == "-" and val["t"] == "num":
                return {**val, "value": -val["value"]}
            return {"t": "call", "name": "reverse" if t[1] == "-" else "not", "args": [val], "kwargs": {}, "pos": t[2],
                    "infix": t[1]}
        return self.power()

    def power(self):
        base = self.primary()
        if self.peek()[1] == "^":
            pos = self.take()[2]
            return {"t": "call", "name": "power", "args": [base, self.unary()], "kwargs": {}, "pos": pos, "infix": "^"}
        return base

    def primary(self):
        kind, val, pos = self.take()
        if kind == "num":
            return {"t": "num", "value": float(val), "pos": pos, "int": re.fullmatch(r"\d+", val) is not None}
        if kind == "str":
            return {"t": "str", "value": val.strip("\"'“”"), "pos": pos}
        if kind == "id":
            if self.peek()[1] == "(":
                self.take()
                args, kwargs = [], {}
                if self.peek()[1] != ")":
                    while True:
                        if self.peek()[0] == "id" and self.peek(1)[1] == "=":
                            k = self.take()[1]
                            self.take()
                            if k in kwargs:
                                self.errors.append(f"{val}(): keyword '{k}' given twice")
                            kwargs[k] = self.expr()
                        else:
                            if kwargs:
                                self.errors.append(f"{val}(): positional argument after keyword argument")
                            args.append(self.expr())
                        if self.peek()[1] == ",":
                            self.take()
                            continue
                        break
                self.expect(")")
                return {"t": "call", "name": val, "args": args, "kwargs": kwargs, "pos": pos}
            if val in LITERALS:
                k, v = LITERALS[val]
                return {"t": k, "value": v, "pos": pos}
            return {"t": "id", "name": val, "pos": pos}
        if val == "(":
            node = self.expr()
            self.expect(")")
            return node
        if kind == "bad":
            raise SyntaxError(f"unexpected character '{val}' {self._where(pos)}")
        raise SyntaxError(f"unexpected '{val or 'end of expression'}' {self._where(pos)}")


def parse_expression(expression: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Parse into a list of statements (AST dicts). Returns (statements, syntax_errors)."""
    p = _Parser(strip_comments(expression))
    try:
        stmts = p.program()
    except SyntaxError as exc:
        return [], [str(exc)] + p.errors
    return stmts, p.errors


# ------------------------------------------------------------------ semantic checks
def _collect(node, calls: list, idents: list):
    if node["t"] == "call":
        calls.append(node)
        for a in node["args"]:
            _collect(a, calls, idents)
        for k, v in node["kwargs"].items():
            if k.lower() in STRING_PARAMS and v["t"] == "id":   # e.g. driver = gaussian (bare word, not a field)
                continue
            _collect(v, calls, idents)
    elif node["t"] == "id":
        idents.append(node["name"])


def validate_expression(
    expression: str,
    region: str = "USA",
    delay: int = 1,
    universe: str = "TOP3000",
    *,
    check_fields: bool = True,
    alpha_type: str = "REGULAR",
    client: BrainClient | None = None,
) -> Dict[str, Any]:
    """Validate a Fast Expression before simulating it.
    Returns {'ok', 'errors', 'warnings', 'operators', 'fields' {id: {type, dataset, available}},
             'variables', 'operator_count' (platform counting), 'datasets'}."""
    c = client or get_client()
    errors: List[str] = []
    warnings: List[str] = []
    stmts, syn = parse_expression(expression)
    if syn:
        return {"ok": False, "errors": syn, "warnings": [], "operators": [], "fields": {}, "variables": []}
    if not stmts:
        return {"ok": False, "errors": ["empty expression"], "warnings": [], "operators": [], "fields": {}, "variables": []}
    if stmts[-1]["t"] == "assign":
        errors.append(f"last statement assigns '{stmts[-1]['name']}'; the alpha must end with an expression")

    sigs = operator_signatures(c)
    calls, idents = [], []
    for s in stmts:
        _collect(s["value"], calls, idents)
    variables = [s["name"] for s in stmts if s["t"] == "assign"]
    for v in variables:
        if v in sigs:
            warnings.append(f"variable '{v}' shadows an operator name")

    candidates = [i for i in dict.fromkeys(idents) if i not in variables and i not in GROUP_KEYWORDS]
    finfo: Dict[str, Optional[Dict[str, Any]]] = {}
    if check_fields and candidates:
        finfo = field_info(candidates, region, delay, universe, c)
        for f, info in finfo.items():
            if info is None:
                sugg = difflib.get_close_matches(f, list(sigs), n=1)
                errors.append(f"unknown variable '{f}' (not a data field or defined variable)"
                              + (f"; did you mean operator '{sugg[0]}(...)'?" if sugg else ""))
            elif not info["available"]:
                errors.append(f"data field '{f}' is not available in {region}/D{delay}/{universe}")
    elif candidates:
        warnings.append(f"fields not verified (check_fields=False): {candidates}")

    var_types: Dict[str, str] = {}

    def kind_of(node) -> str:
        t = node["t"]
        if t in ("num", "bool", "str"):
            return {"num": "number", "bool": "bool", "str": "string"}[t]
        if t == "id":
            n = node["name"]
            if n in var_types:
                return var_types[n]
            if n in GROUP_KEYWORDS:
                return "group"
            info = finfo.get(n)
            if info:
                return {"VECTOR": "vector", "GROUP": "group"}.get(str(info.get("type")).upper(), "matrix")
            return "unknown"
        return check_call(node)

    def check_call(node) -> str:
        name, args, kwargs = node["name"], node["args"], node["kwargs"]
        label = node.get("infix") or f"{name}()"
        sig = sigs.get(name)
        if sig is None:
            sugg = difflib.get_close_matches(name, list(sigs), n=2)
            errors.append(f"unknown operator '{name}'" + (f" (did you mean {', '.join(sugg)}?)" if sugg else ""))
            for a in [*args, *kwargs.values()]:
                kind_of(a)
            return "matrix"
        if alpha_type.upper() in ("REGULAR", "REGION_AGNOSTIC") and sig["scope"] and "REGULAR" not in sig["scope"]:
            errors.append(f"operator '{name}' is not allowed in regular alphas (scope {sig['scope']})")
        # map arguments onto parameter names
        order, npos = sig["order"], len(sig["positional"])
        bound: List[Tuple[str, Dict[str, Any]]] = []
        for idx, a in enumerate(args):
            if idx < npos:
                bound.append((sig["positional"][idx], a))
            elif sig["variadic"]:                      # add/multiply/max/min: extra inputs are data, not keywords
                bound.append((sig["positional"][-1] if sig["positional"] else "x", a))
            elif idx < len(order):                     # keywords may also be passed positionally, in order
                bound.append((order[idx], a))
            else:
                errors.append(f"{label}: too many arguments ({len(args)} given, at most {len(order)})")
                break
        n_pos_given = len(args)
        if not node.get("infix") and n_pos_given < npos:
            missing = [p for p in sig["positional"][n_pos_given:] if p not in kwargs]
            if missing:
                errors.append(f"{label}: missing argument(s) {missing}")
        for k, v in kwargs.items():
            if k not in sig["keywords"] and k not in sig["positional"]:
                errors.append(f"{label}: unknown keyword '{k}' (valid: {sorted(sig['keywords']) or 'none'})")
            if any(k == b[0] for b in bound):
                errors.append(f"{label}: '{k}' given both positionally and as keyword")
            bound.append((k, v))
        # check each argument by role
        result = "matrix"
        arg_kinds = []
        for pname, a in bound:
            role = pname.lower()
            k = "string" if (role in STRING_PARAMS and a["t"] == "id") else kind_of(a)
            if role in WINDOW_PARAMS or (role == "k" and name == "kth_element"):
                if a["t"] != "num":
                    errors.append(f"{label}: '{pname}' must be a constant number, got an expression")
                elif not float(a["value"]).is_integer() or a["value"] < 1:
                    errors.append(f"{label}: '{pname}' must be a positive integer, got {a['value']:g}")
            elif role in BOOL_PARAMS:
                if not (a["t"] == "bool" or (a["t"] == "num" and a["value"] in (0, 1))):
                    errors.append(f"{label}: '{pname}' must be true/false")
            elif role in STRING_PARAMS:
                if a["t"] not in ("str", "id"):
                    errors.append(f"{label}: '{pname}' must be a string")
            elif role in GROUP_PARAMS:
                if k not in ("group", "unknown"):
                    errors.append(f"{label}: '{pname}' must be a grouping field (industry, sector, bucket(...), "
                                  f"group_cartesian_product(...)), got a {k}")
            elif pname in sig["keywords"] and role not in ("x", "y", "weight"):
                if a["t"] not in ("num", "bool", "str"):
                    warnings.append(f"{label}: '{pname}' is usually a constant")
            else:  # data argument
                arg_kinds.append(k)
                if k == "vector" and not name.startswith("vec_"):
                    errors.append(f"{label}: vector field passed directly; reduce it first with vec_avg/vec_sum/... "
                                  f"(platform error 'Invalid data field' / 'does not support event inputs')")
                if k == "group" and name not in ("densify",) and name not in GROUP_RETURNING:
                    warnings.append(f"{label}: grouping field used as data")
        if name.startswith("vec_"):
            if arg_kinds and arg_kinds[0] not in ("vector", "unknown"):
                errors.append(f"{label}: vec_* operators need a VECTOR field, got a {arg_kinds[0]}")
            return "matrix"
        if name in GROUP_RETURNING or (name == "densify" and arg_kinds[:1] == ["group"]):
            return "group"
        return result

    for s in stmts:
        k = kind_of(s["value"])
        if s["t"] == "assign":
            var_types[s["name"]] = k
    final_kind = var_types.get(stmts[-1].get("name")) if stmts[-1]["t"] == "assign" else kind_of(stmts[-1]["value"])
    if final_kind == "vector":
        errors.append("the alpha evaluates to a vector; reduce it with a vec_* operator")
    if final_kind in ("number", "bool", "string"):
        warnings.append("the alpha evaluates to a constant")

    from .pp import operator_count

    fields_out = {f: v for f, v in finfo.items() if v}
    return {
        "ok": not errors,
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
        "operators": sorted({cn["name"] for cn in calls}),
        "fields": fields_out,
        "datasets": sorted({v["dataset"] for v in fields_out.values() if v.get("dataset")}),
        "variables": variables,
        "operator_count": operator_count(expression),
    }


def validate_many(expressions: Iterable[str], region: str = "USA", delay: int = 1, universe: str = "TOP3000",
                  client: BrainClient | None = None) -> List[Dict[str, Any]]:
    """Validate a batch (field lookups are cached, so this is cheap after the first call)."""
    return [{"expression": e, **validate_expression(e, region, delay, universe, client=client)} for e in expressions]
