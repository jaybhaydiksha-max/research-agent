Autonomous Research Agent

An agent that takes a topic, plans sub-questions, searches the web, reads sources, saves notes, reflects on gaps, and writes a cited Markdown report.

Architecture
User topic
   |
   v
[Planner] -> sub-questions
   |
   v
 Agent loop (max N steps) <-------------------+
   |-- web_search  --> candidate URLs         |
   |-- read_page   --> cleaned text           |
   |-- save_note   --> notebook (finding+URL) |
   |-- get_notes   --> reflect: enough? ------+ (no: search again)
   v (yes)
[Report writer] -> cited Markdown report
Setup
bash
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # add LLM_API_KEY (Gemini) and TAVILY_API_KEY
python agent.py "Impact of RBI's digital rupee on UPI"   # CLI
streamlit run app.py                                      # UI
python eval.py                                            # evaluation

Free keys: Tavily (app.tavily.com) and Google Gemini (aistudio.google.com/apikey) both have free tiers. The LLM is provider-agnostic: any OpenAI-compatible API (Gemini, Groq, OpenRouter) works by changing LLM_BASE_URL, LLM_MODEL and LLM_API_KEY in .env.

Project structure
File	Purpose
agent.py	Agent loop, system prompt, step limit and wrap-up guardrails
tools.py	Search, page reader (retries, URL dedupe), note tools
db.py	SQLite memory: runs, notes, reports
app.py	Streamlit UI with run history
eval.py	Benchmark script
4-Week Plan

Week 1: Core loop

Get agent.py running from the CLI on 5 topics
Understand each step of the tool-use loop; print every tool call
Commit to GitHub with a clean history

Week 2: Quality + guardrails

Improve the system prompt (planning, reflection, conflicting sources)
Add retries for failed page reads, dedupe URLs, cap tokens per page
Test the step-limit fallback on purpose

Week 3: Memory + UI

Replace in-memory notes with SQLite (store runs, notes, reports)
Polish the Streamlit UI: live progress, download button, history of past runs
Add quick vs deep modes

Week 4: Evaluation + shipping

Build a 20 to 30 topic eval set in eval.py; add an LLM-as-judge for accuracy and citation quality
Record success rate, average steps, average time, cost per report
Deploy to Hugging Face Spaces, write the README with a GIF demo and architecture diagram
Resume bullet (fill in your real numbers)

Built an autonomous research agent using LLM function-calling (Gemini, provider-agnostic) that plans sub-queries, searches and reads web sources, and generates cited reports; achieved X% success across a Y-topic benchmark, cutting manual research time from ~2 hours to under 5 minutes.

Stretch ideas
Parallel sub-question workers (multi-agent)
Source credibility scoring
PDF export
Human approval step before deep mode runs