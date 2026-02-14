#!/usr/bin/env python3
"""Model comparison test for KAIA Researcher.

Runs the same research question against multiple Azure OpenAI models
and generates a comparison report.

Usage:
  python test_search.py                     # test default model
  python test_search.py --model gpt-4o      # test specific model
  python test_search.py --compare           # compare ALL deployed models
  python test_search.py --local             # test against localhost:8000
"""

import argparse
import json
import os
import sys
import time

import httpx


API_URL_PROD = "https://kaia-researcher-api.icyglacier-f068d1b2.eastus.azurecontainerapps.io"
API_URL_LOCAL = "http://localhost:8000"
APP_PASSWORD = "KantarResearch"

QUESTION = "Salience increased in Q4 2025 for Nike in China — what external events could explain it?"

MODELS = [
    "gpt-4o",         # 2024-08-06 original
    "gpt-4o-latest",  # 2024-11-20 improved
    "gpt-4-1",        # 2025-04-14 GPT-4.1
    "gpt-5-mini",     # 2025-08-07 GPT-5 mini
]


def test_model(base_url: str, model: str = None, verbose: bool = True, max_per_category: int = None) -> dict:
    """Test a single model and return structured results."""
    label = model or "default"
    if verbose:
        print(f"\n{'='*70}")
        print(f"TESTING MODEL: {label}" + (f" (max_per_category={max_per_category})" if max_per_category else ""))
        print(f"{'='*70}\n")

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {APP_PASSWORD}"}
    payload = {
        "question": QUESTION,
        "provider": "openai",
    }
    if model:
        payload["model"] = model
    if max_per_category:
        payload["max_hypotheses_per_category"] = max_per_category

    start = time.time()

    try:
        # Use the non-streaming /research endpoint which returns JSON
        response = httpx.post(
            f"{base_url}/research",
            json=payload,
            headers=headers,
            timeout=httpx.Timeout(600.0, connect=30.0),
        )

        total = time.time() - start

        if response.status_code != 200:
            body = response.text[:500]
            if verbose:
                print(f"   HTTP {response.status_code}: {body}")
            return {"model": label, "error": f"HTTP {response.status_code}: {body[:100]}", "total_time": round(total, 1),
                    "hypotheses_total": 0, "validated_total": 0, "validation_rate": 0,
                    "market_hyps": 0, "brand_hyps": 0, "competitive_hyps": 0,
                    "market_validated": 0, "brand_validated": 0, "competitive_validated": 0,
                    "broad_queries_used": 0, "errors": 1, "validated_items": {}, "details": []}

        data = response.json()

        # Extract hypotheses counts
        hypotheses = data.get("hypotheses", {})
        hypotheses_seen = {
            "market": len(hypotheses.get("market", [])),
            "brand": len(hypotheses.get("brand", [])),
            "competitive": len(hypotheses.get("competitive", [])),
        }

        # Extract validated hypotheses
        validated = data.get("validated_hypotheses", {})
        validated_count = {
            "market": len(validated.get("market", [])),
            "brand": len(validated.get("brand", [])),
            "competitive": len(validated.get("competitive", [])),
        }

        validated_items = {"market": [], "brand": [], "competitive": []}
        for cat in ["market", "brand", "competitive"]:
            for item in validated.get(cat, []):
                validated_items[cat].append({
                    "hypothesis": (item.get("hypothesis") or "")[:100],
                    "evidence": (item.get("evidence") or "")[:100],
                    "source": (item.get("source_title") or item.get("source") or "")[:80],
                    "second_pass": item.get("second_pass_used", False),
                })

        # Count broad queries
        broad_used = sum(1 for cat in validated_items.values() for item in cat if item.get("second_pass"))

        total_hyps = sum(hypotheses_seen.values())
        total_validated = sum(validated_count.values())

        if verbose:
            print(f"   Time: {total:.1f}s")
            print(f"   Hypotheses: market={hypotheses_seen['market']}, brand={hypotheses_seen['brand']}, competitive={hypotheses_seen['competitive']}")
            print(f"   Validated: market={validated_count['market']}, brand={validated_count['brand']}, competitive={validated_count['competitive']}")
            print(f"   Total: {total_validated}/{total_hyps} ({round(total_validated/max(total_hyps,1)*100,1)}%)")
            print(f"   Broad queries rescued: {broad_used}")
            print()
            for cat in ["market", "brand", "competitive"]:
                items = validated_items[cat]
                if items:
                    print(f"   {cat.upper()} ({len(items)} validated):")
                    for item in items:
                        bp = " [broad]" if item.get("second_pass") else ""
                        print(f"     ✅ {item['hypothesis'][:70]}")
                        print(f"        Evidence: {item['evidence'][:70]}{bp}")
                else:
                    print(f"   {cat.upper()}: ❌ no validated results")

        # Also extract the summary
        summary = data.get("summary", {})

        result = {
            "model": label,
            "max_per_cat": max_per_category or 4,
            "total_time": round(total, 1),
            "hypotheses_total": total_hyps,
            "market_hyps": hypotheses_seen["market"],
            "brand_hyps": hypotheses_seen["brand"],
            "competitive_hyps": hypotheses_seen["competitive"],
            "validated_total": total_validated,
            "market_validated": validated_count["market"],
            "brand_validated": validated_count["brand"],
            "competitive_validated": validated_count["competitive"],
            "validation_rate": round(total_validated / max(total_hyps, 1) * 100, 1),
            "broad_queries_used": broad_used,
            "errors": 0,
            "validated_items": validated_items,
            "summary": summary,
            "details": [],
        }

        if verbose:
            print(f"\n   RESULT: {total_validated}/{total_hyps} validated ({result['validation_rate']}%) in {total:.1f}s")

        return result

    except Exception as e:
        elapsed = time.time() - start
        if verbose:
            print(f"   EXCEPTION after {elapsed:.1f}s: {e}")
        return {"model": label, "error": str(e), "total_time": round(elapsed, 1),
                "hypotheses_total": 0, "validated_total": 0, "validation_rate": 0,
                "market_hyps": 0, "brand_hyps": 0, "competitive_hyps": 0,
                "market_validated": 0, "brand_validated": 0, "competitive_validated": 0,
                "broad_queries_used": 0, "errors": 1, "validated_items": {}, "details": []}


