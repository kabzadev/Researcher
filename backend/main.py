"""
Researcher API - Hypothesis-driven brand metric analysis
Supports both Anthropic Claude and OpenAI
Uses Tavily for web search
"""

import os
import json
import re
from typing import Dict, List, Any, Optional
from datetime import datetime
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

# Observability (Application Insights)
try:
    from azure.monitor.opentelemetry import configure_azure_monitor
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
except Exception:
    configure_azure_monitor = None
    FastAPIInstrumentor = None
    RequestsInstrumentor = None
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
        if FastAPIInstrumentor:
            FastAPIInstrumentor.instrument_app(app)
        print("✓ Application Insights telemetry enabled")
    except Exception as e:
        print(f"⚠ Failed to enable Application Insights telemetry: {e}")

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

# LLM Abstraction Layer
def llm_generate(prompt: str, provider: Optional[str] = None, max_tokens: int = 1000) -> str:
    """Generate text using the specified LLM provider"""
    
    # Determine which provider to use
    chosen_provider = provider or DEFAULT_PROVIDER
    
    if chosen_provider == "anthropic":
        client = get_anthropic_client()
        if not client:
            raise HTTPException(status_code=503, detail="Anthropic API key not configured")
        
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
    
    elif chosen_provider == "openai":
        client = get_openai_client()
        if not client:
            raise HTTPException(status_code=503, detail="OpenAI API key not configured")
        
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content or ""
    
    else:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {chosen_provider}. Use 'anthropic' or 'openai'.")

# Competitor Database
COMPETITOR_DB = {
    "new look": ["primark", "m&s", "asos", "next", "h&m", "shein", "zara"],
    "primark": ["new look", "h&m", "shein"],
    "zara": ["h&m", "shein", "asos"],
}

@app.get("/health")
def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

@app.post("/research")
def research(req: ResearchRequest):
    """Main research endpoint - hypothesis-driven analysis"""
    
    # Determine which provider to use (request param > env var > default)
    provider = req.provider or DEFAULT_PROVIDER
    
    try:
        # Step 1: Parse question
        parsed = parse_question(req.question, provider=provider)
        
        # Step 2: Get competitors
        competitors = COMPETITOR_DB.get(parsed["brand"], [])
        
        # Step 3: Generate hypotheses
        hypotheses = generate_hypotheses(parsed, competitors, provider=provider)
        
        # Step 4: Process hypotheses in parallel (search + validate)
        validated = process_hypotheses_parallel(hypotheses, parsed, provider=provider)
        
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
        
        return ResearchResponse(
            question=req.question,
            brand=parsed.get("brand") or "unknown",
            metrics=metrics_arr,
            direction=parsed.get("direction") or "change",
            time_period=parsed.get("time_period"),
            provider_used=provider,
            hypotheses=hypotheses,
            validated_hypotheses=validated,
            summary=summary
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
        started_at = datetime.now()
        yield sse("status", {"stage": "start", "provider": provider})

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
        tavily = get_tavily_client()
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
            if (not r1) or (len(r1) < 2) or (not validation.get("validated")):
                q2 = refine_query(query)
                if q2 and q2 != query:
                    second_pass_used = True
                    second_query = q2
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
            "latency_ms": int((datetime.now() - started_at).total_seconds() * 1000),
        }
        yield sse("final", resp)

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

def process_hypotheses_parallel(hypotheses: Dict, parsed: Dict, provider: Optional[str] = None) -> Dict[str, List[Dict]]:
    """Process each hypothesis: search + validate in parallel.

    Implements a targeted second-pass search (Option A) when the first pass is weak.
    """

    results = {"market": [], "brand": [], "competitive": []}
    errors = []

    all_tasks = []
    for cat in ["market", "brand", "competitive"]:
        for hyp in hypotheses.get(cat, []):
            all_tasks.append((hyp, cat))

    print(f"Processing {len(all_tasks)} hypotheses...")

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
            return None

        try:
            # Pass 1
            print(f"Searching: {query[:50]}...")
            sr1 = tavily.search(
                query=query,
                search_depth="basic",
                max_results=3,
                include_raw_content=True,
            )
            r1 = sr1.get("results", []) or []
            print(f"Found {len(r1)} results for: {query[:30]}...")

            validation = {"validated": False, "evidence": ""}
            if r1:
                validation = validate_hypothesis(hyp, r1, provider=provider)
                print(f"Validation: {validation.get('validated')} - {validation.get('evidence', '')[:50]}...")

            # Option A: targeted second-pass when weak
            second_pass_used = False
            if (not r1) or (len(r1) < 2) or (not validation.get("validated")):
                q2 = refine_query(query)
                if q2 and q2 != query:
                    second_pass_used = True
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
                    "status": "VALIDATED",
                    "hypothesis": hyp.get("hypothesis"),
                    "evidence": validation.get("evidence"),
                    "source": r1[0].get("url"),
                    "source_title": r1[0].get("title"),
                    "second_pass_used": second_pass_used,
                }

        except Exception as e:
            error_msg = f"Tavily error for '{query[:30]}...': {str(e)}"
            print(error_msg)
            errors.append(error_msg)
            return {"error": str(e), "category": cat}

        return None
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_task = {executor.submit(process_one, hyp, cat): (hyp, cat) for hyp, cat in all_tasks}
        
        for future in as_completed(future_to_task):
            hyp, cat = future_to_task[future]
            try:
                result = future.result()
                if result and "error" not in result:
                    results[cat].append(result)
            except Exception as e:
                print(f"Thread error: {e}")
    
    print(f"Results: market={len(results['market'])}, brand={len(results['brand'])}, competitive={len(results['competitive'])}")
    if errors:
        print(f"Errors encountered: {len(errors)}")
    
    return results

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
