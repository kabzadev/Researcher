"""
Researcher API - Hypothesis-driven brand metric analysis
Supports both Anthropic Claude and OpenAI
Uses OpenAI Responses API web search for evidence gathering
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
    from opentelemetry import trace as otel_trace
    from azure.monitor.query import LogsQueryClient
    from azure.identity import DefaultAzureCredential
except Exception:
    configure_azure_monitor = None
    FastAPIInstrumentor = None
    RequestsInstrumentor = None
    LogsQueryClient = None
    DefaultAzureCredential = None
    LoggingInstrumentor = None
    otel_trace = None
from pydantic import BaseModel, Field
import anthropic
import openai
from openai import OpenAI, AzureOpenAI

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

# OpenTelemetry tracer for custom pipeline spans
_tracer = otel_trace.get_tracer("researcher.pipeline") if otel_trace else None

def _start_span(name: str, attributes: dict = None):
    """Start an OpenTelemetry span if tracing is available."""
    if _tracer:
        span = _tracer.start_span(name, attributes=attributes or {})
        return span
    return None

def _end_span(span, attributes: dict = None):
    """End a span, optionally adding final attributes."""
    if span:
        if attributes:
            for k, v in attributes.items():
                span.set_attribute(k, v)
        span.end()

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
        "https://delightful-glacier-01802140f.4.azurestaticapps.net",
        "http://localhost:5173",  # Local dev
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    max_age=3600,
)

# ─────────────────────────────────────────────────────────────────────────────
# TRUSTED SOURCES CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_TRUSTED_SOURCES = [
    # Top tier 'Trusted' sources — news & wire services
    {"domain": "reuters.com", "name": "Reuters", "trust_score": 10, "tier": "trusted"},
    {"domain": "bloomberg.com", "name": "Bloomberg", "trust_score": 10, "tier": "trusted"},
    {"domain": "ft.com", "name": "Financial Times", "trust_score": 10, "tier": "trusted"},
    {"domain": "wsj.com", "name": "The Wall Street Journal", "trust_score": 10, "tier": "trusted"},
    # Advertising & marketing trade press
    {"domain": "adweek.com", "name": "Adweek", "trust_score": 9, "tier": "trusted"},
    {"domain": "adage.com", "name": "Ad Age", "trust_score": 9, "tier": "trusted"},
    {"domain": "thedrum.com", "name": "The Drum", "trust_score": 9, "tier": "trusted"},
    {"domain": "campaignlive.co.uk", "name": "Campaign", "trust_score": 9, "tier": "trusted"},
    {"domain": "campaignlive.com", "name": "Campaign", "trust_score": 9, "tier": "trusted"},
    {"domain": "marketingweek.com", "name": "Marketing Week", "trust_score": 9, "tier": "trusted"},
    # Research & intelligence
    {"domain": "kantar.com", "name": "Kantar", "trust_score": 10, "tier": "trusted"},
    {"domain": "mckinsey.com", "name": "McKinsey", "trust_score": 9, "tier": "trusted"},
    {"domain": "mintel.com", "name": "Mintel", "trust_score": 9, "tier": "trusted"},
    {"domain": "euromonitor.com", "name": "Euromonitor", "trust_score": 9, "tier": "trusted"},
    # Reputable business news (secondary tier)
    {"domain": "cnbc.com", "name": "CNBC", "trust_score": 8, "tier": "reputable"},
    {"domain": "bbc.com", "name": "BBC", "trust_score": 8, "tier": "reputable"},
    {"domain": "bbc.co.uk", "name": "BBC", "trust_score": 8, "tier": "reputable"},
    {"domain": "theguardian.com", "name": "The Guardian", "trust_score": 8, "tier": "reputable"},
    {"domain": "nytimes.com", "name": "New York Times", "trust_score": 8, "tier": "reputable"},
    {"domain": "forbes.com", "name": "Forbes", "trust_score": 7, "tier": "reputable"},
    {"domain": "businessinsider.com", "name": "Business Insider", "trust_score": 7, "tier": "reputable"},
    {"domain": "marketingdive.com", "name": "Marketing Dive", "trust_score": 8, "tier": "reputable"},
    {"domain": "wwd.com", "name": "WWD", "trust_score": 8, "tier": "reputable"},
    {"domain": "yahoo.com", "name": "Yahoo Finance", "trust_score": 7, "tier": "reputable"},
]

# Social media domains — must be EXCLUDED from results (POC requirement)
SOCIAL_MEDIA_DOMAINS = [
    "twitter.com", "x.com",
    "tiktok.com",
    "instagram.com",
    "facebook.com", "fb.com",
    "reddit.com",
    "threads.net",
    "linkedin.com",
    "pinterest.com",
    "snapchat.com",
    "youtube.com",
    "youtu.be",
]

# Mutable server-side source config (overridable via /sources PUT)
_trusted_sources = list(DEFAULT_TRUSTED_SOURCES)


def _get_domain(url: str) -> str:
    """Extract root domain from URL (e.g. 'https://www.reuters.com/article/...' -> 'reuters.com')."""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ""
        if host.startswith("www."):
            host = host[4:]
        return host.lower()
    except Exception:
        return ""


def _is_social_media(url: str) -> bool:
    """Check if URL is from a social media platform."""
    domain = _get_domain(url)
    return any(domain == sm or domain.endswith("." + sm) for sm in SOCIAL_MEDIA_DOMAINS)


def _score_source(url: str, trusted_sources: List[Dict] = None) -> Dict:
    """Score a source URL against the trusted sources list.
    Returns {trust_score, tier, source_name, is_trusted}
    """
    sources = trusted_sources or _trusted_sources
    domain = _get_domain(url)
    for src in sources:
        src_domain = src["domain"].lower()
        if domain == src_domain or domain.endswith("." + src_domain):
            return {
                "trust_score": src.get("trust_score", 5),
                "tier": src.get("tier", "unknown"),
                "source_name": src.get("name", domain),
                "is_trusted": True,
            }
    return {
        "trust_score": 3,
        "tier": "unverified",
        "source_name": domain,
        "is_trusted": False,
    }


@app.get("/sources")
async def get_sources(request: Request):
    """Return the current trusted sources list and social media blocklist."""
    return {
        "trusted_sources": _trusted_sources,
        "social_media_blocked": SOCIAL_MEDIA_DOMAINS,
        "total_trusted": len(_trusted_sources),
    }


@app.put("/sources")
async def update_sources(request: Request):
    """Update the trusted sources list. Body: {trusted_sources: [...]}"""
    global _trusted_sources
    body = await request.json()
    new_sources = body.get("trusted_sources")
    if new_sources is None:
        raise HTTPException(status_code=400, detail="Missing 'trusted_sources' in body")
    if not isinstance(new_sources, list):
        raise HTTPException(status_code=400, detail="'trusted_sources' must be a list")
    # Validate each source has required fields
    for i, src in enumerate(new_sources):
        if not isinstance(src, dict) or "domain" not in src:
            raise HTTPException(status_code=400, detail=f"Source at index {i} missing 'domain' field")
        src.setdefault("name", src["domain"])
        src.setdefault("trust_score", 5)
        src.setdefault("tier", "custom")
    _trusted_sources = new_sources
    return {"status": "updated", "total_trusted": len(_trusted_sources)}


@app.post("/sources/reset")
async def reset_sources(request: Request):
    """Reset trusted sources to defaults."""
    global _trusted_sources
    _trusted_sources = list(DEFAULT_TRUSTED_SOURCES)
    return {"status": "reset", "total_trusted": len(_trusted_sources)}


# ── SERVER-SIDE CONFIG ──────────────────────────────────────────────────────

_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")

DEFAULT_CONFIG = {
    "systemPrompt": (
        "You are a research analyst specialising in brand tracking and consumer sentiment analysis.\n\n"
        "Your role:\n"
        "- Analyse why brand metrics (especially Salience / mental availability) change over time.\n"
        "- Generate hypotheses about market, brand-specific, and competitive factors.\n"
        "- Validate hypotheses with web evidence and provide cited sources.\n\n"
        "Guidelines:\n"
        "- Be specific: reference real events, campaigns, product launches, market shifts.\n"
        "- Be evidence-based: only report findings backed by credible web sources.\n"
        "- Be concise: use bullet points and structured output.\n"
        "- Tailor your analysis to the brand's specific industry and market context.\n"
        "- Always include the time period in search queries to get relevant results."
    ),
    "hypothesisPrompt": (
        "When generating hypotheses, follow these rules:\n\n"
        "INDUSTRY CONTEXT:\n"
        "- First determine the brand's industry (e.g. automotive, fashion, technology, FMCG).\n"
        "- ALL hypotheses must be relevant to the brand's actual industry.\n"
        "- Do NOT include trends, competitors, or events from unrelated industries.\n\n"
        "MARKET HYPOTHESES (macro trends):\n"
        "- Economic conditions: consumer spending, inflation, interest rates, currency shifts.\n"
        "- Industry-specific disruptions: regulation, technology shifts, supply chain events.\n"
        "- Consumer behaviour changes: purchasing patterns, demographics, sentiment.\n"
        "- Political, trade, or environmental factors affecting the brand's sector.\n\n"
        "BRAND HYPOTHESES (brand's own actions):\n"
        "- Each must reference a SPECIFIC action, person, product, campaign, or event.\n"
        "- Include: product launches/recalls, leadership changes, PR events, controversies.\n"
        "- Include: store/facility openings or closures, pricing changes, strategy shifts.\n"
        "- Avoid generic statements like 'brand improved marketing' — name the campaign.\n\n"
        "COMPETITIVE HYPOTHESES:\n"
        "- Each must name a SPECIFIC competitor from the brand's actual industry.\n"
        "- Competitors must operate in the SAME market — never cross-industry.\n"
        "- Include specific actions: campaigns, product launches, pricing moves, expansions.\n"
        "- Each hypothesis should focus on a DIFFERENT competitor.\n\n"
        "SEARCH QUERIES:\n"
        "- search_query: specific and targeted (include brand/competitor name + time period).\n"
        "- search_query_broad: broader fallback (include brand/competitor name + time period).\n\n"
        "QUALITY CHECK:\n"
        "- Before finalising, review each hypothesis for relevance to the brand and its industry.\n"
        "- Remove anything that a domain expert would consider irrelevant or nonsensical."
    ),
    "maxHypothesesPerCategory": 4,
    "minVerifiedSourcePct": 25,
}

def _load_config() -> dict:
    """Load config from disk or return defaults."""
    try:
        if os.path.exists(_CONFIG_FILE):
            with open(_CONFIG_FILE, "r") as f:
                stored = json.load(f)
            # Merge with defaults so new keys are always present
            merged = {**DEFAULT_CONFIG, **stored}
            return merged
    except Exception as e:
        print(f"Config load error: {e}")
    return dict(DEFAULT_CONFIG)

def _save_config(cfg: dict):
    """Persist config to disk."""
    try:
        with open(_CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Config save error: {e}")

# In-memory config, loaded at startup
_app_config: dict = _load_config()


@app.get("/config")
async def get_config(request: Request):
    """Return server-side app config."""
    return _app_config


@app.put("/config")
async def update_config(request: Request):
    """Update server-side app config. Body: JSON with any config keys."""
    global _app_config
    body = await request.json()
    _app_config.update(body)
    _save_config(_app_config)
    return {"status": "updated", "config": _app_config}


@app.post("/config/reset")
async def reset_config(request: Request):
    """Reset config to defaults."""
    global _app_config
    _app_config = dict(DEFAULT_CONFIG)
    _save_config(_app_config)
    return {"status": "reset", "config": _app_config}


# Initialize clients
anthropic_client = None
openai_client = None


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
        azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        if azure_endpoint:
            # Azure OpenAI: key-based auth is policy-blocked; use Managed Identity
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            credential = DefaultAzureCredential()
            token_provider = get_bearer_token_provider(
                credential, "https://cognitiveservices.azure.com/.default"
            )
            api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview")
            openai_client = AzureOpenAI(
                azure_ad_token_provider=token_provider,
                azure_endpoint=azure_endpoint,
                api_version=api_version,
            )
        else:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured")
            openai_client = OpenAI(api_key=api_key)
    return openai_client

# Flag indicating whether we're running against Azure OpenAI
_is_azure = bool(os.getenv("AZURE_OPENAI_ENDPOINT"))




def openai_web_search(query: str, *, user_location: Optional[dict] = None, max_sources: int = 6, model_override: Optional[str] = None, trusted_sources: Optional[List[Dict]] = None) -> List[Dict[str, Any]]:
    """Use OpenAI Responses API web_search tool to retrieve web sources.

    Returns a list of dicts compatible with our existing pipeline:
      {"title": str, "url": str, "content": str, "raw_content": str}

    Includes retry with exponential backoff for 429 rate-limit errors.
    """

    client = get_openai_client()
    search_start = time.time()

    # Azure OpenAI requires 'web_search_preview'; standard OpenAI uses 'web_search'
    search_tool_type = "web_search_preview" if _is_azure else "web_search"
    tool_config: Dict[str, Any] = {"type": search_tool_type, "search_context_size": "high"}
    if user_location:
        tool_config["user_location"] = user_location
    tools: List[Dict[str, Any]] = [tool_config]

    search_model = model_override or os.getenv("OPENAI_SEARCH_MODEL", OPENAI_MODEL)

    # Retry with exponential backoff for 429 rate-limit errors
    max_retries = 3
    resp = None
    # Some models (e.g. gpt-5-mini) don't support temperature
    use_temperature = "gpt-5" not in search_model
    for attempt in range(max_retries + 1):
        try:
            create_kwargs = dict(
                model=search_model,
                tools=tools,
                include=["web_search_call.action.sources"],
                input=query,
            )
            if use_temperature:
                create_kwargs["temperature"] = 0
            resp = client.responses.create(**create_kwargs)
            break  # Success
        except Exception as e:
            if "temperature" in str(e).lower() and use_temperature:
                # Model doesn't support temperature, retry without it
                use_temperature = False
                continue
            if "429" in str(e) and attempt < max_retries:
                wait_time = 2 ** (attempt + 1)  # 2s, 4s, 8s
                print(f"Rate limited (429) on attempt {attempt+1}, retrying in {wait_time}s: {query[:40]}...")
                time.sleep(wait_time)
                continue
            raise  # Re-raise non-429 errors or final attempt

    if resp is None:
        return []

    d = resp.model_dump() if hasattr(resp, "model_dump") else {}

    sources: List[Dict[str, Any]] = []
    message_text = ""

    # First pass: collect source URLs from action.sources (standard OpenAI)
    # and url_citation annotations (Azure OpenAI), plus message text
    for item in (d.get("output") or []):
        t = item.get("type")
        if t == "web_search_call":
            action = item.get("action") or {}
            for s in (action.get("sources") or []):
                url = s.get("url") or ""
                if url:
                    sources.append({
                        "title": s.get("title") or "",
                        "url": url,
                        "content": "",
                        "raw_content": "",
                    })
        elif t == "message":
            for c in (item.get("content") or []):
                if c.get("text"):
                    message_text = c["text"]
                # Azure OpenAI: citations are in annotations with type 'url_citation'
                for annot in (c.get("annotations") or []):
                    if annot.get("type") == "url_citation":
                        url = annot.get("url") or ""
                        if url and not any(s["url"] == url for s in sources):
                            sources.append({
                                "title": annot.get("title") or "",
                                "url": url,
                                "content": "",
                                "raw_content": "",
                            })

    search_elapsed_ms = int((time.time() - search_start) * 1000)

    # Return the LLM's analysis text as a synthetic source, plus individual sources
    if message_text:
        # ── Source filtering & scoring ──
        # 1. Remove social media sources
        sources = [s for s in sources if not _is_social_media(s.get("url", ""))]
        # 2. Score remaining sources
        for s in sources:
            score_info = _score_source(s.get("url", ""), trusted_sources)
            s["trust_score"] = score_info["trust_score"]
            s["tier"] = score_info["tier"]
            s["source_name"] = score_info["source_name"]
            s["is_trusted"] = score_info["is_trusted"]
        # 3. Sort by trust score descending so trusted sources appear first
        sources.sort(key=lambda s: s.get("trust_score", 0), reverse=True)

        filtered_count = len(sources)
        result = [{
            "title": "Web Search Analysis",
            "url": sources[0]["url"] if sources else "",
            "content": message_text[:6000],
            "raw_content": message_text[:6000],
            "trust_score": sources[0].get("trust_score", 3) if sources else 3,
            "tier": sources[0].get("tier", "unverified") if sources else "unverified",
            "source_name": sources[0].get("source_name", "") if sources else "",
            "is_trusted": sources[0].get("is_trusted", False) if sources else False,
        }]
        # Also include individual citation sources so the pipeline has URLs
        for s in sources[:max_sources]:
            if s["url"] != result[0]["url"]:
                result.append(s)
        telemetry_logger.info(
            "web_search_complete query=%s duration_ms=%d sources=%d filtered=%d is_azure=%s",
            query[:60], search_elapsed_ms, len(sources), filtered_count, _is_azure,
        )
        span = _start_span("openai_web_search", {
            "search.query": query[:100], "search.duration_ms": search_elapsed_ms,
            "search.source_count": len(sources), "search.is_azure": _is_azure,
        })
        _end_span(span)
        return result

    # No message text — filter and score raw sources
    sources = [s for s in sources if not _is_social_media(s.get("url", ""))]
    for s in sources:
        score_info = _score_source(s.get("url", ""), trusted_sources)
        s.update(score_info)
    sources.sort(key=lambda s: s.get("trust_score", 0), reverse=True)
    telemetry_logger.info(
        "web_search_complete query=%s duration_ms=%d sources=%d is_azure=%s (no_message)",
        query[:60], search_elapsed_ms, len(sources), _is_azure,
    )
    return sources[:max_sources]


@app.get("/debug/web-search")
async def debug_web_search(request: Request, q: str = "new look fashion UK 2025", raw: bool = False):
    """Debug endpoint to inspect raw OpenAI web_search response structure."""
    try:
        client = get_openai_client()
        resp = client.responses.create(
            model=os.getenv("OPENAI_SEARCH_MODEL", OPENAI_MODEL),
            tools=[{"type": "web_search_preview" if _is_azure else "web_search"}],
            tool_choice="auto",
            include=["web_search_call.action.sources"],
            input=q,
        )
        d = resp.model_dump() if hasattr(resp, "model_dump") else {}
        if raw:
            return d
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
                    # Check for annotations (Azure puts url_citation here)
                    annots = c.get("annotations") or []
                    if annots:
                        entry["annotations_count"] = len(annots)
                        entry["annotation_0"] = annots[0] if annots else None
            summary.append(entry)
        return {"output_count": len(d.get("output", [])), "items": summary, "model": d.get("model"), "usage": d.get("usage")}
    except Exception as e:
        return {"error": str(e)}



# LLM Configuration
DEFAULT_PROVIDER = os.getenv("DEFAULT_LLM_PROVIDER", "anthropic")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Models
class ResearchRequest(BaseModel):
    question: str
    provider: Optional[str] = Field(default=None, description="LLM provider: 'anthropic' or 'openai'. Uses DEFAULT_LLM_PROVIDER env var if not specified.")
    # search_backend kept for backward compat but always uses OpenAI web search
    search_backend: Optional[str] = Field(default=None, description="Deprecated. OpenAI web search is always used.")
    system_prompt: Optional[str] = Field(default=None, description="Optional system prompt prepended to all LLM calls for this request.")
    max_hypotheses_per_category: Optional[int] = Field(default=None, ge=1, le=10, description="Max hypotheses per category (market/brand/competitive). Default: 4.")
    model: Optional[str] = Field(default=None, description="Azure deployment name to use for web search (e.g. 'gpt-4-1-nano', 'gpt-4-1-mini', 'gpt-4o'). Uses OPENAI_SEARCH_MODEL env var if not specified.")
    trusted_sources: Optional[List[Dict[str, Any]]] = Field(default=None, description="Optional custom trusted sources list. Each item: {domain, name, trust_score, tier}. Uses server default if not specified.")

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
    web_searches: Optional[int] = None
    web_search_retries: Optional[int] = None
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

# Fallback for streaming generators where ContextVar doesn't propagate
# across yield boundaries in Starlette's threadpool.
_fallback_metrics: Optional[dict] = None


def _run_metric_incr(key: str, amount: int = 1):
    ctx = _run_ctx.get()
    if not ctx:
        ctx = _fallback_metrics
    if not ctx:
        return
    ctx[key] = int(ctx.get(key, 0) or 0) + amount


def _run_metric_set(key: str, value: Any):
    ctx = _run_ctx.get()
    if not ctx:
        ctx = _fallback_metrics
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
def llm_generate(prompt: str, provider: Optional[str] = None, max_tokens: int = 1000, system_prompt: Optional[str] = None) -> str:
    """Generate text using the specified LLM provider.

    Also records per-call telemetry into the current run context (if present).
    """

    chosen_provider = provider or DEFAULT_PROVIDER
    started = time.time()

    if chosen_provider == "anthropic":
        client = get_anthropic_client()
        kwargs = dict(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        if system_prompt:
            kwargs["system"] = system_prompt
        response = client.messages.create(**kwargs)
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
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            max_tokens=max_tokens,
            temperature=0,
            messages=messages,
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


@app.get("/models")
def list_models():
    """Return available Azure OpenAI model deployments."""
    # These are the deployments we've configured in Azure
    DEPLOYED_MODELS = [
        {"deployment": "gpt-4o", "model": "gpt-4o", "version": "2024-08-06", "description": "GPT-4o (Aug 2024) - Original deployment"},
        {"deployment": "gpt-4o-latest", "model": "gpt-4o", "version": "2024-11-20", "description": "GPT-4o (Nov 2024) - Improved reasoning"},
        {"deployment": "gpt-4-1", "model": "gpt-4.1", "version": "2025-04-14", "description": "GPT-4.1 - Latest GPT-4 series"},
        {"deployment": "gpt-4-1-mini", "model": "gpt-4.1-mini", "version": "2025-04-14", "description": "GPT-4.1 Mini - Fast & capable"},
        {"deployment": "gpt-4-1-nano", "model": "gpt-4.1-nano", "version": "2025-04-14", "description": "GPT-4.1 Nano - Ultra-fast, best validation rate ⭐"},
        {"deployment": "gpt-5-mini", "model": "gpt-5-mini", "version": "2025-08-07", "description": "GPT-5 Mini - Next-gen compact"},
        {"deployment": "gpt-5-nano", "model": "gpt-5-nano", "version": "2025-08-07", "description": "GPT-5 Nano - Next-gen ultra-fast"},
    ]
    current = os.getenv("OPENAI_SEARCH_MODEL", OPENAI_MODEL)
    return {
        "current_default": current,
        "models": DEPLOYED_MODELS,
    }


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
    web_searches=sum(tolong(run.web_searches)),
    web_search_retries=sum(tolong(run.web_search_retries))
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
                    "web_searches": int(r[2] or 0),
                    "web_search_retries": int(r[3] or 0),
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
            "web_searches": 0,
            "web_search_retries": 0,
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
        "web_searches": sum(int(i.get("web_searches", 0) or 0) for i in items),
        "web_search_retries": sum(int(i.get("web_search_retries", 0) or 0) for i in items),
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
                "web_searches": resp.get("web_searches"),
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
            "search_backend": "openai",
            "started_at": datetime.now().isoformat(),
            "web_searches": 0,
            "web_search_retries": 0,
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
                    "web_searches": 0,
                    "web_search_retries": 0,
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
                web_searches=0,
                web_search_retries=0,
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
                "web_searches": 0,
                "web_search_retries": 0,
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
                web_searches=0,
                web_search_retries=0,
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
        hypotheses = generate_hypotheses(parsed, competitors, provider=provider, max_per_category=req.max_hypotheses_per_category or 4, system_prompt=req.system_prompt)
        
        # Step 4: Process hypotheses (search + validate)
        validated, meta = process_hypotheses_parallel(hypotheses, parsed, provider=provider, model_override=req.model)
        _run_metric_set("web_searches", int(meta.get("web_searches", 0) or 0))
        _run_metric_set("web_search_retries", int(meta.get("web_search_retries", 0) or 0))
        
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
            "web_searches": int(meta.get("web_searches", 0) or 0),
            "web_search_retries": int(meta.get("web_search_retries", 0) or 0),
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
            web_searches=int(meta.get("web_searches", 0) or 0),
            web_search_retries=int(meta.get("web_search_retries", 0) or 0),
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
        # Keep a direct reference to the metrics dict so we can read it
        # even if the ContextVar loses propagation across generator yields
        # in Starlette's threadpool.
        run_metrics = {
            "run_id": run_id,
            "provider": provider,
            "question": req.question,
            "started_at": started_at.isoformat(),
            "web_searches": 0,
            "web_search_retries": 0,
            "llm_calls": 0,
            "tokens_in": 0,
            "tokens_out": 0,
        }
        token = _run_ctx.set(run_metrics)
        # Also set module-level fallback for threadpool context loss
        global _fallback_metrics
        _fallback_metrics = run_metrics

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
        step1_start = time.time()
        parsed = parse_question(req.question, provider=provider)
        step1_ms = int((time.time() - step1_start) * 1000)
        telemetry_logger.info("pipeline_step step=parse_question duration_ms=%d brand=%s", step1_ms, parsed.get("brand"))
        span = _start_span("pipeline.parse_question", {"step.duration_ms": step1_ms, "step.brand": parsed.get("brand", "")})
        _end_span(span)
        yield sse("parsed", parsed)

        # Step 2: Get competitors
        competitors = COMPETITOR_DB.get(parsed.get("brand", ""), [])
        yield sse("competitors", {"competitors": competitors})

        # Step 3: Generate hypotheses
        step3_start = time.time()
        hypotheses = generate_hypotheses(parsed, competitors, provider=provider, max_per_category=req.max_hypotheses_per_category or 4, system_prompt=req.system_prompt)
        step3_ms = int((time.time() - step3_start) * 1000)
        total_hyps = sum(len(hypotheses.get(c, []) or []) for c in ["market", "brand", "competitive"])
        telemetry_logger.info("pipeline_step step=generate_hypotheses duration_ms=%d hypothesis_count=%d", step3_ms, total_hyps)
        span = _start_span("pipeline.generate_hypotheses", {"step.duration_ms": step3_ms, "step.hypothesis_count": total_hyps})
        _end_span(span)
        yield sse("hypotheses", hypotheses)

        # Step 4: Process hypotheses in parallel and stream results
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
            hyp_start = time.time()
            query = hyp.get("search_query") or hyp.get("hypothesis") or ""
            query_broad = hyp.get("search_query_broad") or ""
            if not query:
                return {"category": cat, "hypothesis": hyp.get("hypothesis"), "validated": False, "error": "empty_query"}

            # Web search — try specific query first
            _run_metric_incr("web_searches", 1)
            try:
                r1 = openai_web_search(query, model_override=req.model, trusted_sources=req.trusted_sources)
            except Exception as e:
                print(f"Web search error for '{query[:30]}...': {e}")
                r1 = []
            validation = {"validated": False, "evidence": ""}
            if r1:
                validation = validate_hypothesis(hyp, r1, provider=provider)

            # If specific query failed or got no validation, try the broad query
            second_pass_used = False
            second_query = None
            if query_broad and (not r1 or not validation.get("validated")):
                second_pass_used = True
                second_query = query_broad
                _run_metric_incr("web_searches", 1)
                try:
                    r2 = openai_web_search(query_broad, model_override=req.model, trusted_sources=req.trusted_sources)
                except Exception as e:
                    print(f"Broad search error for '{query_broad[:30]}...': {e}")
                    r2 = []
                if r2:
                    validation2 = validate_hypothesis(hyp, r2, provider=provider)
                    if validation2.get("validated"):
                        validation = validation2
                        r1 = r2

            # ── Pass 3: Targeted trusted-source search ──
            # If we validated but the top source is NOT trusted, do one more
            # search steered toward trusted domains via site: operators.
            # This increases the verified-source ratio without replacing the
            # evidence — we only swap in the trusted result if it also validates.
            top_trusted = not r1 or not r1[0].get("is_trusted", False)
            if validation.get("validated") and top_trusted:
                sources_list = req.trusted_sources or _trusted_sources
                # Pick top-5 trusted domains for the site: clause
                top_domains = [s["domain"] for s in sources_list if s.get("tier") == "trusted"][:5]
                if top_domains:
                    site_clause = " OR ".join(f"site:{d}" for d in top_domains)
                    targeted_query = f"{query} ({site_clause})"
                    _run_metric_incr("web_searches", 1)
                    try:
                        r3 = openai_web_search(targeted_query, model_override=req.model, trusted_sources=req.trusted_sources)
                    except Exception as e:
                        print(f"Targeted search error: {e}")
                        r3 = []
                    if r3 and r3[0].get("is_trusted", False):
                        validation3 = validate_hypothesis(hyp, r3, provider=provider)
                        if validation3.get("validated"):
                            validation = validation3
                            r1 = r3

            # Extract source trust metadata
            source_trust = {}
            if r1:
                source_trust = {
                    "trust_score": r1[0].get("trust_score", 3),
                    "tier": r1[0].get("tier", "unverified"),
                    "source_name": r1[0].get("source_name", ""),
                    "is_trusted": r1[0].get("is_trusted", False),
                }

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
                **source_trust,
            }

        step4_start = time.time()
        # Process hypotheses sequentially to avoid 429 rate limits.
        # With search_context_size='high', each search uses significant tokens;
        # parallel execution overwhelms the TPM quota.
        completed = 0
        for hyp, cat in tasks:
            completed += 1
            try:
                item = process_one(hyp, cat)
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
                        "trust_score": item.get("trust_score", 3),
                        "tier": item.get("tier", "unverified"),
                        "source_name": item.get("source_name", ""),
                        "is_trusted": item.get("is_trusted", False),
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
        step4_ms = int((time.time() - step4_start) * 1000)
        validated_count = sum(len(v) for v in validated.values())
        telemetry_logger.info(
            "pipeline_step step=parallel_search duration_ms=%d hypotheses=%d validated=%d workers=5",
            step4_ms, len(tasks), validated_count,
        )
        span = _start_span("pipeline.parallel_search", {
            "step.duration_ms": step4_ms, "step.hypothesis_count": len(tasks),
            "step.validated_count": validated_count, "step.workers": 5,
        })
        _end_span(span)

        # ── Enforce minimum verified-source percentage ──
        min_verified_pct = _app_config.get("minVerifiedSourcePct", 25)
        if min_verified_pct and min_verified_pct > 0:
            all_v = []
            for cat in ["market", "brand", "competitive"]:
                for v in validated.get(cat, []):
                    all_v.append((cat, v))
            total = len(all_v)
            if total > 0:
                trusted = sum(1 for _, v in all_v if v.get("is_trusted", False))
                current_pct = trusted / total * 100
                if current_pct < min_verified_pct:
                    # Sort unverified items by trust_score ascending (drop worst first)
                    unverified = [(cat, v) for cat, v in all_v if not v.get("is_trusted", False)]
                    unverified.sort(key=lambda x: x[1].get("trust_score", 0))
                    # Remove unverified items one at a time until threshold is met or
                    # we'd drop everything unverified
                    items_to_drop = set()
                    remaining_total = total
                    remaining_trusted = trusted
                    for cat, v in unverified:
                        if remaining_total <= 1 or remaining_trusted / remaining_total * 100 >= min_verified_pct:
                            break
                        items_to_drop.add(id(v))
                        remaining_total -= 1
                    if items_to_drop:
                        pre_count = sum(len(vals) for vals in validated.values())
                        for cat in ["market", "brand", "competitive"]:
                            validated[cat] = [v for v in validated.get(cat, []) if id(v) not in items_to_drop]
                        post_count = sum(len(vals) for vals in validated.values())
                        new_trusted = sum(1 for cat in validated for v in validated[cat] if v.get("is_trusted"))
                        new_pct = round(new_trusted / max(post_count, 1) * 100, 1)
                        print(f"[MinVerified] Dropped {pre_count - post_count} unverified findings "
                              f"({current_pct:.0f}% → {new_pct}%) to meet {min_verified_pct}% threshold")
                        yield sse("quality_filter", {
                            "dropped": pre_count - post_count,
                            "before_pct": round(current_pct, 1),
                            "after_pct": new_pct,
                            "threshold": min_verified_pct,
                        })

        # Step 5: Build summary + final response
        step5_start = time.time()
        summary = build_summary(validated)
        step5_ms = int((time.time() - step5_start) * 1000)
        telemetry_logger.info("pipeline_step step=build_summary duration_ms=%d", step5_ms)
        span = _start_span("pipeline.build_summary", {"step.duration_ms": step5_ms})
        _end_span(span)

        metric_val = parsed.get("metric", "salient")
        if isinstance(metric_val, str):
            metrics_arr = [metric_val]
        elif isinstance(metric_val, list):
            metrics_arr = metric_val
        else:
            metrics_arr = ["salient"]

        # Read from run_metrics directly (local closure variable) rather
        # than the ContextVar, which may have lost propagation across yields.
        latency_ms = int((datetime.now() - started_at).total_seconds() * 1000)

        tokens_in = int(run_metrics.get("tokens_in", 0) or 0)
        tokens_out = int(run_metrics.get("tokens_out", 0) or 0)

        run_summary = {
            "run_id": run_metrics.get("run_id"),
            "started_at": run_metrics.get("started_at"),
            "latency_ms": latency_ms,
            "provider": provider,
            "question": req.question,
            "brand": parsed.get("brand"),
            "time_period": parsed.get("time_period"),
            "web_searches": int(run_metrics.get("web_searches", 0) or 0),
            "web_search_retries": int(run_metrics.get("web_search_retries", 0) or 0),
            "llm_calls": int(run_metrics.get("llm_calls", 0) or 0),
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

        # Step 5b: Generate executive summary
        exec_summary = ""
        try:
            all_evidence = []
            for cat in ["market", "brand", "competitive"]:
                for v in validated.get(cat, []):
                    all_evidence.append(f"[{cat}] {v.get('evidence', '')} (Source: {v.get('source_name', 'unknown')})")
            if all_evidence:
                summary_prompt = f"""You are a research analyst. Based on the following validated findings about {parsed.get('brand', 'the brand')}, write a concise executive summary (3-5 sentences). Report ONLY the factual findings from the sources. DO NOT make inferences, draw conclusions about what the findings mean for the brand, or provide recommendations.

