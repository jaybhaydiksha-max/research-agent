"""Evaluation harness: runs the agent on a benchmark of topics and measures quality.
 
For each topic it checks:
  - structure:  report has an Executive Summary and a Sources section
  - evidence:   >= MIN_URLS distinct URLs cited, >= MIN_NOTES notes saved
  - quality:    an LLM judge scores relevance, grounding and citations (1-5)
A topic PASSES if all checks pass and the judge average is >= JUDGE_THRESHOLD.
 
Results are appended to eval_results.csv, so you can run in small batches
(free API tiers have daily limits) and the summary covers everything so far.
 
Usage:
    python eval.py --limit 5          # run the next 5 unfinished topics
    python eval.py --limit 5 --no-judge
    python eval.py --summary          # just print the summary
    python eval.py --rerun            # ignore previous results and start over
"""
import argparse
import csv
import json
import re
import time
from pathlib import Path
 
import db
from agent import chat, run_research
 
RESULTS = Path(__file__).with_name("eval_results.csv")
FIELDS = [
    "topic", "status", "steps", "seconds", "urls", "notes", "sections_ok",
    "relevance", "grounding", "citations", "judge_avg", "passed", "error",
]
 
TOPICS = [
    "Impact of RBI's digital rupee on UPI",
    "Pros and cons of nuclear energy in India",
    "How retrieval-augmented generation reduces hallucinations in LLMs",
    "Current state of electric vehicle adoption in India",
    "What the evidence says about intermittent fasting and health",
    "India's semiconductor manufacturing push: progress and challenges",
    "Impact of AI coding assistants on software engineering jobs",
    "Pros and cons of remote work for productivity",
    "How GST has affected small businesses in India",
    "India's renewable energy targets and progress so far",
    "Kubernetes vs Docker Swarm: key differences and when to use each",
    "Climate change and its effect on Indian monsoon patterns",
    "UPI's international expansion to other countries",
    "Microplastics and human health: current evidence",
    "Comparing vector databases for RAG applications",
    "Trends in Indian startup funding in recent years",
    "Benefits and risks of generative AI in education",
    "How CRISPR gene editing works and its current medical uses",
    "Impact of social media on teenage mental health",
    "Open-source vs proprietary large language models: trade-offs",
]
 
MIN_URLS = 3
MIN_NOTES = 3
JUDGE_THRESHOLD = 3.5
 
JUDGE_PROMPT = """You are a strict evaluator of research reports. You are given a topic, the notes the
research agent saved (the ONLY evidence it was allowed to use), and its final report.
Score each criterion from 1 (poor) to 5 (excellent):
- relevance: does the report directly and completely address the topic?
- grounding: is every factual claim supported by the saved notes (no invented facts or numbers)?
- citations: are claims cited with [n] and do the numbered sources map to real URLs?
Reply with ONLY a JSON object, no other text, like:
{"relevance": 4, "grounding": 3, "citations": 5}"""
 
 
def judge(topic: str, report: str, notes: list[dict]):
    """LLM-as-judge. Returns (relevance, grounding, citations) or None if it can't be parsed."""
    messages = [
        {"role": "system", "content": JUDGE_PROMPT},
        {
            "role": "user",
            "content": f"Topic: {topic}\n\nSaved notes:\n{json.dumps(notes)[:6000]}\n\nReport:\n{report[:8000]}",
        },
    ]
    try:
        text = chat(messages, use_tools=False).content or ""
        data = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
        return tuple(float(data[k]) for k in ("relevance", "grounding", "citations"))
    except Exception:
        return None
 
 
