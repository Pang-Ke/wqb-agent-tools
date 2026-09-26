"""Official BRAIN documentation (Learn section): tutorials index, pages as markdown, search,
operator docs, example alphas, video courses."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from .client import BrainClient, get_client
from .utils import html_to_text


def list_tutorials(client: BrainClient | None = None) -> List[Dict[str, Any]]:
    """GET /tutorials - documentation index: [{id, title, category, pages: [{id, title, duration, lastModified}]}]."""
    return (client or get_client()).paginate("/tutorials", limit=None, page_size=50)


def docs_index(client: BrainClient | None = None) -> List[Dict[str, str]]:
    """Flat list of documentation pages: [{page_id, title, section, category, lastModified}]."""
    rows = []
    for t in list_tutorials(client):
        for p in t.get("pages") or []:
            rows.append({"page_id": p.get("id"), "title": p.get("title"), "section": t.get("title"),
                         "category": t.get("category"), "lastModified": p.get("lastModified")})
    return rows


def _render_block(block: Dict[str, Any]) -> str:
    kind, value = block.get("type"), block.get("value")
    if kind == "TEXT":
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        text = re.sub(r"(?is)<style[^>]*>.*?</style>", "", text)
        return html_to_text(text)
    if kind == "HEADING":
        return "## " + html_to_text(value.get("content") if isinstance(value, dict) else str(value))
    if kind == "TABLE" and isinstance(value, dict):
        rows = value.get("data") or []
        if not rows:
            return ""
        cells = [[html_to_text(str(c)).replace("\n", " ") for c in r] for r in rows]
        head = "| " + " | ".join(cells[0]) + " |\n|" + "---|" * len(cells[0])
        return head + "\n" + "\n".join("| " + " | ".join(r) + " |" for r in cells[1:])
    if kind == "IMAGE" and isinstance(value, dict):
        return f"![{value.get('title', '')}]({value.get('url', '')})"
    if kind == "EQUATION":
        return f"$$ {value if isinstance(value, str) else json.dumps(value)} $$"
    if kind == "SIMULATION_EXAMPLE":
        return "```json\n" + json.dumps(value, ensure_ascii=False, indent=1) + "\n```"
    return f"[{kind}] " + (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))[:3000]


def get_doc_page(page_id: str, as_markdown: bool = True, client: BrainClient | None = None) -> Any:
    """GET /tutorial-pages/{id} - a documentation page, rendered to markdown by default."""
    data = (client or get_client()).get(f"/tutorial-pages/{page_id}")
    if not as_markdown:
        return data
    body = "\n\n".join(filter(None, (_render_block(b) for b in data.get("content") or [])))
    return f"# {data.get('title', page_id)}\n\n_lastModified: {data.get('lastModified')}_\n\n{body}"


def get_operator_doc(operator: str, as_markdown: bool = True, client: BrainClient | None = None) -> Any:
    """GET /operators/{name} - long-form documentation page of an operator."""
    data = (client or get_client()).get(f"/operators/{operator}")
    if not as_markdown:
        return data
    body = "\n\n".join(filter(None, (_render_block(b) for b in data.get("content") or [])))
    return f"# {data.get('title', operator)}\n\n{body}"


def search_docs(query: str, types: str = "reference\x1ftutorialPage\x1fvideo\x1frecommendedReading",
                client: BrainClient | None = None) -> Dict[str, Any]:
    """GET /search?query=... over documentation (reference, tutorialPage, video, recommendedReading)."""
    return (client or get_client()).get("/search", params={"query": query, "type": types})


def dump_docs(out_dir: str | Path, client: BrainClient | None = None) -> Dict[str, Any]:
    """Save every documentation page as markdown into out_dir (plus index.json)."""
    c = client or get_client()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    index = docs_index(c)
    saved, failed = 0, []
    for row in index:
        try:
            (out / f"{row['page_id']}.md").write_text(get_doc_page(row["page_id"], client=c), encoding="utf-8")
            saved += 1
        except Exception as exc:  # noqa: BLE001
            failed.append({"page_id": row["page_id"], "error": str(exc)})
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"saved": saved, "failed": failed, "dir": str(out.resolve())}


def example_alphas(limit: int = 50, client: BrainClient | None = None) -> List[Dict[str, Any]]:
    """GET /suggest/examples - official example alphas (settings + commented expression)."""
    return (client or get_client()).paginate("/suggest/examples", limit=limit, page_size=50)


def video_courses(client: BrainClient | None = None) -> List[Dict[str, Any]]:
    return (client or get_client()).paginate("/video-courses", limit=None, page_size=50)