Question: {req.question}

Validated Findings:
{chr(10).join(all_evidence)}

Executive Summary:"""
                exec_summary = llm_generate(summary_prompt, provider=provider, max_tokens=300)
                # Strip the "Executive Summary:" prefix the LLM may echo back
                exec_summary = re.sub(r'^\s*Executive\s+Summary\s*[:.]?\s*', '', exec_summary, flags=re.IGNORECASE).strip()
        except Exception as e:
            print(f"Executive summary error: {e}")
            exec_summary = ""

        yield sse("executive_summary", {"summary": exec_summary})

        # Source policy stats
        all_sources = []
        for cat in ["market", "brand", "competitive"]:
            for v in validated.get(cat, []):
                all_sources.append(v)
        trusted_count = sum(1 for s in all_sources if s.get("is_trusted"))
        total_sources = len(all_sources)
        source_policy = {
            "trusted_source_count": trusted_count,
            "total_source_count": total_sources,
            "trusted_ratio": round(trusted_count / max(total_sources, 1) * 100, 1),
            "social_media_filtered": True,
        }

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
            "executive_summary": exec_summary,
            "source_policy": source_policy,
            "run_id": run_id,
            "latency_ms": latency_ms,
            "web_searches": run_summary["web_searches"],
            "web_search_retries": run_summary["web_search_retries"],
            "llm_calls": run_summary["llm_calls"],
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "tokens_total": tokens_in + tokens_out,
        }
        yield sse("final", resp)

        # best-effort clear run context
        _run_ctx.reset(token)
        _fallback_metrics = None

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

def generate_hypotheses(parsed: Dict, competitors: List[str], provider: Optional[str] = None, max_per_category: int = 4, system_prompt: Optional[str] = None) -> Dict[str, List[Dict]]:
    """Generate hypotheses for market, brand, and competitive factors.
    
    Industry-agnostic: prompts adapt to the brand rather than
    assuming fashion/retail.
    """
    
    brand = parsed["brand"]
    direction = parsed["direction"]
    time_period = parsed.get("time_period", "2025")
    metric = parsed.get("metric", "salience")
    region = parsed.get("region", "")
    n = max_per_category
    
    # Build a region clause for prompts
    region_clause = f" in {region}" if region else ""
    
    hypotheses = {"market": [], "brand": [], "competitive": []}
    
    # ── Step 0: Determine industry context ──────────────────────────
    # Let the LLM figure out the industry so all subsequent prompts
    # are contextually appropriate.
    industry = ""
    try:
        industry_prompt = f"""What industry does the brand "{brand}" operate in?
