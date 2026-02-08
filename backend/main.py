"""
Researcher API - Hypothesis-driven brand metric analysis
Uses Anthropic Claude + Tavily Search
"""

import os
import json
import re
from typing import Dict, List, Any, Optional
from datetime import datetime
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic
from tavily import TavilyClient

app = FastAPI(title="Researcher API", version="0.1.0")

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
anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
tavily_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

# Models
class ResearchRequest(BaseModel):
    question: str

class ResearchResponse(BaseModel):
    question: str
    brand: str
    metrics: List[str]  # Frontend expects array
    direction: str
    time_period: Optional[str]
    hypotheses: Dict[str, List[Dict]]
    validated_hypotheses: Dict[str, List[Dict]]  # Changed from validated_findings
    summary: Dict[str, List[Dict]]

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
    
    try:
        # Step 1: Parse question
        parsed = parse_question(req.question)
        
        # Step 2: Get competitors
        competitors = COMPETITOR_DB.get(parsed["brand"], [])
        
        # Step 3: Generate hypotheses
        hypotheses = generate_hypotheses(parsed, competitors)
        
        # Step 4: Process hypotheses in parallel (search + validate)
        validated = process_hypotheses_parallel(hypotheses, parsed)
        
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
            brand=parsed["brand"],
            metrics=metrics_arr,
            direction=parsed["direction"],
            time_period=parsed.get("time_period"),
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
        raise HTTPException(status_code=400, detail=f"AI model error: {error_msg}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Research error: {str(e)}")

def parse_question(question: str) -> Dict:
    """Extract brand, metric, direction from question using Claude"""
    
    prompt = f"""Parse this brand research question and extract:
    - brand: The brand being discussed (lowercase)
    - metric: The metric mentioned (e.g., "salience", "awareness", "consideration")
    - direction: "increase", "decrease", or "change"
    - time_period: Any time period mentioned (e.g., "Q3 2025")
    
    Question: {question}
    
    Return ONLY valid JSON with these exact keys."""
    
    response = anthropic_client.messages.create(
        model="claude-3-5-haiku-20241022",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )
    
    try:
        content = response.content[0].text
        # Extract JSON from response
        json_match = re.search(r'\{.*?\}', content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except:
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

def generate_hypotheses(parsed: Dict, competitors: List[str]) -> Dict[str, List[Dict]]:
    """Generate hypotheses for market, brand, and competitive factors"""
    
    brand = parsed["brand"]
    direction = parsed["direction"]
    time_period = parsed.get("time_period", "2025")
    
    hypotheses = {"market": [], "brand": [], "competitive": []}
    
    # Market hypotheses - use static fallback if Claude fails
    market_prompt = f"""Generate 3-4 hypotheses about UK fashion retail MARKET trends 
    that could cause {direction} in brand salience for {brand}.
    
    Time period: {time_period}
    
    Return ONLY a JSON object like:
    {{"hypotheses": [{{"id": "M1", "hypothesis": "description", "search_query": "UK fashion trend Q3 2025"}}]}}"""
    
    try:
        response = anthropic_client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=1000,
            messages=[{"role": "user", "content": market_prompt}]
        )
        content = response.content[0].text
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
        response = anthropic_client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=1000,
            messages=[{"role": "user", "content": brand_prompt}]
        )
        content = response.content[0].text
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
        response = anthropic_client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=1000,
            messages=[{"role": "user", "content": comp_prompt}]
        )
        content = response.content[0].text
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

def process_hypotheses_parallel(hypotheses: Dict, parsed: Dict) -> Dict[str, List[Dict]]:
    """Process each hypothesis: search + validate in parallel"""
    
    results = {"market": [], "brand": [], "competitive": []}
    errors = []
    
    all_tasks = []
    for cat in ["market", "brand", "competitive"]:
        for hyp in hypotheses.get(cat, []):
            all_tasks.append((hyp, cat))
    
    print(f"Processing {len(all_tasks)} hypotheses...")
    
    def process_one(hyp, cat):
        query = hyp.get("search_query", hyp.get("hypothesis", ""))
        if not query:
            return None
        
        # Tavily search
        try:
            print(f"Searching: {query[:50]}...")
            search_result = tavily_client.search(
                query=query,
                search_depth="basic",
                max_results=3,
                include_raw_content=True
            )
            
            print(f"Found {len(search_result.get('results', []))} results for: {query[:30]}...")
            
            if search_result.get("results"):
                # Validate using Claude
                validation = validate_hypothesis(hyp, search_result["results"])
                print(f"Validation: {validation.get('validated')} - {validation.get('evidence', '')[:50]}...")
                if validation.get("validated"):
                    return {
                        "status": "VALIDATED",
                        "hypothesis": hyp.get("hypothesis"),
                        "evidence": validation.get("evidence"),
                        "source": search_result["results"][0].get("url"),
                        "source_title": search_result["results"][0].get("title")
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

def validate_hypothesis(hypothesis: Dict, search_results: List[Dict]) -> Dict:
    """Use Claude to validate if search results support the hypothesis"""
    
    search_text = "\n\n".join([
        f"Title: {r.get('title', '')}\nContent: {r.get('raw_content', r.get('content', ''))[:500]}"
        for r in search_results[:2]
    ])
    
    prompt = f"""Hypothesis: {hypothesis.get('hypothesis')}

Search Results:
{search_text}

Does this search result contain direct evidence supporting the hypothesis?
Return JSON: {{"validated": true/false, "evidence": "SHORT factual summary (20 words max) with key numbers/dates"}}"""
    
    response = anthropic_client.messages.create(
        model="claude-3-5-haiku-20241022",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )
    
    try:
        content = response.content[0].text
        json_match = re.search(r'\{.*?\}', content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except:
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
