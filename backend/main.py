"""
Researcher API - Hypothesis-driven brand metric analysis
Supports both Anthropic Claude and OpenAI
Uses Tavily for web search
"""

import os
import json
import re
from typing import Dict, List, Any, Optional, Deque
from datetime import datetime
from dataclasses import dataclass
from collections import deque
import uuid
import time
import contextvars
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import FastAPI, HTTPException, Request, Body, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

# Observability (Application Insights)
try:
    from azure.monitor.opentelemetry import configure_azure_monitor
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    from opentelemetry.instrumentation.logging import LoggingInstrumentor
    from azure.monitor.query import LogsQueryClient
    from azure.identity import DefaultAzureCredential
except Exception:
    configure_azure_monitor = None
    FastAPIInstrumentor = None
    RequestsInstrumentor = None
    LogsQueryClient = None
    DefaultAzureCredential = None
    LoggingInstrumentor = None
from pydantic import BaseModel, Field
import anthropic
import openai
from openai import OpenAI
from tavily import TavilyClient

app = FastAPI(title="Researcher API", version="0.1.0")

# Simple password gate for the entire app (internal PLC)
# Client must send: Authorization: Bearer <password>
APP_PASSWORD = os.getenv("RESEARCHER_APP_PASSWORD")

@app.middleware("http")
async def password_gate(request: Request, call_next):
    """App-wide bearer password gate.

    NOTE: In Starlette/FastAPI middleware, raising HTTPException can surface as 500.
    We return JSONResponse directly for auth failures.
    """

    # Always allow CORS preflight
    if request.method == "OPTIONS":
        return await call_next(request)

    # Allow health checks unauthenticated
    if request.url.path in ("/health",):
        return await call_next(request)

    # If password not configured, fail closed
    if not APP_PASSWORD:
        return JSONResponse(status_code=503, content={"detail": "App password not configured"})

    auth = request.headers.get("authorization") or ""
    if not auth.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"detail": "Missing Authorization header"})

    token = auth.removeprefix("Bearer ").strip()
    if token != APP_PASSWORD:
        return JSONResponse(status_code=401, content={"detail": "Invalid credentials"})

    return await call_next(request)

# Configure Application Insights / Azure Monitor OpenTelemetry (best practice)
# Uses APPLICATIONINSIGHTS_CONNECTION_STRING from Key Vault.
if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING") and configure_azure_monitor:
    try:
        configure_azure_monitor()
        if RequestsInstrumentor:
            RequestsInstrumentor().instrument()
        if LoggingInstrumentor:
            # Capture stdlib logging into OpenTelemetry so it lands in AppTraces
            LoggingInstrumentor().instrument(set_logging_format=True)
        if FastAPIInstrumentor:
            FastAPIInstrumentor.instrument_app(app)
        print("✓ Application Insights telemetry enabled (traces + logs)")
    except Exception as e:
        print(f"⚠ Failed to enable Application Insights telemetry: {e}")

# Logger for durable run summaries (exported to App Insights)
import logging
telemetry_logger = logging.getLogger("researcher.telemetry")
telemetry_logger.setLevel(logging.INFO)

def _emit_run_event(run_summary: Dict[str, Any]):
    """Emit a durable run summary into App Insights via logs.

    In workspace-based App Insights this lands in AppTraces and is queryable.
    """
    try:
        telemetry_logger.info("ResearchRunSummary %s", json.dumps(run_summary, ensure_ascii=False))
    except Exception:
        pass


def _logs_client():
    if not LogsQueryClient or not DefaultAzureCredential:
        return None
    ws = os.getenv("LOG_ANALYTICS_WORKSPACE_ID")
    if not ws:
        return None
    return LogsQueryClient(DefaultAzureCredential()), ws


# CORS for frontend - explicitly allow the static web app
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://orange-island-01010220f.2.azurestaticapps.net",
        "http://localhost:5173",  # Local dev
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    max_age=3600,
)

# Initialize clients
anthropic_client = None
openai_client = None
tavily_client = None

def get_anthropic_client():
    global anthropic_client
    if anthropic_client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured")
        anthropic_client = anthropic.Anthropic(api_key=api_key)
    return anthropic_client

def get_openai_client():
    global openai_client
    if openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured")
        openai_client = OpenAI(api_key=api_key)
    return openai_client

def get_tavily_client():
    global tavily_client
    if tavily_client is None:
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            raise HTTPException(status_code=503, detail="TAVILY_API_KEY not configured")
        tavily_client = TavilyClient(api_key=api_key)
    return tavily_client


def openai_web_search(query: str, *, user_location: Optional[dict] = None, max_sources: int = 6) -> List[Dict[str, Any]]:
    """Use OpenAI Responses API web_search tool to retrieve web sources.

    Returns a list of dicts compatible with our existing pipeline:
      {"title": str, "url": str, "content": str, "raw_content": str}

    Note: This is only enabled when provider=='openai' and request.search_backend=='openai'.
    """

    client = get_openai_client()

    tools: List[Dict[str, Any]] = [{"type": "web_search"}]
    if user_location:
        tools = [{"type": "web_search", "user_location": user_location}]

    resp = client.responses.create(
        model=os.getenv("OPENAI_SEARCH_MODEL", OPENAI_MODEL),
        tools=tools,
        tool_choice="auto",
        include=["web_search_call.action.sources"],
        input=query,
    )

    d = resp.model_dump() if hasattr(resp, "model_dump") else {}

    sources: List[Dict[str, Any]] = []

    # Debug: log output item types and structure
    for i, item in enumerate(d.get("output") or []):
        t = item.get("type", "unknown")
        if t == "web_search_call":
            action = item.get("action") or {}
            src_list = action.get("sources") or []
            print(f"  [ws-debug] output[{i}] type=web_search_call, action_keys={list(action.keys())}, sources_count={len(src_list)}")
            if src_list:
                print(f"  [ws-debug] source[0] keys={list(src_list[0].keys())}")
            for s in src_list:
                url = s.get("url") or ""
                if not url:
                    continue
                sources.append({
                    "title": s.get("title") or "",
                    "url": url,
                    "content": s.get("snippet") or s.get("text") or "",
                    "raw_content": s.get("snippet") or s.get("text") or "",
                })
        elif t == "message":
            content = item.get("content") or []
            text_preview = ""
            for c in content:
                if c.get("text"):
                    text_preview = c["text"][:100]
                    break
            print(f"  [ws-debug] output[{i}] type=message, content_items={len(content)}, text_preview={text_preview}")
        else:
            print(f"  [ws-debug] output[{i}] type={t}, keys={list(item.keys())}")

    print(f"  [ws-debug] total sources extracted: {len(sources)}")
    return sources[:max_sources]