Return ONLY a JSON object: {{"industry": "automotive"}}, {{"industry": "fashion retail"}}, etc.
One or two words maximum for the industry value."""
        ind_content = llm_generate(industry_prompt, provider=provider, max_tokens=50)
        ind_data = extract_json(ind_content)
        industry = ind_data.get("industry", "")
    except Exception:
        pass
    
    industry_clause = f" ({industry})" if industry else ""
    
    # ── Market hypotheses ───────────────────────────────────────────
    market_prompt = f"""You are a brand research analyst. Generate exactly {n} specific hypotheses about macro market trends
that could explain why {brand}{industry_clause}'s brand {metric} {direction}d during {time_period}{region_clause}.

Focus on CONCRETE, SEARCHABLE trends relevant to {brand}'s industry:
- Economic conditions (consumer spending, inflation, currency, interest rates)
- Industry-specific shifts (regulatory changes, technology disruption, supply chain)
- Consumer behavior changes (purchasing patterns, preferences, demographics)
- Political, trade, or environmental factors

CRITICAL RULES:
- Every hypothesis MUST be directly relevant to {brand} and its industry{industry_clause}
- Do NOT include hypotheses about unrelated industries or brands
- search_query: specific, targeted query (MUST include "{brand}" and "{time_period}")
- search_query_broad: broader fallback query (MUST include "{brand}" and "{time_period}")

