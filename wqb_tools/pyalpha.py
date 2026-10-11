"""Python alphas (simulation language PYTHON): static checks, payload building and simulation of @alpha modules.

A Python alpha is ONE self-contained module with exactly one function decorated with `@alpha(data=[...], store=[...])`.
The engine calls it once per day with `data.<field>` = 2-D float32 array [lookback + 1 rows, n_instruments] (today is
the last row; fewer rows during warm-up; read-only) and `data.universe` (1/0, always present). It must return a 1-D
float32 array [n_instruments]. `store` persists state between days. Only MATRIX fields load; VECTOR fields, the GLB
region and multi-simulation are not supported. Docs: 'getting-started-brain-python-alphas' (docs.get_doc_page).

Practical limits (observed): heavy per-day computation makes a simulation very slow, and the community reports
failures around a ~600 s budget, so vectorise across instruments, never loop over them, keep lookback as small as the logic needs, and
keep per-day work near O(n_instruments): cache intermediate rows in `store` (ring buffer, dims "xi") instead of
recomputing nested time-series windows, or use incremental (EWMA-style) state. A lookback-0 stateful alpha on
USA TOP3000 runs in about 2 minutes; a daily SVD on 3000 names with lookback 120 took over an hour, and the same
code on a 500-name universe about 6 minutes.

    import wqb_tools as W
    code = W.python_alpha_template(["returns"])            # skeleton to edit
    W.check_python_alpha(code, region="USA")               # static + field checks, no simulation used
    r = W.simulate_python("my_alpha.py", lookback=20, decay=4, neutralization="SUBINDUSTRY")
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, List, Optional

from .client import BrainClient

# settings the platform rejects when language = PYTHON
PY_UNSUPPORTED_SETTINGS = ("unitHandling", "nanHandling")
PY_UNSUPPORTED_REGIONS = ("GLB",)
MAX_LOOKBACK = 1024

_TEMPLATE = '''from brain.alphas import alpha
import numpy as np
import numpy.typing as npt


def cs_rank(x):
    """Cross-sectional rank in [0, 1]; NaN stays NaN."""
    out = np.full(x.shape, np.nan, dtype=np.float64)
    ok = np.isfinite(x)
    n = int(ok.sum())
    if n > 1:
        out[ok] = np.argsort(np.argsort(x[ok])) / (n - 1)
    return out


def last_valid(x):
    """Latest non-NaN value of each column of a [rows, n] window (a backfill over the lookback window)."""
    out = np.full(x.shape[1], np.nan, dtype=np.float64)
    for row in x[::-1]:
        need = np.isnan(out) & np.isfinite(row)
        out[need] = row[need]
    return out


@alpha(
    data={fields!r},
    store=[],
)
def {name}(data, store) -> npt.NDArray[np.float32]:
    n = data.universe.shape[1]
    out = np.full(n, np.nan, dtype=np.float32)
    in_univ = data.universe[-1] == 1
{body}
    out[in_univ] = signal[in_univ].astype(np.float32)
    return out
'''


def python_alpha_template(fields: List[str], name: str = "my_alpha") -> str:
    """A runnable starter module: imports, two numpy helpers (cs_rank, last_valid), the @alpha contract and a
    placeholder signal (sum of cross-sectional ranks of the latest valid value of each field). Edit the body."""
    lines = [f"    signal = np.zeros(n, dtype=np.float64)"]
    lines += [f"    signal += np.nan_to_num(cs_rank(last_valid(data.{f})) - 0.5)" for f in fields]
    return _TEMPLATE.format(fields=list(fields), name=name, body="\n".join(lines))


def load_python_alpha(code_or_path: str | Path) -> str:
    """Return the module source: reads the file when given a path to an existing .py file, else returns the string."""
    s = str(code_or_path)
    if "\n" not in s and s.endswith(".py") and Path(s).is_file():
        return Path(s).read_text(encoding="utf-8")
    return s


def _literal(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except Exception:  # noqa: BLE001
        return None


def inspect_python_alpha(code_or_path: str | Path) -> Dict[str, Any]:
    """Parse a Python alpha module without running it:
    {'function', 'fields' (data=[...]), 'store' (names), 'imports', 'n_alpha_functions', 'n_params', 'returns_float32'
     (an .astype(np.float32) is present), 'syntax_error'}."""
    code = load_python_alpha(code_or_path)
    out: Dict[str, Any] = {"function": None, "fields": [], "store": [], "imports": [], "n_alpha_functions": 0,
                           "n_params": None, "returns_float32": "float32" in code and ".astype(" in code,
                           "syntax_error": None}
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        out["syntax_error"] = f"line {exc.lineno}: {exc.msg}"
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out["imports"] += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            out["imports"].append(("." * node.level) + (node.module or ""))
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            call = dec if isinstance(dec, ast.Call) else None
            target = call.func if call else dec
            dname = target.id if isinstance(target, ast.Name) else getattr(target, "attr", None)
            if dname != "alpha":
                continue
            out["n_alpha_functions"] += 1
            out["function"] = node.name
            out["n_params"] = len(node.args.args)
            for kw in (call.keywords if call else []):
                val = _literal(kw.value)
                if kw.arg == "data" and isinstance(val, list):
                    out["fields"] = val
                elif kw.arg == "store":      # entries are names or typed dicts ({"name": ..., "extend": np.float64(0)})
                    for e in getattr(kw.value, "elts", []):
                        if isinstance(e, ast.Constant) and isinstance(e.value, str):
                            out["store"].append(e.value)
                        elif isinstance(e, ast.Dict):
                            out["store"] += [_literal(v) for k, v in zip(e.keys, e.values) if _literal(k) == "name"]
    return out


def check_python_alpha(code_or_path: str | Path, region: str | None = None, delay: int = 1,
                       universe: str | None = None, lookback: int | None = None,
                       client: BrainClient | None = None) -> Dict[str, Any]:
    """Static check of a Python alpha against the platform's rules (uses no simulation):
    one @alpha function taking (data, store); 'universe' not listed in data; no imports from brain other than
    brain.alphas and no local imports; float32 return; lookback within 0..1024; region not GLB; and, when `region`
    is given, every data field exists there and is a MATRIX field.
    Returns {'ok', 'errors', 'warnings', **inspect_python_alpha()}."""
    info = inspect_python_alpha(code_or_path)
    errors: List[str] = []
    warnings: List[str] = []
    if info["syntax_error"]:
        return {"ok": False, "errors": [f"syntax error: {info['syntax_error']}"], "warnings": [], **info}
    if info["n_alpha_functions"] != 1:
        errors.append(f"need exactly one @alpha-decorated function, found {info['n_alpha_functions']}")
    if info["n_params"] is not None and info["n_params"] != 2:
        errors.append(f"the alpha function must take exactly (data, store), found {info['n_params']} parameters")
    if "universe" in info["fields"]:
        errors.append("do not list 'universe' in data - it is always available as data.universe")
    if info["n_alpha_functions"] == 1 and not info["fields"]:
        warnings.append("data=[...] is empty or not a literal list of field names")
    for mod in info["imports"]:
        root = mod.lstrip(".").split(".")[0]
        if mod.startswith("."):
            errors.append(f"relative import '{mod}': the module must be self-contained")
        elif root == "brain" and mod != "brain.alphas":
            errors.append(f"import '{mod}' is not allowed in the alpha module (only brain.alphas)")
    if "brain.alphas" not in info["imports"]:
        errors.append("missing 'from brain.alphas import alpha'")
    if not info["returns_float32"]:
        warnings.append("no .astype(np.float32) found: the return value must be a float32 array")
    if lookback is None:
        warnings.append("lookback not given: the window has lookback + 1 rows (0 = today only); set it >= the longest "
                        "history the code reads (sparse fundamentals want ~250)")
    elif not 0 <= int(lookback) <= MAX_LOOKBACK:
        errors.append(f"lookback must be within 0..{MAX_LOOKBACK}")
    if region and region.upper() in PY_UNSUPPORTED_REGIONS:
        errors.append(f"region {region.upper()} is not supported for Python alphas")
    if region and info["fields"] and not errors:
        from .validate import field_info

        try:
            infos = field_info(info["fields"], region.upper(), delay, universe or "TOP3000", client=client)
        except Exception as exc:  # noqa: BLE001
            infos, _ = {}, warnings.append(f"could not look up the data fields: {str(exc)[:80]}")
        for f, fi in infos.items():
            if fi is None:
                errors.append(f"'{f}' is not a data field")
            elif fi.get("available") is False:
                errors.append(f"field '{f}' is not available in {region.upper()} delay {delay}")
            elif str(fi.get("type") or "MATRIX").upper() != "MATRIX":
                errors.append(f"field '{f}' is {fi.get('type')}: only MATRIX fields load in Python alphas")
    return {"ok": not errors, "errors": errors, "warnings": warnings, **info}


def python_payload(code_or_path: str | Path, lookback: int = 0, **settings: Any) -> Dict[str, Any]:
    """POST /simulations body for a Python alpha (language PYTHON, lookback set, unsupported settings removed)."""
    from .simulate import build_payload

    return build_payload(load_python_alpha(code_or_path), language="PYTHON", lookback=int(lookback), **settings)


def simulate_python(code_or_path: str | Path, lookback: int = 0, *, check: bool = True, wait: bool = True,
                    use_cache: bool = True, timeout: float = 7200, client: BrainClient | None = None,
                    **settings: Any) -> Dict[str, Any]:
    """Simulate a Python alpha (source string or path to a .py file). lookback = extra history rows (window =
    lookback + 1). check=True runs check_python_alpha first and returns {'ok': False, 'status': 'CHECK_FAILED',
    'errors'} without spending a simulation when it fails. Other settings as in simulate() (region, universe, decay,
    neutralization, truncation, max_trade, max_position...). Python simulations run one at a time (no multi-sim) and
    are slower than Fast Expression."""
    from .simulate import simulate

    code = load_python_alpha(code_or_path)
    if check:
        chk = check_python_alpha(code, settings.get("region"), settings.get("delay", 1), settings.get("universe"),
                                 lookback, client)
        if not chk["ok"]:
            return {"ok": False, "status": "CHECK_FAILED", "alpha_id": None, "errors": chk["errors"],
                    "warnings": chk["warnings"]}
    res = simulate(payload=python_payload(code, lookback, **settings), wait=wait, use_cache=use_cache,
                   timeout=timeout, client=client)
    return res