@app.get("/debug/web-search")
async def debug_web_search(request: Request, q: str = "new look fashion UK 2025"):
    """Debug endpoint to inspect raw OpenAI web_search response structure."""
    try:
        client = get_openai_client()
        resp = client.responses.create(
            model=os.getenv("OPENAI_SEARCH_MODEL", OPENAI_MODEL),
            tools=[{"type": "web_search"}],
            tool_choice="auto",
            include=["web_search_call.action.sources"],
            input=q,
        )
        d = resp.model_dump() if hasattr(resp, "model_dump") else {}
        # Summarize output items
        summary = []
        for i, item in enumerate(d.get("output") or []):
            t = item.get("type", "unknown")
            entry = {"index": i, "type": t, "keys": list(item.keys())}
            if t == "web_search_call":
                action = item.get("action") or {}
                entry["action_keys"] = list(action.keys())
                entry["action_type"] = action.get("type")
                entry["action_status"] = action.get("status")
                src = action.get("sources") or []
                entry["sources_count"] = len(src)
                if src:
                    entry["source_0"] = src[0]
            elif t == "message":
                for c in (item.get("content") or []):
                    if c.get("text"):
                        entry["text_preview"] = c["text"][:500]
                        break
            summary.append(entry)
        return {"output_count": len(d.get("output", [])), "items": summary, "model": d.get("model"), "usage": d.get("usage")}
    except Exception as e:
        return {"error": str(e)}


# Eagerly initialize Tavily at startup to catch config errors early
try:
    get_tavily_client()
    print("✓ Tavily client initialized")
except Exception as e:
    print(f"⚠ Tavily initialization failed: {e}")

# LLM Configuration
DEFAULT_PROVIDER = os.getenv("DEFAULT_LLM_PROVIDER", "anthropic")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Models
class ResearchRequest(BaseModel):
    question: str
    provider: Optional[str] = Field(default=None, description="LLM provider: 'anthropic' or 'openai'. Uses DEFAULT_LLM_PROVIDER env var if not specified.")
    # Search backend is only honored when provider=='openai' (per product decision).
    search_backend: Optional[str] = Field(default=None, description="Web search backend. For provider=openai: 'tavily' (default) or 'openai' (Responses web_search). Ignored for anthropic.")

class ResearchResponse(BaseModel):
    question: str
    brand: str
    metrics: List[str]  # Frontend expects array
    direction: str
    time_period: Optional[str]
    provider_used: str  # Which LLM provider was actually used
    hypotheses: Dict[str, List[Dict]]
    validated_hypotheses: Dict[str, List[Dict]]
    summary: Dict[str, List[Dict]]

    # Coaching / clarification
    coaching: Optional[Dict[str, Any]] = None

    # Telemetry
    run_id: Optional[str] = None
    latency_ms: Optional[int] = None
    tavily_searches: Optional[int] = None
    tavily_second_passes: Optional[int] = None
    llm_calls: Optional[int] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    tokens_total: Optional[int] = None

# --------------------
# Telemetry (in-memory ring buffer + per-request context)
# --------------------

_run_ctx: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar("run_ctx", default=None)
_eval_mode: contextvars.ContextVar[bool] = contextvars.ContextVar("eval_mode", default=False)
RUN_LOG: Deque[dict] = deque(maxlen=500)


def _run_metric_incr(key: str, amount: int = 1):
    ctx = _run_ctx.get()
    if not ctx:
        return
    ctx[key] = int(ctx.get(key, 0) or 0) + amount


def _run_metric_set(key: str, value: Any):
    ctx = _run_ctx.get()
    if not ctx:
        return
    ctx[key] = value


def _run_llm_record(call: dict):
    ctx = _run_ctx.get()
    if not ctx:
        return
    calls = ctx.setdefault("llm_call_details", [])
    calls.append(call)


# LLM Abstraction Layer
def llm_generate(prompt: str, provider: Optional[str] = None, max_tokens: int = 1000) -> str:
    """Generate text using the specified LLM provider.

    Also records per-call telemetry into the current run context (if present).
    """

    chosen_provider = provider or DEFAULT_PROVIDER
    started = time.time()

    if chosen_provider == "anthropic":
        client = get_anthropic_client()
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
        usage_obj = getattr(response, "usage", None)
        in_toks = int(getattr(usage_obj, "input_tokens", 0) or 0)
        out_toks = int(getattr(usage_obj, "output_tokens", 0) or 0)

        _run_metric_incr("llm_calls", 1)
        _run_metric_incr("tokens_in", in_toks)
        _run_metric_incr("tokens_out", out_toks)
        _run_llm_record(
            {
                "provider": "anthropic",
                "model": ANTHROPIC_MODEL,
                "latency_ms": int((time.time() - started) * 1000),
                "max_tokens": max_tokens,
                "tokens_in": in_toks,
                "tokens_out": out_toks,
                "prompt_chars": len(prompt or ""),
                "output_chars": len(text or ""),
            }
        )
        return text

    if chosen_provider == "openai":
        client = get_openai_client()
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.choices[0].message.content or ""
        usage_obj = getattr(response, "usage", None)
        in_toks = int(getattr(usage_obj, "prompt_tokens", 0) or 0)
        out_toks = int(getattr(usage_obj, "completion_tokens", 0) or 0)

        _run_metric_incr("llm_calls", 1)
        _run_metric_incr("tokens_in", in_toks)
        _run_metric_incr("tokens_out", out_toks)
        _run_llm_record(
            {
                "provider": "openai",
                "model": OPENAI_MODEL,
                "latency_ms": int((time.time() - started) * 1000),
                "max_tokens": max_tokens,
                "tokens_in": in_toks,
                "tokens_out": out_toks,
                "prompt_chars": len(prompt or ""),
                "output_chars": len(text or ""),
            }
        )
        return text

    raise HTTPException(status_code=400, detail=f"Unknown provider: {chosen_provider}. Use 'anthropic' or 'openai'.")

def _is_help_question(q: str) -> bool:
    ql = (q or "").strip().lower()
    if not ql:
        return False

    # Exact / prefix commands
    if re.match(r"^\s*(/help|help)\b", ql):
        return True

    # Natural language variants
    phrases = [
        "what do you do",
        "what can you do",
        "how do i use",
        "capabilities",
        "supported metrics",
        "what metrics",
    ]
    return any(p in ql for p in phrases)


