"""Small helpers: record-set decoding, HTML -> text, CSV/JSON output."""
from __future__ import annotations

import csv
import html
import io
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List


def recordset_to_dicts(payload: Any) -> List[Dict[str, Any]]:
    """BRAIN record sets are {'schema': {'properties': [{name,...}]}, 'records': [[...], ...]}.
    Convert to a list of dicts keyed by property name."""
    if not isinstance(payload, dict):
        return []
    schema = payload.get("schema") or {}
    cols = [p.get("name") for p in schema.get("properties") or []]
    return [dict(zip(cols, row)) for row in payload.get("records") or []]


def recordset_columns(payload: Any) -> List[str]:
    if not isinstance(payload, dict):
        return []
    return [p.get("name") for p in (payload.get("schema") or {}).get("properties") or []]


def html_to_text(value: str | None) -> str:
    text = value or ""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|h\d|tr|pre|blockquote)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = re.sub(r'(?is)<img[^>]*src="([^"]+)"[^>]*>', r"[image: \1]", text)
    text = re.sub(r'(?is)<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"\2 (\1)", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def flatten(row: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    """{'is': {'sharpe': 1.2}} -> {'is.sharpe': 1.2} (lists stay as-is)."""
    out: Dict[str, Any] = {}
    for k, v in row.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))
        else:
            out[key] = v
    return out


def to_csv(rows: Iterable[Dict[str, Any]], path: str | Path | None = None, flat: bool = True) -> str:
    rows = [flatten(r) if flat else r for r in rows]
    cols: List[str] = []
    for row in rows:
        for k in row.keys():
            if k not in cols:
                cols.append(k)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v) for k, v in row.items()})
    text = buf.getvalue()
    if path:
        Path(path).write_text(text, encoding="utf-8-sig")
    return text


def dump_json(data: Any, path: str | Path | None = None, indent: int | None = 2) -> str:
    text = json.dumps(data, ensure_ascii=False, indent=indent, default=str)
    if path:
        Path(path).write_text(text, encoding="utf-8")
    return text


def append_jsonl(path: str | Path, record: Any) -> None:
    with Path(path).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def read_jsonl(path: str | Path) -> List[Any]:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out
