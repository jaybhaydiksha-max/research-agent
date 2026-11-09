"""Tools the research agent can call (with retries, URL dedupe and SQLite-backed notes)."""
import os
import time
from urllib.parse import urldefrag
 
import requests
from bs4 import BeautifulSoup
from tavily import TavilyClient
 
import db
 
MAX_PAGE_CHARS = 6000
 
# Per-run state, reset by start_run().
_state = {"run_id": None, "read_urls": set(), "searches_since_note": 0}
MAX_SEARCHES_WITHOUT_NOTE = 3
 
 
def start_run(run_id: int):
    _state["run_id"] = run_id
    _state["read_urls"] = set()
    _state["searches_since_note"] = 0
 
 
def _norm(url: str) -> str:
    return urldefrag(url.strip())[0].rstrip("/")
 
 
def _retry(fn, attempts: int = 3, base_delay: float = 2):
    for i in range(attempts):
        try:
            return fn()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(base_delay * (i + 1))
 
 
def web_search(query: str, max_results: int = 5):
    # Guardrail: stop endless searching. Force the agent to read and save findings.
    if _state["searches_since_note"] >= MAX_SEARCHES_WITHOUT_NOTE:
        return {
            "error": "Too many searches without saving a note. Use read_page on the best "
            "results you already have, then save_note, before searching again."
        }
    _state["searches_since_note"] += 1
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    res = _retry(lambda: client.search(query=query, max_results=max_results))
    out = [
        {"title": r["title"], "url": r["url"], "snippet": r["content"][:300]}
        for r in res["results"]
    ]
    if not out:
        return {"error": "No results. Try different keywords."}
    return out
 
 
def read_page(url: str):
    key = _norm(url)
    if key in _state["read_urls"]:
        return {"error": "Already read this URL. Pick a different source."}
 
    r = None
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        except requests.RequestException as e:
            if attempt == 2:
                return {"error": f"Could not reach page: {e}. Try another source."}
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code in (401, 403, 404, 410):
            return {"error": f"HTTP {r.status_code}. Page is blocked or gone; try another source."}
        if r.status_code >= 500 and attempt < 2:
            time.sleep(2 * (attempt + 1))
            continue
        break
 
    if r is None or r.status_code >= 400:
        return {"error": f"HTTP {getattr(r, 'status_code', '?')}. Try another source."}
    if "html" not in r.headers.get("Content-Type", "").lower():
        return {"error": "Not an HTML page (maybe a PDF or file). Try another source."}
 
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ").split())
    if len(text) < 200:
        return {"error": "Page had almost no readable text (paywall or JavaScript page). Try another source."}
 
    _state["read_urls"].add(key)
    return {"url": url, "text": text[:MAX_PAGE_CHARS]}
 
 
def save_note(sub_question: str, finding: str, source_url: str):
    if not source_url.startswith("http"):
        return {"error": "source_url must be a full http(s) URL from your search or read results."}
    run_id = _state["run_id"]
    if run_id is None:
        return {"error": "No active run."}
    for n in db.get_notes(run_id):
        if n["source"] == source_url and n["finding"].strip() == finding.strip():
            return {"saved": False, "reason": "Duplicate note, skipped."}
    total = db.add_note(run_id, sub_question, finding, source_url)
    _state["searches_since_note"] = 0
    return {"saved": True, "total_notes": total}
 
 
def get_notes():
    run_id = _state["run_id"]
    return db.get_notes(run_id) if run_id is not None else []
 
 
TOOL_SCHEMAS = [
    {
        "name": "web_search",
        "description": "Search the web. Returns titles, URLs and short snippets. Use a different query each time.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "read_page",
        "description": "Fetch a URL and return its cleaned text. Use on the most authoritative search results. Each URL can be read only once.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "save_note",
        "description": "Save one short factual finding with its source URL. Every claim in the final report must come from a saved note.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sub_question": {"type": "string"},
                "finding": {"type": "string"},
                "source_url": {"type": "string"},
            },
            "required": ["sub_question", "finding", "source_url"],
        },
    },
    {
        "name": "get_notes",
        "description": "Return all saved notes so far. Use before deciding if research is sufficient.",
        "input_schema": {"type": "object", "properties": {}},
    },
]
 
TOOL_FUNCS = {
    "web_search": web_search,
    "read_page": read_page,
    "save_note": save_note,
    "get_notes": get_notes,
}
 
 
def run_tool(name: str, args: dict):
    func = TOOL_FUNCS.get(name)
    if func is None:
        return {"error": f"Unknown tool {name}"}
    try:
        return func(**args)
    except Exception as e:
        return {"error": str(e)}