def _help_payload() -> Dict[str, Any]:
    return {
        "kind": "help",
        "message": (
            "I’m a hypothesis-driven research assistant. I’m best at explaining *why a brand metric changed* by finding validating web evidence with citations.\n\n"
            "Right now I work best with questions about **Salience / mental availability**.\n\n"
            "For best results include: **brand**, **metric**, **direction (up/down)**, and a **time period** (and optionally a region)."
        ),
        "supported_metrics": ["salience"],
        "examples": [
            "Salience fell by 6 points in Q3 2025 for New Look — find external reasons with citations.",
            "Salience increased in Q4 2025 for Nike in China — what external events could explain it? Provide citations.",
        ],
        "note": "If you ask competitor-landscape or underperformance-by-market questions without a metric/timeframe, I’ll ask for clarification.",
    }


def _looks_like_metric_change(q: str) -> bool:
    ql = (q or "").lower()
    metric_words = ["salience", "awareness", "consideration", "preference", "intent", "nps", "share of voice"]
    change_words = ["increased", "decreased", "fell", "rose", "down", "up", "drop", "gain", "change"]
    return any(w in ql for w in metric_words) and any(w in ql for w in change_words)


def _coaching_payload(question: str, brand_hint: str = "") -> Dict[str, Any]:
    b = brand_hint or "the brand"
    return {
        "message": (
            "Your question is valid, but it doesn’t map cleanly to our current metric-change research pipeline. "
            "To get the best results, pick a timeframe and define what ‘underperforming’ means (revenue vs market share vs awareness/salience)."
        ),
        "suggested_questions": [
            f"Who are {b}'s biggest competitors globally and in Asia/Europe/US? Provide citations.",
            f"In 2024–2025, which regions is {b} underperforming in (North America, China, EMEA) based on revenue growth/decline? Provide citations.",
            f"Brand salience decreased for {b} in China in Q3 2025 — find external reasons with citations.",
        ],
        "need": ["timeframe", "definition_of_underperforming"],
    }


# Competitor Database
COMPETITOR_DB = {
    "new look": ["primark", "m&s", "asos", "next", "h&m", "shein", "zara"],
    "primark": ["new look", "h&m", "shein"],
    "zara": ["h&m", "shein", "asos"],
}

@app.get("/health")
def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@app.get("/telemetry/runs")
def telemetry_runs(limit: int = 50):
    """Return recent run summaries.

    Option 2 (durable): Query workspace-based Application Insights (Log Analytics).
    Fallback: in-memory ring buffer if query client isn't available.
    """
    lim = max(1, min(int(limit or 50), 200))

    lc = _logs_client()
    if lc:
        client, ws = lc
        query = f"""
AppTraces
| where Message startswith 'ResearchRunSummary '
| extend payload = substring(Message, strlen('ResearchRunSummary '))
| extend run = parse_json(payload)
| project run
| take {lim}
"""
        try:
            resp = client.query_workspace(ws, query)
            rows = []
            if resp and resp.tables:
                for r in resp.tables[0].rows:
                    rows.append(r[0])
            # rows are dict-like already
            return {"runs": rows}
        except Exception:
            pass

    items = list(RUN_LOG)[-lim:]
    return {"runs": items}


@app.get("/telemetry/summary")
def telemetry_summary():

    # Try durable query first
    lc = _logs_client()
    if lc:
        client, ws = lc
        query = """
AppTraces
| where Message startswith 'ResearchRunSummary '
| extend payload = substring(Message, strlen('ResearchRunSummary '))
| extend run = parse_json(payload)
| summarize
    runs=count(),
    tokens_total=sum(tolong(run.tokens_total)),
    tavily_searches=sum(tolong(run.tavily_searches)),
    tavily_second_passes=sum(tolong(run.tavily_second_passes))
"""
        try:
            resp = client.query_workspace(ws, query)
            if resp and resp.tables and resp.tables[0].rows:
                r = resp.tables[0].rows[0]
                return {
                    "runs": int(r[0] or 0),
                    "errors": 0,
                    "p50_latency_ms": None,
                    "p95_latency_ms": None,
                    "tokens_total": int(r[1] or 0),
                    "tavily_searches": int(r[2] or 0),
                    "tavily_second_passes": int(r[3] or 0),
                    "providers": {},
                }
        except Exception:
            pass

    # Fallback: in-memory
    items = list(RUN_LOG)
    if not items:
        return {
            "runs": 0,
            "errors": 0,
            "p50_latency_ms": None,
            "p95_latency_ms": None,
            "tokens_total": 0,
            "tavily_searches": 0,
            "tavily_second_passes": 0,
            "providers": {},
        }

    latencies = sorted([int(i.get("latency_ms", 0) or 0) for i in items if i.get("latency_ms") is not None])

    def pct(p: float):
        if not latencies:
            return None
        idx = int(round((p / 100.0) * (len(latencies) - 1)))
        return latencies[max(0, min(idx, len(latencies) - 1))]

    providers = {}
    for i in items:
        pr = i.get("provider") or "unknown"
        providers[pr] = providers.get(pr, 0) + 1

    return {
        "runs": len(items),
        "errors": len([i for i in items if i.get("error")]),
        "p50_latency_ms": pct(50),
        "p95_latency_ms": pct(95),
        "tokens_total": sum(int(i.get("tokens_total", 0) or 0) for i in items),
        "tavily_searches": sum(int(i.get("tavily_searches", 0) or 0) for i in items),
        "tavily_second_passes": sum(int(i.get("tavily_second_passes", 0) or 0) for i in items),
        "providers": providers,
    }

