"""Research agent loop: plan -> search -> read -> note -> reflect -> write.
 
Provider-agnostic: works with any OpenAI-compatible API (Gemini, Groq, OpenRouter, ...).
Configure via .env (LLM_API_KEY, LLM_BASE_URL, LLM_MODEL).
Every run, its notes and its report are stored in SQLite (see db.py).
"""
import json
import os
import time
from datetime import date
 
from dotenv import load_dotenv
from openai import (
    OpenAI,
    RateLimitError,
    InternalServerError,
    APIConnectionError,
    APITimeoutError,
)
 
import db
import tools
 
load_dotenv()
 
client = OpenAI(
    api_key=os.environ["LLM_API_KEY"],
    base_url=os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
)
MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
 
SYSTEM_TEMPLATE = """You are a careful research agent. Today's date is {today}.
 
WORKFLOW
1. PLAN: in your first reply, list 3-5 specific sub-questions that together cover the topic, then start searching.
2. RESEARCH each sub-question: web_search -> pick the 1-2 most authoritative results (regulators, government, research institutions, reputable news; avoid content farms) -> read_page -> save_note.
3. Use a different search query every time. Never re-read a URL. If read_page fails, move on to another result.
   After EVERY web_search you must read_page the best result and save_note before searching again. Never run more than 2 searches in a row without saving a note.
   Do not chase one specific document (for example a particular press release) for more than 2 searches. If you cannot find it, use reputable news or analysis that cites it and move on.
4. REFLECT: call get_notes. Check that every sub-question has at least one note and that key numbers have 2 independent sources where possible. If sources disagree, save both as separate notes and flag the conflict.
5. WRITE the final report as soon as you have enough evidence. Do not keep searching forever.
 
RULES
- Every factual claim in the report must come from a saved note. Cite it as [n].
- Prefer recent sources, and mention dates when a figure could be outdated.
- Never invent URLs, numbers or quotes. If evidence is thin, say so under Limitations.
- Notes must be short, factual, and contain one finding each.
 
REPORT FORMAT (Markdown)
# Title
## Executive Summary (3-5 sentences)
## Findings (one subsection per sub-question)
## Conflicting views (omit if none)
## Limitations
## Sources (numbered list: [n] title - URL)"""
 
DEPTH_STEPS = {"quick": 10, "deep": 25}
 
# Convert our tool schemas to the OpenAI function-calling format.
OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        },
    }
    for t in tools.TOOL_SCHEMAS
]
 
 
def build_system() -> str:
    return SYSTEM_TEMPLATE.format(today=date.today().isoformat())
 
 
def chat(messages, use_tools=True, retries=5):
    """LLM call with backoff. Retries rate limits, server errors and network drops."""
    for attempt in range(retries):
        try:
            kwargs = {"model": MODEL, "messages": messages}
            if use_tools:
                kwargs["tools"] = OPENAI_TOOLS
            return client.chat.completions.create(**kwargs).choices[0].message
        except (RateLimitError, InternalServerError, APIConnectionError, APITimeoutError) as e:
            if attempt == retries - 1:
                raise
            wait = 10 * (attempt + 1)
            print(f"LLM error ({type(e).__name__}); retrying in {wait}s...")
            time.sleep(wait)
 
 
def run_research(topic: str, depth: str = "quick", on_event=print) -> str:
    db.init_db()
    run_id = db.create_run(topic, depth)
    tools.start_run(run_id)
 
    max_steps = DEPTH_STEPS.get(depth, 10)
    system = build_system()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Research topic: {topic}"},
    ]
    step = 0
 
    try:
        for step in range(1, max_steps + 1):
            msg = chat(messages)
 
            # No tool calls means the model has written its final report.
            if not msg.tool_calls:
                report = msg.content or ""
                db.finish_run(run_id, report, "completed", step)
                on_event(f"[step {step}] Report written (run #{run_id}).")
                return report
 
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )
 
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    bad_args = False
                except json.JSONDecodeError:
                    args, bad_args = {}, True
 
                on_event(f"[step {step}] {tc.function.name}({json.dumps(args)[:120]})")
                if bad_args:
                    output = {"error": "Arguments were not valid JSON. Call the tool again with valid JSON."}
                else:
                    output = tools.run_tool(tc.function.name, args)
 
                # Trace: store every tool call so runs can be inspected later.
                db.add_event(
                    run_id,
                    step,
                    tc.function.name,
                    json.dumps(args)[:500],
                    json.dumps(output)[:500],
                )
 
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.function.name,
                        "content": json.dumps(output)[:8000],
                    }
                )
 
            # Guardrail: nudge the model to wrap up before the budget runs out.
            if max_steps - step == 3:
                messages.append(
                    {
                        "role": "user",
                        "content": "Your research budget is almost used up. Save any final findings, then write the final report.",
                    }
                )
 
        # Guardrail: step limit hit, force a final answer from the saved notes.
        on_event("Step limit reached. Writing report from notes collected so far.")
        notes = db.get_notes(run_id)
        final_messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"Topic: {topic}\n\nWrite the final cited Markdown report now, "
                f"using only these notes (number them in order as sources):\n{json.dumps(notes)}",
            },
        ]
        report = chat(final_messages, use_tools=False).content or ""
        db.finish_run(run_id, report, "step_limit", max_steps)
        return report
 
    except Exception:
        db.finish_run(run_id, "", "failed", step)
        raise
 
 
if __name__ == "__main__":
    import sys
 
    topic = " ".join(sys.argv[1:]) or "Impact of RBI's digital rupee on UPI"
    print(run_research(topic))
 