Return ONLY a JSON object:
{{"hypotheses": [
  {{"id": "M1", "hypothesis": "specific trend affecting {brand}", "search_query": "{brand} specific trend {time_period}", "search_query_broad": "{brand} market trends {time_period}"}},
  {{"id": "M2", "hypothesis": "another trend", "search_query": "{brand} specific term {time_period}", "search_query_broad": "{brand} industry trend {time_period}"}}
]}}"""
    
    try:
        content = llm_generate(market_prompt, provider=provider, max_tokens=1000, system_prompt=system_prompt)
        data = extract_json(content)
        hypotheses["market"] = data.get("hypotheses", [])[:n]
    except Exception as e:
        print(f"Market hypothesis error: {e}")
    
    # Fallback market hypotheses
    if not hypotheses["market"]:
        hypotheses["market"] = [
            {"id": "M1", "hypothesis": f"Economic downturn affecting {brand}'s sector in {time_period}", "search_query": f"{brand} economic impact {time_period}", "search_query_broad": f"{brand} market conditions {time_period}"},
            {"id": "M2", "hypothesis": f"Consumer sentiment shift in {brand}'s market", "search_query": f"{brand} consumer sentiment {time_period}", "search_query_broad": f"{brand} market changes {time_period}"},
            {"id": "M3", "hypothesis": f"Regulatory or policy changes affecting {brand}", "search_query": f"{brand} regulations policy {time_period}", "search_query_broad": f"{brand} industry news {time_period}"}
        ][:n]
    
    # ── Brand hypotheses ────────────────────────────────────────────
    brand_prompt = f"""You are a brand research analyst. Generate exactly {n} specific hypotheses about {brand}'s own actions
