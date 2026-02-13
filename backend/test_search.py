#!/usr/bin/env python3
"""Diagnostic test for Azure OpenAI web_search_preview.

Runs a single research question end-to-end and prints detailed output
at every step so we can see exactly what's happening.

Usage:
  python test_search.py                     # test against deployed Azure API
  python test_search.py --local             # test against localhost:8000
  python test_search.py --direct            # test openai_web_search directly (requires env vars)
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


def test_direct_search():
    """Test openai_web_search directly against Azure OpenAI."""
    # Import from main.py
    sys.path.insert(0, os.path.dirname(__file__))
    from main import openai_web_search, _is_azure, OPENAI_MODEL

    print(f"\n{'='*70}")
    print(f"DIRECT SEARCH TEST")
    print(f"  Azure mode: {_is_azure}")
    print(f"  Model: {OPENAI_MODEL}")
    print(f"  Search model: {os.getenv('OPENAI_SEARCH_MODEL', OPENAI_MODEL)}")
    print(f"{'='*70}\n")

    test_queries = [
        "Nike Q4 2025 social media marketing campaign China",
        "Adidas Q4 2025 marketing campaign launch",
        "Nike sales revenue Q4 2025",
    ]

    for i, query in enumerate(test_queries, 1):
        print(f"\n--- Query {i}/{len(test_queries)}: {query} ---")
        start = time.time()
        try:
            results = openai_web_search(query)
            elapsed = time.time() - start
            print(f"  Duration: {elapsed:.1f}s")
            print(f"  Results: {len(results)}")
            for j, r in enumerate(results[:3]):
                print(f"    [{j}] title: {r.get('title', '')[:60]}")
                print(f"        url: {r.get('url', '')[:80]}")
                content = r.get('raw_content', r.get('content', ''))
                print(f"        content: {content[:200]}...")
        except Exception as e:
            elapsed = time.time() - start
            print(f"  ERROR after {elapsed:.1f}s: {e}")

        # Rate limit protection
        if i < len(test_queries):
            print(f"  (waiting 3s before next query...)")
            time.sleep(3)


def test_api(base_url: str):
    """Test the full research API endpoint."""
    print(f"\n{'='*70}")
    print(f"API TEST: {base_url}")
    print(f"{'='*70}\n")

    # Step 1: Health check
    print("1. Health check...")
    try:
        r = httpx.get(f"{base_url}/", headers={"Authorization": f"Bearer {APP_PASSWORD}"}, timeout=10)
        print(f"   Status: {r.status_code}")
    except Exception as e:
        print(f"   ERROR: {e}")
        return

    # Step 2: Send research request (streaming)
    print(f"\n2. Research question: {QUESTION[:60]}...")
    print(f"   Streaming response...\n")

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {APP_PASSWORD}"}
    payload = {
        "question": QUESTION,
        "provider": "openai",
        "password": APP_PASSWORD,
    }

    start = time.time()
    hypotheses_seen = {"market": 0, "brand": 0, "competitive": 0}
    validated_count = {"market": 0, "brand": 0, "competitive": 0}
    errors = []

    try:
        with httpx.stream(
            "POST",
            f"{base_url}/research",
            json=payload,
            headers=headers,
            timeout=httpx.Timeout(300.0, connect=30.0),
        ) as response:
            print(f"   HTTP Status: {response.status_code}")
            if response.status_code != 200:
                print(f"   Body: {response.read().decode()[:500]}")
                return

            buffer = ""
            for chunk in response.iter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    event_raw, buffer = buffer.split("\n\n", 1)
                    lines = event_raw.strip().split("\n")
                    event_type = None
                    data_str = None
                    for line in lines:
                        if line.startswith("event: "):
                            event_type = line[7:]
                        elif line.startswith("data: "):
                            data_str = line[6:]

                    if not event_type or not data_str:
                        continue

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    elapsed = time.time() - start

                    if event_type == "status":
                        stage = data.get("stage", "")
                        print(f"   [{elapsed:5.1f}s] STATUS: {stage}")
                        if "total_hypotheses" in data:
                            print(f"           Total hypotheses: {data['total_hypotheses']}")

                    elif event_type == "hypotheses":
                        for cat in ["market", "brand", "competitive"]:
                            hyps = data.get(cat, [])
                            hypotheses_seen[cat] = len(hyps)
                            if hyps:
                                print(f"   [{elapsed:5.1f}s] HYPOTHESES ({cat}): {len(hyps)} generated")
                                for h in hyps:
                                    print(f"           - {h.get('hypothesis', '')[:80]}")
                                    print(f"             search_query: {h.get('search_query', '')[:60]}")

                    elif event_type == "hypothesis_result":
                        cat = data.get("category", "?")
                        validated = data.get("validated", False)
                        query = data.get("search_query", "")[:50]
                        evidence = data.get("evidence", "")[:60]
                        error = data.get("error", "")
                        completed = data.get("completed", "?")
                        total = data.get("total", "?")
                        result_count = data.get("result_count", 0)

                        status = "✅ VALIDATED" if validated else "❌ FAILED"
                        print(f"   [{elapsed:5.1f}s] {status} ({cat}) [{completed}/{total}]")
                        print(f"           query: {query}")
                        print(f"           results: {result_count}, evidence: {evidence}")
                        if error:
                            print(f"           ERROR: {error}")
                            errors.append(error)

                        if validated:
                            validated_count[cat] += 1

                    elif event_type == "summary":
                        print(f"\n   [{elapsed:5.1f}s] SUMMARY received")
                        for key in ["macro_drivers", "brand_drivers", "competitive_drivers"]:
                            drivers = data.get(key, [])
                            print(f"           {key}: {len(drivers)} items")
                            for d_item in drivers:
                                print(f"             - {d_item.get('hypothesis', '')[:70]}")

                    elif event_type == "complete":
                        total_time = data.get("total_time_seconds", elapsed)
                        print(f"\n   [{elapsed:5.1f}s] COMPLETE (server: {total_time:.1f}s)")

                    elif event_type == "error":
                        print(f"   [{elapsed:5.1f}s] ERROR: {data}")

    except Exception as e:
        elapsed = time.time() - start
        print(f"\n   EXCEPTION after {elapsed:.1f}s: {e}")

    # Summary
    total = time.time() - start
    print(f"\n{'='*70}")
    print(f"RESULTS SUMMARY")
    print(f"{'='*70}")
    print(f"  Total time: {total:.1f}s")
    print(f"  Hypotheses generated: market={hypotheses_seen['market']}, brand={hypotheses_seen['brand']}, competitive={hypotheses_seen['competitive']}")
    print(f"  Validated:            market={validated_count['market']}, brand={validated_count['brand']}, competitive={validated_count['competitive']}")
    print(f"  Total validated: {sum(validated_count.values())} / {sum(hypotheses_seen.values())}")
    if errors:
        print(f"  Errors: {len(errors)}")
        for e in errors[:5]:
            print(f"    - {e[:80]}")

    # Quality assessment
    total_validated = sum(validated_count.values())
    if total_validated >= 8:
        print(f"\n  ✅ QUALITY: GOOD ({total_validated} validated)")
    elif total_validated >= 5:
        print(f"\n  ⚠️  QUALITY: ACCEPTABLE ({total_validated} validated)")
    elif total_validated >= 2:
        print(f"\n  ❌ QUALITY: POOR ({total_validated} validated)")
    else:
        print(f"\n  🚫 QUALITY: FAILING ({total_validated} validated)")

    if total > 120:
        print(f"  🐢 SPEED: TOO SLOW ({total:.0f}s)")
    elif total > 60:
        print(f"  ⚠️  SPEED: SLOW ({total:.0f}s)")
    else:
        print(f"  ✅ SPEED: OK ({total:.0f}s)")

    # Check all categories
    for cat, count in validated_count.items():
        if count == 0:
            print(f"  🚫 MISSING CATEGORY: {cat} has 0 validated hypotheses!")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test KAIA Researcher search quality")
    parser.add_argument("--local", action="store_true", help="Test against localhost:8000")
    parser.add_argument("--direct", action="store_true", help="Test openai_web_search directly")
    args = parser.parse_args()

    if args.direct:
        test_direct_search()
    else:
        base_url = API_URL_LOCAL if args.local else API_URL_PROD
        test_api(base_url)