@app.get("/eval/questions")
def eval_questions():
    """Return the hardcoded eval question set."""
    try:
        with open(os.path.join(os.path.dirname(__file__), "eval_questions.json"), "r", encoding="utf-8") as f:
            return {"questions": json.load(f)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Eval questions load error: {e}")


def _score_response(resp: dict) -> dict:
    """Heuristic scoring for eval comparisons (0-100)."""
    summary = resp.get("summary") or {}
    macro = summary.get("macro_drivers") or []
    brand = summary.get("brand_drivers") or []
    comp = summary.get("competitive_drivers") or []

    sections_nonempty = int(bool(macro)) + int(bool(brand)) + int(bool(comp))
    drivers_total = len(macro) + len(brand) + len(comp)

    citations = []
    for d in (macro + brand + comp):
        for u in (d.get("source_urls") or []):
            if u:
                citations.append(u)

    unique_domains = set()
    for u in citations:
        try:
            from urllib.parse import urlparse
            unique_domains.add(urlparse(u).netloc.replace("www.", ""))
        except Exception:
            pass

    citations_total = len(citations)
    unique_domains_n = len(unique_domains)

    # Simple score
    score = 0
    score += min(citations_total, 6) * 5  # up to 30
    score += sections_nonempty * 10       # up to 30
    score += min(drivers_total, 6) * 3    # up to 18
    score += min(unique_domains_n, 5) * 2 # up to 10

    if citations_total == 0:
        score -= 10
    if drivers_total == 0:
        score -= 15

    score = max(0, min(100, score))

    return {
        "score": score,
        "drivers_total": drivers_total,
        "sections_nonempty": sections_nonempty,
        "citations_total": citations_total,
        "unique_domains": unique_domains_n,
    }


@app.post("/feedback")
def feedback(payload: dict = Body(...)):
    """Collect thumbs up/down feedback tied to a run.

    Expected payload:
      { run_id, rating: 1|-1, comment?, question?, provider? }
    """
    run_id = payload.get("run_id")
    rating = payload.get("rating")
    if rating not in (1, -1):
        raise HTTPException(status_code=400, detail="rating must be 1 or -1")

    evt = {
        "kind": "UserFeedback",
        "run_id": run_id,
        "rating": rating,
        "comment": (payload.get("comment") or "")[:2000],
        "question": (payload.get("question") or "")[:500],
        "provider": payload.get("provider") or payload.get("provider_used"),
        "timestamp": datetime.now().isoformat(),
    }
    _emit_run_event(evt)
    return {"ok": True}


@app.post("/eval/run")
def eval_run(payload: dict = Body(...)):
    """Run the eval set against both providers and return scores.

    Payload:
      { "providerA": "openai", "providerB": "anthropic", "limit": 10 }
    """

    providerA = (payload.get("providerA") or "openai").lower()
    providerB = (payload.get("providerB") or "anthropic").lower()
    limit = int(payload.get("limit") or 3)

    # load questions
    qs = eval_questions().get("questions", [])
    qs = qs[: max(1, min(limit, len(qs)))]

    results = []

    for q in qs:
        qtext = q.get("text")
        if not qtext:
            continue

        for prov in [providerA, providerB]:
            # call our own research function directly (no HTTP)
            token_eval = _eval_mode.set(True)
            try:
                resp_model = research(ResearchRequest(question=qtext, provider=prov))
            finally:
                _eval_mode.reset(token_eval)
            resp = resp_model.model_dump() if hasattr(resp_model, "model_dump") else dict(resp_model)

            score = _score_response(resp)

            eval_event = {
                "kind": "EvalRun",
                "question_id": q.get("id"),
                "question": qtext,
                "provider": prov,
                "run_id": resp.get("run_id"),
                "score": score,
                "latency_ms": resp.get("latency_ms"),
                "tokens_total": resp.get("tokens_total"),
                "tavily_searches": resp.get("tavily_searches"),
                "validated_counts": (resp.get("validated_counts") or resp.get("summary")),
                "timestamp": datetime.now().isoformat(),
            }
            _emit_run_event(eval_event)

            results.append({
                "question_id": q.get("id"),
                "provider": prov,
                "score": score,
                "response": resp,
            })

    return {"results": results}


@app.post("/research")
def research(req: ResearchRequest):
    """Main research endpoint - hypothesis-driven analysis"""

    run_id = str(uuid.uuid4())
    started_at = time.time()

    # Determine which provider to use (request param > env var > default)
    provider = req.provider or DEFAULT_PROVIDER

    token = _run_ctx.set(
        {
            "run_id": run_id,
            "provider": provider,
            "question": req.question,
            "search_backend": req.search_backend or "tavily",
            "started_at": datetime.now().isoformat(),
            "tavily_searches": 0,
            "tavily_second_passes": 0,
            "llm_calls": 0,
            "tokens_in": 0,
            "tokens_out": 0,
        }
    )

    try:
        # Help shortcut
        if _is_help_question(req.question):
            latency_ms = int((time.time() - started_at) * 1000)
            help_payload = _help_payload()
            RUN_LOG.append(
                {
                    "run_id": run_id,
                    "started_at": datetime.now().isoformat(),
                    "latency_ms": latency_ms,
                    "provider": provider,
                    "question": req.question,
                    "brand": None,
                    "time_period": None,
                    "tavily_searches": 0,
                    "tavily_second_passes": 0,
                    "llm_calls": int((_run_ctx.get() or {}).get("llm_calls", 0) or 0),
                    "tokens_in": int((_run_ctx.get() or {}).get("tokens_in", 0) or 0),
                    "tokens_out": int((_run_ctx.get() or {}).get("tokens_out", 0) or 0),
                    "tokens_total": int((_run_ctx.get() or {}).get("tokens_in", 0) or 0) + int((_run_ctx.get() or {}).get("tokens_out", 0) or 0),
                    "help": True,
                }
            )

            return ResearchResponse(
                question=req.question,
                brand="help",
                metrics=["salient"],
                direction="change",
                time_period=None,
                provider_used=provider,
                hypotheses={"market": [], "brand": [], "competitive": []},
                validated_hypotheses={"market": [], "brand": [], "competitive": []},
                summary={"macro_drivers": [], "brand_drivers": [], "competitive_drivers": []},
                coaching=help_payload,
                run_id=run_id,
                latency_ms=latency_ms,
                tavily_searches=0,
                tavily_second_passes=0,
                llm_calls=int((_run_ctx.get() or {}).get("llm_calls", 0) or 0),
                tokens_in=int((_run_ctx.get() or {}).get("tokens_in", 0) or 0),
                tokens_out=int((_run_ctx.get() or {}).get("tokens_out", 0) or 0),
                tokens_total=int((_run_ctx.get() or {}).get("tokens_in", 0) or 0) + int((_run_ctx.get() or {}).get("tokens_out", 0) or 0),
            )

        # STRICT coaching mode: if question isn't a metric-change question, coach instead of forcing the pipeline
        if not _looks_like_metric_change(req.question):
            brand_guess = "unknown"
            m = re.search(r"\b([A-Z][A-Za-z0-9&\- ]{1,30})\b", req.question)
            if m:
                brand_guess = m.group(1).strip().lower()

            latency_ms = int((time.time() - started_at) * 1000)
            coaching = _coaching_payload(req.question, brand_hint=brand_guess)

            run_summary = {
                "run_id": run_id,
                "started_at": datetime.now().isoformat(),
                "latency_ms": latency_ms,
                "provider": provider,
                "question": req.question,
                "brand": brand_guess,
                "time_period": None,
                "tavily_searches": 0,
                "tavily_second_passes": 0,
                "llm_calls": int((_run_ctx.get() or {}).get("llm_calls", 0) or 0),
                "tokens_in": int((_run_ctx.get() or {}).get("tokens_in", 0) or 0),
                "tokens_out": int((_run_ctx.get() or {}).get("tokens_out", 0) or 0),
                "tokens_total": int((_run_ctx.get() or {}).get("tokens_in", 0) or 0) + int((_run_ctx.get() or {}).get("tokens_out", 0) or 0),
                "validated_counts": {"market": 0, "brand": 0, "competitive": 0},
                "coached": True,
            }
            RUN_LOG.append(run_summary)
            _emit_run_event(run_summary)

            return ResearchResponse(
                question=req.question,
                brand=brand_guess,
                metrics=["salient"],
                direction="change",
                time_period=None,
                provider_used=provider,
                hypotheses={"market": [], "brand": [], "competitive": []},
                validated_hypotheses={"market": [], "brand": [], "competitive": []},
                summary={"macro_drivers": [], "brand_drivers": [], "competitive_drivers": []},
                coaching=coaching,
                run_id=run_id,
                latency_ms=latency_ms,
                tavily_searches=0,
                tavily_second_passes=0,
                llm_calls=run_summary["llm_calls"],
                tokens_in=run_summary["tokens_in"],
                tokens_out=run_summary["tokens_out"],
                tokens_total=run_summary["tokens_total"],
            )

        # Step 1: Parse question
        parsed = parse_question(req.question, provider=provider)
        
        # Step 2: Get competitors
        competitors = COMPETITOR_DB.get(parsed["brand"], [])
        
        # Step 3: Generate hypotheses
        hypotheses = generate_hypotheses(parsed, competitors, provider=provider)
        
        # Step 4: Process hypotheses in parallel (search + validate)
        validated, meta = process_hypotheses_parallel(hypotheses, parsed, provider=provider)
        _run_metric_set("tavily_searches", int(meta.get("tavily_searches", 0) or 0))
        _run_metric_set("tavily_second_passes", int(meta.get("tavily_second_passes", 0) or 0))
        
        # Step 5: Build summary
        summary = build_summary(validated)
        
        # Handle metric - ensure it's an array for frontend
        metric_val = parsed.get("metric", "salient")
        if isinstance(metric_val, str):
            metrics_arr = [metric_val]
        elif isinstance(metric_val, list):
            metrics_arr = metric_val
        else:
            metrics_arr = ["salient"]
        
        ctx = _run_ctx.get() or {}
        latency_ms = int((time.time() - started_at) * 1000)
        _run_metric_set("latency_ms", latency_ms)
        _run_metric_set("brand", parsed.get("brand"))
        _run_metric_set("time_period", parsed.get("time_period"))

        # finalize totals
        tokens_in = int(ctx.get("tokens_in", 0) or 0)
        tokens_out = int(ctx.get("tokens_out", 0) or 0)

        run_summary = {
            "run_id": ctx.get("run_id"),
            "started_at": ctx.get("started_at"),
            "latency_ms": latency_ms,
            "provider": provider,
            "question": req.question,
            "brand": parsed.get("brand"),
            "time_period": parsed.get("time_period"),
            "tavily_searches": int(meta.get("tavily_searches", 0) or 0),
            "tavily_second_passes": int(meta.get("tavily_second_passes", 0) or 0),
            "llm_calls": int(ctx.get("llm_calls", 0) or 0),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "tokens_total": tokens_in + tokens_out,
            "validated_counts": {
                "market": len(validated.get("market", []) or []),
                "brand": len(validated.get("brand", []) or []),
                "competitive": len(validated.get("competitive", []) or []),
            },
        }
        RUN_LOG.append(run_summary)
        _emit_run_event(run_summary)

        return ResearchResponse(
            question=req.question,
            brand=parsed.get("brand") or "unknown",
            metrics=metrics_arr,
            direction=parsed.get("direction") or "change",
            time_period=parsed.get("time_period"),
            provider_used=provider,
            hypotheses=hypotheses,
            validated_hypotheses=validated,
            summary=summary,
            run_id=run_id,
            latency_ms=latency_ms,
            tavily_searches=int(meta.get("tavily_searches", 0) or 0),
            tavily_second_passes=int(meta.get("tavily_second_passes", 0) or 0),
            llm_calls=run_summary["llm_calls"],
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_total=tokens_in + tokens_out,
        )
    except anthropic.BadRequestError as e:
        error_msg = str(e)
        if "credit balance is too low" in error_msg or "purchase credits" in error_msg:
            raise HTTPException(
                status_code=402,
                detail="API credits exhausted. Please add credits to your Anthropic account at https://console.anthropic.com/settings/plans"
            )
        raise HTTPException(status_code=400, detail=f"Anthropic model error: {error_msg}")
    except openai.BadRequestError as e:
        error_msg = str(e)
        if "insufficient_quota" in error_msg or "billing" in error_msg:
            raise HTTPException(
                status_code=402,
                detail="API credits exhausted. Please check your OpenAI account billing at https://platform.openai.com/settings/organization/billing/overview"
            )
        raise HTTPException(status_code=400, detail=f"OpenAI model error: {error_msg}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Research error: {str(e)}")
    finally:
        # clear run context
        _run_ctx.reset(token)

@app.post("/research/stream")
def research_stream(req: ResearchRequest):
    """Streaming research endpoint (SSE).

    Emits incremental events so the UI can render results as they arrive.
    """

    provider = req.provider or DEFAULT_PROVIDER

    def sse(event: str, data: Any):
        payload = json.dumps(data, ensure_ascii=False)
        return f"event: {event}\ndata: {payload}\n\n"

    def event_gen():
        run_id = str(uuid.uuid4())
        started_at = datetime.now()
        token = _run_ctx.set(
            {
                "run_id": run_id,
                "provider": provider,
                "question": req.question,
                "started_at": started_at.isoformat(),
                "tavily_searches": 0,
                "tavily_second_passes": 0,
                "llm_calls": 0,
                "tokens_in": 0,
                "tokens_out": 0,
            }
        )

        yield sse("status", {"stage": "start", "provider": provider, "run_id": run_id})

        # Help shortcut (stream)
        if _is_help_question(req.question):
            yield sse("final", {
                "question": req.question,
                "brand": "help",
                "metrics": ["salient"],
                "direction": "change",
                "time_period": None,
                "provider_used": provider,
                "hypotheses": {"market": [], "brand": [], "competitive": []},
                "validated_hypotheses": {"market": [], "brand": [], "competitive": []},
                "summary": {"macro_drivers": [], "brand_drivers": [], "competitive_drivers": []},
                "coaching": _help_payload(),
            })
            return

        # STRICT coaching mode (stream): coach instead of forcing the pipeline
        if not _looks_like_metric_change(req.question):
            brand_guess = "unknown"
            m = re.search(r"\b([A-Z][A-Za-z0-9&\- ]{1,30})\b", req.question)
            if m:
                brand_guess = m.group(1).strip().lower()

            coaching = _coaching_payload(req.question, brand_hint=brand_guess)
            yield sse("final", {
                "question": req.question,
                "brand": brand_guess,
                "metrics": ["salient"],
                "direction": "change",
                "time_period": None,
                "provider_used": provider,
                "hypotheses": {"market": [], "brand": [], "competitive": []},
                "validated_hypotheses": {"market": [], "brand": [], "competitive": []},
                "summary": {"macro_drivers": [], "brand_drivers": [], "competitive_drivers": []},
                "coaching": coaching,
            })
            return

        # Step 1: Parse question
        parsed = parse_question(req.question, provider=provider)
        yield sse("parsed", parsed)

        # Step 2: Get competitors
        competitors = COMPETITOR_DB.get(parsed.get("brand", ""), [])
        yield sse("competitors", {"competitors": competitors})

        # Step 3: Generate hypotheses
        hypotheses = generate_hypotheses(parsed, competitors, provider=provider)
        yield sse("hypotheses", hypotheses)

        # Step 4: Process hypotheses in parallel and stream results
        search_backend = (req.search_backend or "tavily").lower()
        use_openai_search = (provider == "openai" and search_backend == "openai")
        tavily = None if use_openai_search else get_tavily_client()
        tasks: List[tuple[Dict, str]] = []
        for cat in ["market", "brand", "competitive"]:
            for hyp in hypotheses.get(cat, []) or []:
                tasks.append((hyp, cat))

        validated = {"market": [], "brand": [], "competitive": []}
        yield sse("status", {"stage": "search", "total_hypotheses": len(tasks)})

        def refine_query(original: str) -> str:
            brand = parsed.get("brand") or ""
            tp = parsed.get("time_period") or ""
            region = "UK" if "uk" not in original.lower() else ""
            return " ".join([original, brand, tp, region, "retail"]).strip()

        def process_one(hyp: Dict, cat: str) -> Dict:
            query = hyp.get("search_query") or hyp.get("hypothesis") or ""
            if not query:
                return {"category": cat, "hypothesis": hyp.get("hypothesis"), "validated": False, "error": "empty_query"}

            # Pass 1
            if use_openai_search:
                try:
                    r1 = openai_web_search(query)
                except Exception as e:
                    print(f"OpenAI web_search error for '{query[:30]}...': {e}")
                    r1 = []
            else:
                _run_metric_incr("tavily_searches", 1)
                sr1 = tavily.search(
                    query=query,
                    search_depth="basic",
                    max_results=3,
                    include_raw_content=True,
                )
                r1 = sr1.get("results", []) or []
            validation = {"validated": False, "evidence": ""}
            if r1:
                validation = validate_hypothesis(hyp, r1, provider=provider)

            # Option A second pass when weak
            second_pass_used = False
            second_query = None
            if (not use_openai_search) and ((not r1) or (len(r1) < 2) or (not validation.get("validated"))):
                q2 = refine_query(query)
                if q2 and q2 != query:
                    second_pass_used = True
                    second_query = q2
                    _run_metric_incr("tavily_searches", 1)
                    _run_metric_incr("tavily_second_passes", 1)
                    sr2 = tavily.search(
                        query=q2,
                        search_depth="basic",
                        max_results=3,
                        include_raw_content=True,
                    )
                    r2 = sr2.get("results", []) or []
                    combined = (r1 + r2)[:4]
                    if combined:
                        validation2 = validate_hypothesis(hyp, combined, provider=provider)
                        if validation2.get("validated"):
                            validation = validation2
                            r1 = combined

            return {
                "category": cat,
                "hypothesis": hyp.get("hypothesis"),
                "search_query": query,
                "second_pass_used": second_pass_used,
                "second_query": second_query,
                "validated": bool(validation.get("validated")),
                "confidence": hyp.get("confidence"),
                "evidence": validation.get("evidence", ""),
                "source": (r1[0].get("url") if r1 else None),
                "source_title": (r1[0].get("title") if r1 else None),
                "result_count": len(r1),
            }

        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_task = {executor.submit(process_one, hyp, cat): (hyp, cat) for hyp, cat in tasks}
            completed = 0
            for future in as_completed(future_to_task):
                completed += 1
                hyp, cat = future_to_task[future]
                try:
                    item = future.result()
                except Exception as e:
                    item = {
                        "category": cat,
                        "hypothesis": hyp.get("hypothesis"),
                        "validated": False,
                        "error": str(e),
                    }
                if item.get("validated"):
                    validated[cat].append(
                        {
                            "status": "VALIDATED",
                            "hypothesis": item.get("hypothesis"),
                            "evidence": item.get("evidence"),
                            "source": item.get("source"),
                            "source_title": item.get("source_title"),
                        }
                    )

                yield sse(
                    "hypothesis_result",
                    {
                        **item,
                        "completed": completed,
                        "total": len(tasks),
                    },
                )

        # Step 5: Build summary + final response
        summary = build_summary(validated)

        metric_val = parsed.get("metric", "salient")
        if isinstance(metric_val, str):
            metrics_arr = [metric_val]
        elif isinstance(metric_val, list):
            metrics_arr = metric_val
        else:
            metrics_arr = ["salient"]

        ctx = _run_ctx.get() or {}
        latency_ms = int((datetime.now() - started_at).total_seconds() * 1000)

        tokens_in = int(ctx.get("tokens_in", 0) or 0)
        tokens_out = int(ctx.get("tokens_out", 0) or 0)

        run_summary = {
            "run_id": ctx.get("run_id"),
            "started_at": ctx.get("started_at"),
            "latency_ms": latency_ms,
            "provider": provider,
            "question": req.question,
            "brand": parsed.get("brand"),
            "time_period": parsed.get("time_period"),
            "tavily_searches": int(ctx.get("tavily_searches", 0) or 0),
            "tavily_second_passes": int(ctx.get("tavily_second_passes", 0) or 0),
            "llm_calls": int(ctx.get("llm_calls", 0) or 0),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "tokens_total": tokens_in + tokens_out,
            "validated_counts": {
                "market": len(validated.get("market", []) or []),
                "brand": len(validated.get("brand", []) or []),
                "competitive": len(validated.get("competitive", []) or []),
            },
        }
        RUN_LOG.append(run_summary)
        _emit_run_event(run_summary)

        resp = {
            "question": req.question,
            "brand": parsed.get("brand"),
            "metrics": metrics_arr,
            "direction": parsed.get("direction"),
            "time_period": parsed.get("time_period"),
            "provider_used": provider,
            "hypotheses": hypotheses,
            "validated_hypotheses": validated,
            "summary": summary,
            "run_id": run_id,
            "latency_ms": latency_ms,
            "tavily_searches": run_summary["tavily_searches"],
            "tavily_second_passes": run_summary["tavily_second_passes"],
            "llm_calls": run_summary["llm_calls"],
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "tokens_total": tokens_in + tokens_out,
        }
        yield sse("final", resp)

        # best-effort clear run context
        _run_ctx.reset(token)

    return StreamingResponse(event_gen(), media_type="text/event-stream")

def parse_question(question: str, provider: Optional[str] = None) -> Dict:
    """Extract brand, metric, direction from question using LLM"""
    
    prompt = f"""Parse this brand research question and extract:
    - brand: The brand being discussed (lowercase)
    - metric: The metric mentioned (e.g., "salience", "awareness", "consideration")
    - direction: "increase", "decrease", or "change"
    - time_period: Any time period mentioned (e.g., "Q3 2025")
    
    Question: {question}
    
    Return ONLY valid JSON with these exact keys."""
    
    try:
        content = llm_generate(prompt, provider=provider, max_tokens=500)
        # Extract JSON from response
        json_match = re.search(r'\{.*?\}', content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception as e:
        print(f"Parse question error: {e}")
        pass
    
    return {"brand": "unknown", "metric": "salient", "direction": "change", "time_period": None}

def extract_json(text: str) -> Dict:
    """Robust JSON extraction from Claude response"""
    # Try to find JSON in code blocks first
    code_match = re.search(r'```(?:json)?\s*\n?(\{.*?\})\n?\s*```', text, re.DOTALL)
    if code_match:
        try:
            return json.loads(code_match.group(1))
        except:
            pass
    
    # Try to find JSON with balanced braces
    try:
        # Find the first { and match braces
        start = text.find('{')
        if start == -1:
            return {}
        
        count = 0
        for i, char in enumerate(text[start:]):
            if char == '{':
                count += 1
            elif char == '}':
                count -= 1
                if count == 0:
                    return json.loads(text[start:start+i+1])
    except:
        pass
    
    return {}

def generate_hypotheses(parsed: Dict, competitors: List[str], provider: Optional[str] = None) -> Dict[str, List[Dict]]:
    """Generate hypotheses for market, brand, and competitive factors"""
    
    brand = parsed["brand"]
    direction = parsed["direction"]
    time_period = parsed.get("time_period", "2025")
    
    hypotheses = {"market": [], "brand": [], "competitive": []}
    
    # Market hypotheses - use static fallback if LLM fails
    market_prompt = f"""Generate 3-4 hypotheses about UK fashion retail MARKET trends 
    that could cause {direction} in brand salience for {brand}.
    
    Time period: {time_period}
    
    Return ONLY a JSON object like:
    {{"hypotheses": [{{"id": "M1", "hypothesis": "description", "search_query": "UK fashion trend Q3 2025"}}]}}"""
    
    try:
        content = llm_generate(market_prompt, provider=provider, max_tokens=1000)
        data = extract_json(content)
        hypotheses["market"] = data.get("hypotheses", [])
    except Exception as e:
        print(f"Market hypothesis error: {e}")
    
    # Fallback market hypotheses
    if not hypotheses["market"]:
        hypotheses["market"] = [
            {"id": "M1", "hypothesis": f"Economic downturn affecting fashion spending in {time_period}", "search_query": f"UK fashion spending economy {time_period}"},
            {"id": "M2", "hypothesis": "Online shopping shift away from physical retail", "search_query": f"UK online fashion shopping growth {time_period}"},
            {"id": "M3", "hypothesis": "Seasonal trends or weather impacting fashion sales", "search_query": f"UK fashion sales weather seasonal {time_period}"}
        ]
    
    # Brand hypotheses
    brand_prompt = f"""Generate 3-4 hypotheses about {brand}'s specific actions or issues 
    that could cause brand salience to {direction}.
    Areas: advertising spend, store activity, marketing campaigns, PR, news coverage.
    
    Time period: {time_period}
    
    Return ONLY a JSON object like:
    {{"hypotheses": [{{"id": "B1", "hypothesis": "description", "search_query": "{brand} store closures 2025"}}]}}"""
    
    try:
        content = llm_generate(brand_prompt, provider=provider, max_tokens=1000)
        data = extract_json(content)
        hypotheses["brand"] = data.get("hypotheses", [])
    except Exception as e:
        print(f"Brand hypothesis error: {e}")
    
    # Fallback brand hypotheses
    if not hypotheses["brand"]:
        hypotheses["brand"] = [
            {"id": "B1", "hypothesis": f"{brand} store closures or reduced presence", "search_query": f"{brand} store closures {time_period}"},
            {"id": "B2", "hypothesis": f"{brand} marketing or advertising spend changes", "search_query": f"{brand} advertising marketing {time_period}"},
            {"id": "B3", "hypothesis": f"News or media coverage about {brand}", "search_query": f"{brand} news media {time_period}"}
        ]
    
    # Competitive hypotheses
    comp_list = ', '.join(competitors[:6]) if competitors else "main competitors"
    comp_prompt = f"""Generate 3-4 hypotheses about competitor actions affecting {brand}'s salience.
    Competitors to consider: {comp_list}
    Time period: {time_period}
    
    Return ONLY a JSON object like:
    {{"hypotheses": [{{"id": "C1", "hypothesis": "competitor action", "search_query": "Zara campaign UK 2025"}}]}}"""
    
    try:
        content = llm_generate(comp_prompt, provider=provider, max_tokens=1000)
        data = extract_json(content)
        hypotheses["competitive"] = data.get("hypotheses", [])
    except Exception as e:
        print(f"Competitive hypothesis error: {e}")
    
    # Fallback competitive hypotheses  
    if not hypotheses["competitive"]:
        comp_fallback = competitors[:4] if competitors else ["Zara", "H&M", "Primark"]
        hypotheses["competitive"] = [
            {"id": "C1", "hypothesis": f"{comp_fallback[0]} launched major marketing campaign", "search_query": f"{comp_fallback[0]} marketing campaign UK {time_period}"},
            {"id": "C2", "hypothesis": f"{comp_fallback[1] if len(comp_fallback) > 1 else comp_fallback[0]} store expansion or new initiatives", "search_query": f"{comp_fallback[1] if len(comp_fallback) > 1 else comp_fallback[0]} stores UK {time_period}"},
            {"id": "C3", "hypothesis": "Competitor news or media dominance", "search_query": f"UK fashion retailers competition {time_period}"}
        ]
    
    return hypotheses

def process_hypotheses_parallel(hypotheses: Dict, parsed: Dict, provider: Optional[str] = None) -> tuple[Dict[str, List[Dict]], Dict[str, int]]:
    """Process each hypothesis: search + validate in parallel.

    Implements a targeted second-pass search (Option A) when the first pass is weak.
    """

    eval_mode = bool(_eval_mode.get() or False)
    ctx = _run_ctx.get() or {}
    search_backend = (ctx.get("search_backend") or "tavily").lower()
    # debug
    print(f"Search backend: {search_backend} (provider={provider})")

    if eval_mode:
        # Cheaper/faster settings for eval runs to avoid burning tokens/time.
        hypotheses = {
            "market": (hypotheses.get("market") or [])[:2],
            "brand": (hypotheses.get("brand") or [])[:2],
            "competitive": (hypotheses.get("competitive") or [])[:2],
        }

    results = {"market": [], "brand": [], "competitive": []}
    errors = []

    tavily_searches_total = 0
    tavily_second_passes_total = 0

    all_tasks = []
    for cat in ["market", "brand", "competitive"]:
        for hyp in hypotheses.get(cat, []):
            all_tasks.append((hyp, cat))

    print(f"Processing {len(all_tasks)} hypotheses...")

    tavily = None
    use_openai_search = (provider == "openai" and search_backend == "openai")
    if not use_openai_search:
        tavily = get_tavily_client()

    def refine_query(original: str) -> str:
        # Cheap, deterministic refinement (no extra LLM calls)
        brand = parsed.get("brand") or ""
        tp = parsed.get("time_period") or ""
        region = "UK" if "uk" not in original.lower() else ""
        return " ".join([original, brand, tp, region, "retail"]).strip()

    def process_one(hyp, cat):
        query = hyp.get("search_query", hyp.get("hypothesis", ""))
        if not query:
            return {"category": cat, "_tavily_searches": 0, "_tavily_second_passes": 0}

        local_searches = 0
        local_second = 0

        try:
            # Pass 1
            print(f"Searching: {query[:50]}...")
            if use_openai_search:
                try:
                    r1 = openai_web_search(query)
                except Exception as e:
                    print(f"OpenAI web_search error for '{query[:30]}...': {e}")
                    r1 = []
            else:
                sr1 = tavily.search(
                    query=query,
                    search_depth="basic",
                    max_results=2 if eval_mode else 3,
                    include_raw_content=False if eval_mode else True,
                )
                r1 = (sr1 or {}).get("results", []) or []
            print(f"Found {len(r1)} results for: {query[:30]}...")

            validation = {"validated": False, "evidence": ""}
            if r1:
                validation = validate_hypothesis(hyp, r1, provider=provider)
                print(f"Validation: {validation.get('validated')} - {validation.get('evidence', '')[:50]}...")

            # Option A: targeted second-pass when weak
            second_pass_used = False
            if (not eval_mode) and (not use_openai_search) and ((not r1) or (len(r1) < 2) or (not validation.get("validated"))):
                q2 = refine_query(query)
                if q2 and q2 != query:
                    second_pass_used = True
                    local_searches += 1
                    local_second += 1
                    print(f"2nd-pass search: {q2[:60]}...")
                    sr2 = tavily.search(
                        query=q2,
                        search_depth="basic",
                        max_results=3,
                        include_raw_content=True,
                    )
                    r2 = sr2.get("results", []) or []
                    combined = (r1 + r2)[:4]
                    if combined:
                        validation2 = validate_hypothesis(hyp, combined, provider=provider)
                        if validation2.get("validated"):
                            validation = validation2
                            r1 = combined

            if r1 and validation.get("validated"):
                return {
                    "category": cat,
                    "_tavily_searches": local_searches,
                    "_tavily_second_passes": local_second,
                    "item": {
                        "status": "VALIDATED",
                        "hypothesis": hyp.get("hypothesis"),
                        "evidence": validation.get("evidence"),
                        "source": r1[0].get("url"),
                        "source_title": r1[0].get("title"),
                        "second_pass_used": second_pass_used,
                    },
                }

            return {"category": cat, "_tavily_searches": local_searches, "_tavily_second_passes": local_second}

        except Exception as e:
            error_msg = f"Tavily error for '{query[:30]}...': {str(e)}"
            print(error_msg)
            errors.append(error_msg)
            return {"category": cat, "_tavily_searches": local_searches, "_tavily_second_passes": local_second, "error": str(e)}
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_task = {executor.submit(process_one, hyp, cat): (hyp, cat) for hyp, cat in all_tasks}
        
        for future in as_completed(future_to_task):
            hyp, cat = future_to_task[future]
            try:
                result = future.result() or {}

                tavily_searches_total_nonlocal = int(result.get("_tavily_searches", 0) or 0)
                tavily_second_passes_total_nonlocal = int(result.get("_tavily_second_passes", 0) or 0)
                nonlocal_err = result.get("error")

                # aggregate counts in main thread (contextvars don't propagate to threads)
                tavily_searches_total += tavily_searches_total_nonlocal
                tavily_second_passes_total += tavily_second_passes_total_nonlocal

                if result.get("item") and not nonlocal_err:
                    results[result.get("category", cat)].append(result["item"])
            except Exception as e:
                print(f"Thread error: {e}")
    
    print(f"Results: market={len(results['market'])}, brand={len(results['brand'])}, competitive={len(results['competitive'])}")
    if errors:
        print(f"Errors encountered: {len(errors)}")
    
    meta = {
        "tavily_searches": tavily_searches_total,
        "tavily_second_passes": tavily_second_passes_total,
    }
    return results, meta

def validate_hypothesis(hypothesis: Dict, search_results: List[Dict], provider: Optional[str] = None) -> Dict:
    """Use LLM to validate if search results support the hypothesis"""
    
    search_text = "\n\n".join([
        f"Title: {r.get('title', '')}\nContent: {r.get('raw_content', r.get('content', ''))[:500]}"
        for r in search_results[:2]
    ])
    
    prompt = f"""Hypothesis: {hypothesis.get('hypothesis')}

Search Results:
{search_text}

Does this search result contain direct evidence supporting the hypothesis?
Return JSON: {{"validated": true/false, "evidence": "SHORT factual summary (20 words max) with key numbers/dates"}}"""
    
    try:
        content = llm_generate(prompt, provider=provider, max_tokens=500)
        json_match = re.search(r'\{.*?\}', content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception as e:
        print(f"Validate hypothesis error: {e}")
        pass
    
    return {"validated": False, "evidence": ""}

def build_summary(validated: Dict) -> Dict[str, List[Dict]]:
    """Format validated findings into summary structure"""
    
    summary = {"macro_drivers": [], "brand_drivers": [], "competitive_drivers": []}
    
    for cat, output_key in [("market", "macro_drivers"), ("brand", "brand_drivers"), ("competitive", "competitive_drivers")]:
        for item in validated.get(cat, []):
            if item.get("status") == "VALIDATED":
                summary[output_key].append({
                    "driver": item.get("evidence", item.get("hypothesis", "")),
                    "hypothesis": item.get("hypothesis", ""),
                    "source_urls": [item.get("source")] if item.get("source") else [],
                    "source_title": item.get("source_title", ""),
                    "confidence": "medium",
                    "status": item.get("status")
                })
    
    return summary

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