that could explain why its brand {metric} {direction}d during {time_period}{region_clause}.

Focus on CONCRETE actions by {brand}{industry_clause}:
- Specific advertising campaigns, endorsements, or sponsorships (name them)
- Product launches, recalls, or discontinuations (name specific products)
- Store/facility openings, closures, or expansions (name locations)
- Leadership changes, controversies, PR events (name specifics)
- Pricing, strategy, or business model changes

CRITICAL RULES:
- Each hypothesis MUST be about {brand} specifically, not generic industry trends
- Each hypothesis MUST mention a specific action, person, product, or event
- search_query: specific, targeted (MUST include "{brand}" and "{time_period}")
- search_query_broad: broader fallback (MUST include "{brand}" and "{time_period}")

Return ONLY a JSON object:
{{"hypotheses": [
  {{"id": "B1", "hypothesis": "{brand} did X", "search_query": "{brand} specific action {time_period}", "search_query_broad": "{brand} news {time_period}"}},
  {{"id": "B2", "hypothesis": "{brand} launched Y", "search_query": "{brand} Y launch {time_period}", "search_query_broad": "{brand} product launch {time_period}"}}
]}}"""
    
    try:
        content = llm_generate(brand_prompt, provider=provider, max_tokens=1000, system_prompt=system_prompt)
        data = extract_json(content)
        hypotheses["brand"] = data.get("hypotheses", [])[:n]
    except Exception as e:
        print(f"Brand hypothesis error: {e}")
    
    # Fallback brand hypotheses
    if not hypotheses["brand"]:
        hypotheses["brand"] = [
            {"id": "B1", "hypothesis": f"{brand} had significant business changes", "search_query": f"{brand} business changes {time_period}", "search_query_broad": f"{brand} news {time_period}"},
            {"id": "B2", "hypothesis": f"{brand} launched major campaign or product", "search_query": f"{brand} campaign launch {time_period}", "search_query_broad": f"{brand} marketing {time_period}"},
            {"id": "B3", "hypothesis": f"{brand} faced controversy or PR issues", "search_query": f"{brand} controversy news {time_period}", "search_query_broad": f"{brand} media coverage {time_period}"}
        ][:n]
    
    # ── Competitive hypotheses ──────────────────────────────────────
    # Auto-detect competitors if none provided
    if not competitors:
        try:
            comp_detect_prompt = f"""Name the top 5 direct competitors of {brand}{industry_clause}.