def evaluate(topic: str, depth: str, use_judge: bool) -> dict:
    row = {k: "" for k in FIELDS}
    row["topic"] = topic
    start = time.time()
    try:
        report = run_research(topic, depth, on_event=lambda m: None)
    except Exception as e:
        row.update(status="failed", seconds=round(time.time() - start, 1),
                   passed=False, error=str(e)[:150].replace("\n", " "))
        return row
 
    run = db.list_runs(1)[0]  # runs are sequential, so the latest one is ours
    notes = db.get_notes(run["id"])
    urls = set(re.findall(r"https?://[^\s)\]>]+", report))
    lower = report.lower()
    sections_ok = "executive summary" in lower and "sources" in lower
 
    row.update(
        status=run["status"], steps=run["steps"], seconds=round(time.time() - start, 1),
        urls=len(urls), notes=len(notes), sections_ok=sections_ok,
    )
    passed = len(urls) >= MIN_URLS and len(notes) >= MIN_NOTES and sections_ok
 
    if use_judge:
        scores = judge(topic, report, notes)
        if scores:
            row.update(relevance=scores[0], grounding=scores[1], citations=scores[2],
                       judge_avg=round(sum(scores) / 3, 2))
            passed = passed and (sum(scores) / 3) >= JUDGE_THRESHOLD
        else:
            row["error"] = "judge output could not be parsed"
            passed = False
    row["passed"] = passed
    return row
 
 
def load_rows() -> list[dict]:
    if not RESULTS.exists():
        return []
    with open(RESULTS, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
 
 
def append_row(row: dict):
    new_file = not RESULTS.exists()
    with open(RESULTS, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            w.writeheader()
        w.writerow(row)
 
 
def summarize():
    rows = load_rows()
    if not rows:
        print("No results yet. Run: python eval.py --limit 5")
        return
 
    def avg(col, only_ok=True):
        vals = [float(r[col]) for r in rows if r[col] not in ("", None)]
        return sum(vals) / len(vals) if vals else None
 
    n = len(rows)
    passed = sum(r["passed"] == "True" for r in rows)
    failed = sum(r["status"] == "failed" for r in rows)
    limit_hit = sum(r["status"] == "step_limit" for r in rows)
 
    print("\n=== Evaluation summary ===")
    print(f"Topics evaluated : {n}")
    print(f"Success rate     : {passed}/{n} = {passed / n:.0%}")
    print(f"Crashed runs     : {failed}")
    print(f"Hit step limit   : {limit_hit}")
    for label, col, unit in [("Avg steps", "steps", ""), ("Avg time", "seconds", " s"),
                             ("Avg citations", "urls", ""), ("Avg notes saved", "notes", ""),
                             ("Avg judge score", "judge_avg", " / 5")]:
        v = avg(col)
        print(f"{label:<17}: {v:.1f}{unit}" if v is not None else f"{label:<17}: n/a")
    print(f"\nPer-topic details: {RESULTS.name}")
 
 
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5, help="max topics to run this time")
    ap.add_argument("--depth", default="quick", choices=["quick", "deep"])
    ap.add_argument("--no-judge", action="store_true", help="skip the LLM judge (saves API calls)")
    ap.add_argument("--pause", type=int, default=20, help="seconds to wait between topics")
    ap.add_argument("--rerun", action="store_true", help="delete old results and start over")
    ap.add_argument("--summary", action="store_true", help="only print the summary")
    args = ap.parse_args()
 
    if args.summary:
        summarize()
        return
    if args.rerun and RESULTS.exists():
        RESULTS.unlink()
 
    db.init_db()
    done = {r["topic"] for r in load_rows()}
    todo = [t for t in TOPICS if t not in done][: args.limit]
    if not todo:
        print("All topics are already evaluated.")
        summarize()
        return
 
    for i, topic in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {topic}")
        row = evaluate(topic, args.depth, not args.no_judge)
        append_row(row)
        verdict = "PASS" if row["passed"] is True else "FAIL"
        print(f"    {verdict} | status={row['status']} steps={row['steps']} "
              f"urls={row['urls']} notes={row['notes']} judge={row['judge_avg'] or 'n/a'} "
              f"{row['error']}")
        if i < len(todo):
            time.sleep(args.pause)
 
    summarize()
 
 
if __name__ == "__main__":
    main()