def compare_models(base_url: str, models: list, wait_between: int = 90, max_per_category: int = None):
    """Run tests for multiple models and generate comparison."""
    results = []

    for i, model in enumerate(models):
        print(f"\n{'#'*70}")
        print(f"# MODEL {i+1}/{len(models)}: {model}")
        print(f"{'#'*70}")

        result = test_model(base_url, model=model, verbose=True, max_per_category=max_per_category)
        results.append(result)

        # Wait between models to let rate limits reset
        if i < len(models) - 1:
            print(f"\n   ⏳ Waiting {wait_between}s for rate limit reset...")
            time.sleep(wait_between)

    return results


def generate_report(results: list, output_path: str):
    """Generate a markdown comparison report."""
    # Sort by validation rate (desc), then by time (asc)
    ranked = sorted(results, key=lambda r: (-r["validated_total"], -r["validation_rate"], r["total_time"]))

    report = []
    report.append("# KAIA Researcher — Model Comparison Report")
    report.append(f"\n**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"\n**Test Question:** {QUESTION}")
    report.append("")

    # Summary table
    report.append("## Results Summary")
    report.append("")
    report.append("| Rank | Model | Hypotheses | Validated | Rate | Market | Brand | Competitive | Broad Rescued | Time |")
    report.append("|------|-------|------------|-----------|------|--------|-------|-------------|---------------|------|")

    for i, r in enumerate(ranked, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "  "
        error = " ⚠️" if r.get("error") else ""
        mpc = f" ({r.get('max_per_cat', 4)}/cat)" if r.get("max_per_cat") else ""
        report.append(
            f"| {medal} {i} | **{r['model']}**{mpc} | "
            f"{r['hypotheses_total']} | "
            f"{r['validated_total']} | "
            f"{r['validation_rate']}% | "
            f"{r['market_validated']}/{r['market_hyps']} | "
            f"{r['brand_validated']}/{r['brand_hyps']} | "
            f"{r['competitive_validated']}/{r['competitive_hyps']} | "
            f"{r['broad_queries_used']} | "
            f"{r['total_time']:.0f}s{error} |"
        )

    report.append("")

    # Winner
    winner = ranked[0]
    report.append("## 🏆 Recommendation")
    report.append("")
    if winner.get("error"):
        report.append(f"⚠️ **{winner['model']}** had errors: {winner['error']}")
    else:
        report.append(f"**Best Model: `{winner['model']}`**")
        report.append(f"- Validated **{winner['validated_total']}/{winner['hypotheses_total']}** hypotheses ({winner['validation_rate']}%)")
        report.append(f"- Completed in **{winner['total_time']:.0f}s**")
        report.append(f"- Coverage: Market={winner['market_validated']}, Brand={winner['brand_validated']}, Competitive={winner['competitive_validated']}")
        if winner['broad_queries_used'] > 0:
            report.append(f"- Used {winner['broad_queries_used']} broad fallback queries to recover results")
    report.append("")

    # Detailed results per model
    report.append("## Detailed Results")
    report.append("")

    for r in ranked:
        mpc = f" ({r.get('max_per_cat', 4)} per category)" if r.get("max_per_cat") else ""
        report.append(f"### {r['model']}{mpc}")
        report.append("")
        if r.get("error"):
            report.append(f"**Error:** {r['error']}")
            report.append("")
            continue

        report.append(f"- **Time:** {r['total_time']:.0f}s")
        report.append(f"- **Hypotheses:** {r['hypotheses_total']}")
        report.append(f"- **Validation Rate:** {r['validation_rate']}% ({r['validated_total']}/{r['hypotheses_total']})")
        report.append(f"- **Broad Queries Used:** {r['broad_queries_used']}")
        report.append("")

        for cat in ["market", "brand", "competitive"]:
            items = r.get("validated_items", {}).get(cat, [])
            hyps = r.get(f"{cat}_hyps", 0)
            report.append(f"**{cat.title()} ({len(items)}/{hyps} validated):**")
            if items:
                for item in items:
                    bp = " *(broad query)*" if item.get("second_pass") else ""
                    report.append(f"- {item['hypothesis']}")
                    report.append(f"  - Evidence: {item['evidence']}{bp}")
                    if item.get("source"):
                        report.append(f"  - Source: {item['source']}")
            else:
                report.append("- *(no validated results)*")
            report.append("")

    # Analysis
    report.append("## Analysis")
    report.append("")

    # Speed comparison
    times = [(r['model'], r['total_time']) for r in ranked if not r.get('error')]
    if times:
        fastest = min(times, key=lambda x: x[1])
        slowest = max(times, key=lambda x: x[1])
        report.append(f"**Speed:** Fastest was `{fastest[0]}` ({fastest[1]:.0f}s), slowest was `{slowest[0]}` ({slowest[1]:.0f}s)")
        report.append("")

    # Category coverage
    report.append("**Category Coverage:**")
    for r in ranked:
        if r.get("error"):
            continue
        missing = []
        if r['market_validated'] == 0:
            missing.append("Market")
        if r['brand_validated'] == 0:
            missing.append("Brand")
        if r['competitive_validated'] == 0:
            missing.append("Competitive")
        if missing:
            report.append(f"- `{r['model']}`: ❌ Missing {', '.join(missing)}")
        else:
            report.append(f"- `{r['model']}`: ✅ All categories covered")
    report.append("")

    # Broad query effectiveness
    report.append("**Dual-Query Strategy Effectiveness:**")
    for r in ranked:
        if r.get("error"):
            continue
        report.append(f"- `{r['model']}`: {r['broad_queries_used']} broad queries rescued additional results")
    report.append("")

    text = "\n".join(report)

    with open(output_path, "w") as f:
        f.write(text)

    print(f"\n📄 Report saved to: {output_path}")
    print(f"\n{text}")
    return text


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test KAIA Researcher search quality")
    parser.add_argument("--local", action="store_true", help="Test against localhost:8000")
    parser.add_argument("--model", type=str, help="Test a specific model deployment name")
    parser.add_argument("--compare", action="store_true", help="Compare all deployed models")
    parser.add_argument("--wait", type=int, default=90, help="Seconds to wait between model tests (default: 90)")
    parser.add_argument("--max-per-category", type=int, default=None, help="Override max hypotheses per category")
    args = parser.parse_args()

    base_url = API_URL_LOCAL if args.local else API_URL_PROD

    if args.compare:
        results = compare_models(base_url, MODELS, wait_between=args.wait, max_per_category=args.max_per_category)
        report_path = os.path.join(os.path.dirname(__file__), "..", "model_comparison_report.md")
        generate_report(results, report_path)
    elif args.model:
        result = test_model(base_url, model=args.model, verbose=True, max_per_category=args.max_per_category)
        print(f"\nFinal: {json.dumps({k: v for k, v in result.items() if k not in ('details', 'validated_items', 'summary')}, indent=2)}")
    else:
        result = test_model(base_url, model=None, verbose=True, max_per_category=args.max_per_category)
        print(f"\nFinal: {json.dumps({k: v for k, v in result.items() if k not in ('details', 'validated_items', 'summary')}, indent=2)}")