Return ONLY a JSON object: {{"competitors": ["Competitor1", "Competitor2", ...]}}"""
            comp_content = llm_generate(comp_detect_prompt, provider=provider, max_tokens=100)
            comp_data = extract_json(comp_content)
            competitors = comp_data.get("competitors", [])[:6]
        except Exception:
            pass
    
    comp_list = ', '.join(competitors[:6]) if competitors else f"major competitors in {brand}'s industry"
    comp_prompt = f"""You are a brand research analyst. Generate exactly {n} specific hypotheses about how NAMED competitors
affected {brand}'s brand {metric} during {time_period}{region_clause}.

Available competitors: {comp_list}

CRITICAL RULES:
1. Each hypothesis MUST name a SPECIFIC competitor brand from the list above
2. Each hypothesis should focus on a DIFFERENT competitor
3. Competitors MUST be in the SAME industry as {brand}{industry_clause}
4. Include specific actions: campaigns, product launches, pricing moves, expansions, viral moments
5. search_query: specific, targeted (MUST include the competitor name and "{time_period}")
6. search_query_broad: broader fallback (MUST include the competitor name and "{time_period}")
7. Do NOT include competitors from unrelated industries

Return ONLY a JSON object:
{{"hypotheses": [
  {{"id": "C1", "hypothesis": "[Competitor] launched [specific campaign] that drew attention from {brand}", "search_query": "[Competitor] specific campaign {time_period}", "search_query_broad": "[Competitor] marketing news {time_period}"}},
  {{"id": "C2", "hypothesis": "[Competitor] [specific action] increased visibility vs {brand}", "search_query": "[Competitor] specific action {time_period}", "search_query_broad": "[Competitor] brand news {time_period}"}}
]}}"""
    
    try:
        content = llm_generate(comp_prompt, provider=provider, max_tokens=1000, system_prompt=system_prompt)
        data = extract_json(content)
        hypotheses["competitive"] = data.get("hypotheses", [])[:n]
    except Exception as e:
        print(f"Competitive hypothesis error: {e}")
    
    # Fallback competitive hypotheses  
    if not hypotheses["competitive"]:
        if competitors:
            hypotheses["competitive"] = [
                {"id": f"C{i+1}", "hypothesis": f"{comp} gained market share or brand visibility vs {brand}", "search_query": f"{comp} brand marketing {time_period}", "search_query_broad": f"{comp} news {time_period}"}
                for i, comp in enumerate(competitors[:n])
            ]
        else:
            hypotheses["competitive"] = [
                {"id": "C1", "hypothesis": f"A competitor gained visibility over {brand}", "search_query": f"{brand} competitors market share {time_period}", "search_query_broad": f"{brand} competition {time_period}"}
            ]
    
    # ── Relevance filter ────────────────────────────────────────────
    # Final check: remove any hypotheses that are obviously irrelevant
    # to the brand or its industry.
    # SAFEGUARD: never remove ALL hypotheses from any category.
    try:
        all_hyps = []
        for cat in ["market", "brand", "competitive"]:
            for h in hypotheses.get(cat, []):
                all_hyps.append({"category": cat, "id": h.get("id"), "hypothesis": h.get("hypothesis", "")})
        
        if all_hyps:
            filter_prompt = f"""You are a quality-control analyst. Review these hypotheses generated for the brand "{brand}"{industry_clause}.
The research question is: "{parsed.get('question', f'{brand} {metric} {direction} {time_period}')}"

Hypotheses:
{json.dumps(all_hyps, indent=2)}

Identify any hypotheses that are NOT genuinely relevant to {brand} or its industry{industry_clause}.
A hypothesis is IRRELEVANT ONLY if:
- It mentions brands, products, or trends from a COMPLETELY DIFFERENT industry
- It has absolutely no logical connection to {brand}

IMPORTANT: Be conservative. When in doubt, keep the hypothesis.
- Competitor actions from the SAME industry are ALWAYS relevant — do NOT remove them.
- General market/economic trends are usually relevant — do NOT remove them.
- Only remove things that are clearly from a wrong industry (e.g. sneaker news for an auto brand).

Return ONLY a JSON object with the IDs to REMOVE:
{{"remove_ids": ["M3", "C2"]}}
If ALL hypotheses are relevant, return: {{"remove_ids": []}}"""
            
            filter_content = llm_generate(filter_prompt, provider=provider, max_tokens=200)
            filter_data = extract_json(filter_content)
            remove_ids = set(filter_data.get("remove_ids", []))
            
            if remove_ids:
                print(f"Relevance filter removing: {remove_ids}")
                for cat in ["market", "brand", "competitive"]:
                    original = hypotheses[cat]
                    filtered = [h for h in original if h.get("id") not in remove_ids]
                    # SAFEGUARD: never empty a category entirely
                    if not filtered and original:
                        print(f"  ⚠ Relevance filter would empty '{cat}' — keeping first hypothesis")
                        filtered = [original[0]]
                    hypotheses[cat] = filtered
    except Exception as e:
        print(f"Relevance filter error (non-fatal): {e}")
    
    return hypotheses

def process_hypotheses_parallel(hypotheses: Dict, parsed: Dict, provider: Optional[str] = None, model_override: Optional[str] = None) -> tuple[Dict[str, List[Dict]], Dict[str, int]]:
    """Process each hypothesis: search + validate sequentially.

    Uses dual-query strategy: specific first, broad fallback.
    """

    eval_mode = bool(_eval_mode.get() or False)

    if eval_mode:
        # Cheaper/faster settings for eval runs to avoid burning tokens/time.
        hypotheses = {
            "market": (hypotheses.get("market") or [])[:2],
            "brand": (hypotheses.get("brand") or [])[:2],
            "competitive": (hypotheses.get("competitive") or [])[:2],
        }

    results = {"market": [], "brand": [], "competitive": []}
    errors = []

    web_searches_total = 0
    web_search_retries_total = 0

    all_tasks = []
    for cat in ["market", "brand", "competitive"]:
        for hyp in hypotheses.get(cat, []):
            all_tasks.append((hyp, cat))

    print(f"Processing {len(all_tasks)} hypotheses...")

    def refine_query(original: str) -> str:
        brand = parsed.get("brand") or ""
        tp = parsed.get("time_period") or ""
        region = "UK" if "uk" not in original.lower() else ""
        return " ".join([original, brand, tp, region, "retail"]).strip()

    def process_one(hyp, cat):
        query = hyp.get("search_query", hyp.get("hypothesis", ""))
        query_broad = hyp.get("search_query_broad", "")
        if not query:
            return {"category": cat, "_web_searches": 0, "_web_search_retries": 0}

        local_searches = 0

        try:
            # Web search — try specific query first
            print(f"Searching: {query[:50]}...")
            local_searches += 1
            try:
                r1 = openai_web_search(query, model_override=model_override)
            except Exception as e:
                print(f"Web search error for '{query[:30]}...': {e}")
                r1 = []
            print(f"Found {len(r1)} results for: {query[:30]}...")

            validation = {"validated": False, "evidence": ""}
            if r1:
                validation = validate_hypothesis(hyp, r1, provider=provider)
                print(f"Validation: {validation.get('validated')} - {validation.get('evidence', '')[:50]}...")

            # If specific query failed or got no validation, try the broad query
            if query_broad and (not r1 or not validation.get("validated")):
                print(f"Trying broad query: {query_broad[:50]}...")
                local_searches += 1
                try:
                    r2 = openai_web_search(query_broad, model_override=model_override)
                except Exception as e:
                    print(f"Broad search error for '{query_broad[:30]}...': {e}")
                    r2 = []
                if r2:
                    validation2 = validate_hypothesis(hyp, r2, provider=provider)
                    if validation2.get("validated"):
                        validation = validation2
                        r1 = r2
                        print(f"Broad validated: {validation2.get('evidence', '')[:50]}...")

            if r1 and validation.get("validated"):
                return {
                    "category": cat,
                    "_web_searches": local_searches,
                    "_web_search_retries": 0,
                    "item": {
                        "status": "VALIDATED",
                        "hypothesis": hyp.get("hypothesis"),
                        "evidence": validation.get("evidence"),
                        "source": r1[0].get("url"),
                        "source_title": r1[0].get("title"),
                        "second_pass_used": bool(query_broad and local_searches > 1),
                    },
                }

            return {"category": cat, "_web_searches": local_searches, "_web_search_retries": 0}

        except Exception as e:
            error_msg = f"Search error for '{query[:30]}...': {str(e)}"
            print(error_msg)
            errors.append(error_msg)
            return {"category": cat, "_web_searches": local_searches, "_web_search_retries": 0, "error": str(e)}
    
    # Process sequentially to avoid 429 rate limits with Azure's TPM quota.
    # With search_context_size='high', each search uses significant tokens.
    for hyp, cat in all_tasks:
        try:
            result = process_one(hyp, cat) or {}

            web_searches_total += int(result.get("_web_searches", 0) or 0)
            web_search_retries_total += int(result.get("_web_search_retries", 0) or 0)

            if result.get("item") and not result.get("error"):
                results[result.get("category", cat)].append(result["item"])
        except Exception as e:
            print(f"Processing error: {e}")
    
    print(f"Results: market={len(results['market'])}, brand={len(results['brand'])}, competitive={len(results['competitive'])}")
    if errors:
        print(f"Errors encountered: {len(errors)}")
    
    meta = {
        "web_searches": web_searches_total,
        "web_search_retries": web_search_retries_total,
    }
    return results, meta

def validate_hypothesis(hypothesis: Dict, search_results: List[Dict], provider: Optional[str] = None) -> Dict:
    """Use LLM to validate if search results support the hypothesis"""
    
    # Use generous content window for Azure OpenAI analysis sources
    search_text = "\n\n".join([
        f"Title: {r.get('title', '')}\nContent: {r.get('raw_content', r.get('content', ''))[:2000]}"
        for r in search_results[:3]
    ])
    
    prompt = f"""Hypothesis: {hypothesis.get('hypothesis')}

Search Results:
{search_text}

Does this search result contain relevant factual information that supports or relates to the hypothesis?
Be generous — if the evidence is even partially relevant, validate it.

IMPORTANT RULES:
- DO NOT make inferences or draw conclusions about what the evidence means for the brand or client.
- DO NOT interpret or speculate beyond what the sources explicitly state.
- Only report the factual findings from the search results.
- Your evidence should be a direct summary of what the source says, not an interpretation.

Return JSON: {{"validated": true/false, "evidence": "SHORT factual summary (20 words max) with key numbers/dates from the source"}}"""
    
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
