# KAIA Researcher — Requirements & Implementation Status

**Document Version:** 1.1  
**Last Updated:** 2026-02-13  
**Backend Version:** v17  
**Frontend Version:** SWA (Static Web App)

---

## Table of Contents

1. [Source Policy](#1-source-policy)
2. [No Inference Rule](#2-no-inference-rule)
3. [Query Filtering & Metric Validation](#3-query-filtering--metric-validation)
4. [Request Precision & Minimum Information](#4-request-precision--minimum-information)
5. [Executive Summary](#5-executive-summary)
6. [UI/UX — Split-Pane Layout](#6-uiux--split-pane-layout)
7. [Evaluation Framework](#7-evaluation-framework)
8. [Model Selection](#8-model-selection)

---

## 1. Source Policy

### Requirement

> The Metric Analysis Agent may pull news from a broad set of providers, but each source requires a quality grade so items can be prioritised accordingly.
>
> Social media posts (e.g. X/Twitter, TikTok, Instagram, Facebook) are out of scope for the POC and must not appear as news items.
>
> Top tier 'Trusted' sources: Reuters, Bloomberg, Financial Times, WSJ, Adweek, Ad Age, The Drum, Campaign, Marketing Week, Kantar Media, McKinsey ConsumerWise, Mintel, Euromonitor.
>
> Steer the LLM to use these sources first, but not be limited to them.

### Implementation Status: ✅ IMPLEMENTED (v17)

**Backend (`main.py`):**

| Feature | Status | Details |
|---------|--------|---------|
| Default trusted sources list | ✅ Done | 24 sources configured with trust scores (3-10) and tiers (`trusted`, `reputable`, `unverified`) |
| Social media blocklist | ✅ Done | 13 social media domains blocked: Twitter/X, TikTok, Instagram, Facebook, Reddit, LinkedIn, Pinterest, Snapchat, YouTube, Threads |
| Source scoring | ✅ Done | Every search result is scored against the trusted list. `_score_source()` extracts root domain and matches. |
| Source filtering | ✅ Done | `_is_social_media()` removes blocked sources from results before they reach validation. |
| Source prioritization | ✅ Done | Results sorted by `trust_score` descending — trusted sources appear first for validation. |
| Source trust metadata on results | ✅ Done | Each hypothesis result includes `trust_score`, `tier`, `source_name`, `is_trusted` fields. |
| Source policy stats | ✅ Done | Final response includes `source_policy` with `trusted_ratio`, `trusted_source_count`, `total_source_count`. |
| `/sources` GET endpoint | ✅ Done | Returns current trusted sources list and social media blocklist. |
| `/sources` PUT endpoint | ✅ Done | Allows updating the trusted sources list at runtime. |
| `/sources/reset` POST endpoint | ✅ Done | Resets trusted sources to defaults. |
| Per-request trusted sources | ✅ Done | `trusted_sources` field on `ResearchRequest` allows frontend to pass custom list per query. |

**Frontend (`Settings.tsx`):**

| Feature | Status | Details |
|---------|--------|---------|
| Trusted sources editor | 🔲 TODO | Settings page needs UI for viewing/editing sources, trust scores, and tiers |
| Add/remove sources | 🔲 TODO | Needs add row, delete row, inline editing |
| Trust score slider | 🔲 TODO | 1-10 score slider per source |

**Trusted Sources List (Default Configuration):**

| Source | Trust Score | Tier |
|--------|:-----------:|------|
| Reuters | 10 | Trusted |
| Bloomberg | 10 | Trusted |
| Financial Times | 10 | Trusted |
| Wall Street Journal | 10 | Trusted |
| Kantar | 10 | Trusted |
| Adweek | 9 | Trusted |
| Ad Age | 9 | Trusted |
| The Drum | 9 | Trusted |
| Campaign | 9 | Trusted |
| Marketing Week | 9 | Trusted |
| McKinsey | 9 | Trusted |
| Mintel | 9 | Trusted |
| Euromonitor | 9 | Trusted |
| CNBC | 8 | Reputable |
| BBC | 8 | Reputable |
| The Guardian | 8 | Reputable |
| New York Times | 8 | Reputable |
| Marketing Dive | 8 | Reputable |
| WWD | 8 | Reputable |
| Forbes | 7 | Reputable |
| Business Insider | 7 | Reputable |
| Yahoo Finance | 7 | Reputable |

---

## 2. No Inference Rule

### Requirement

> There should be no inference against results (i.e., inferencing what the search results mean for changes in the data or conclusions for the client). Mixing internal validated data vs. online sources would be high risk in this case, and sufficient benefits can be delivered by returning high quality and relevant results for CS to interpret.

### Implementation Status: ✅ IMPLEMENTED (v17)

**Changes made:**

1. **Validation prompt updated** (`validate_hypothesis()` in `main.py`):
   - Added explicit rules: `DO NOT make inferences or draw conclusions about what the evidence means for the brand or client`
   - Added: `DO NOT interpret or speculate beyond what the sources explicitly state`
   - Added: `Only report the factual findings from the search results`
   - Added: `Your evidence should be a direct summary of what the source says, not an interpretation`

2. **Executive summary prompt** (new in v17):
   - Follows the same no-inference rule: `Report ONLY the factual findings from the sources. DO NOT make inferences, draw conclusions about what the findings mean for the brand, or provide recommendations.`

**Before (v16):**
```
Does this search result contain relevant information that supports or relates to the hypothesis?
Be generous — if the evidence is even partially relevant, validate it.
Return JSON: {"validated": true/false, "evidence": "SHORT factual summary (20 words max) with key numbers/dates"}
```

**After (v17):**
```
Does this search result contain relevant factual information that supports or relates to the hypothesis?
Be generous — if the evidence is even partially relevant, validate it.

IMPORTANT RULES:
- DO NOT make inferences or draw conclusions about what the evidence means for the brand or client.
- DO NOT interpret or speculate beyond what the sources explicitly state.
- Only report the factual findings from the search results.
- Your evidence should be a direct summary of what the source says, not an interpretation.

Return JSON: {"validated": true/false, "evidence": "SHORT factual summary (20 words max) with key numbers/dates from the source"}
```

---

## 3. Query Filtering & Metric Validation

### Requirement

> Search must be related to specific metric (incl. Image statement).
>
> Stick to a single metric at a time. Only allow grouping for:
> - MDS – M + D + S
> - Funnels – all metrics in funnel
>
> Ask follow-up questions to check.
>
> If no metric mentioned at all – prompt to ask which metric.
> If no clear match – play back metric.
> Map closest metric based on first or follow up prompt. Do not refuse to help if can't find identical match.

### Implementation Status: 🔲 TODO

**Planned Implementation:**

1. **Metric validation step** — Add a pre-check after `parse_question()` that validates the extracted metric against a known list:
   - Salience, Meaningfulness, Difference (MDS components)
   - Awareness, Consideration, Preference, Purchase (Funnel metrics)  
   - Image statements (custom per brand)
   - Category Entry Points

2. **Follow-up question flow** — If no metric is detected:
   - Return a `coaching` response asking: "Which metric would you like to explore? (e.g., Salience, Meaningfulness, Difference)"
   - Support natural language mapping: "not using the best ingredients" → closest Image statement

3. **Metric grouping rules:**
   - If user says "MDS" → expand to M + D + S (3 separate searches)
   - If user says "funnel" → expand to all funnel metrics
   - Otherwise → single metric only

4. **Implementation approach:**
   - Add `VALID_METRICS` dictionary with canonical names and aliases
   - Add `validate_metric()` function that maps free-text to closest metric
   - Modify `parse_question()` to extract metric and validate
   - If no match → return coaching response before search begins

---

## 4. Request Precision & Minimum Information

### Requirement

> Minimum information required: Brand, Market, Category, Time periods.
>
> If not specified — For brand, market, category, use default from settings.
> If specified — over-rule settings.
> If time-period not specified — use last year.

### Implementation Status: 🔲 TODO

**Planned Implementation:**

1. **Default settings** — Add to `AppSettings` (frontend) and `/research` request:
   - `default_brand`: e.g., "New Look"
   - `default_market`: e.g., "United Kingdom"
   - `default_category`: e.g., "Fashion Retail"
   - `default_time_period`: "last year" (auto-resolved to current year - 1)

2. **Parse question enhancement** — After `parse_question()`, check for missing fields:
   - Brand: If not mentioned → use `default_brand` from settings
   - Market: If not mentioned → use `default_market` from settings
   - Category: If not mentioned → use `default_category` from settings
   - Time period: If not mentioned → default to "last year" (e.g., "2025")

3. **Follow-up flow** — If brand is completely ambiguous and no default set:
   - Return a coaching response: "Which brand would you like to research?"
   - Don't refuse to search — fill in defaults silently when possible

4. **Settings UI** — Add defaults section to Settings page with dropdowns for brand, market, category.

---

## 5. Executive Summary

### Requirement

> The response should include an executive summary that synthesizes the validated findings.

### Implementation Status: ✅ IMPLEMENTED (v17)

**Changes made:**

1. **New pipeline step** — After hypothesis validation and summary building:
   - Collects all validated evidence across categories
   - Calls LLM with a no-inference summary prompt
   - Generates 3-5 sentence executive summary of factual findings

2. **SSE streaming event** — New `executive_summary` event emitted before `final`:
   ```
   event: executive_summary
   data: {"summary": "Nike launched its 'Why Do It?' campaign..."}
   ```

3. **Final response** — `executive_summary` field included in the `final` response payload.

4. **No-inference rule applied** — Summary prompt explicitly states:
   - `Report ONLY the factual findings from the sources`
   - `DO NOT make inferences, draw conclusions, or provide recommendations`

**Frontend:**

| Feature | Status | Details |
|---------|--------|---------|
| Display executive summary in detail pane | 🔲 TODO | Will be shown at top of right-pane report view |

---

## 6. UI/UX — Split-Pane Layout

### Requirement

> The UI should stream the response on the right pane. Only the card is persisted in the chat UI and clicking a card loads the full response in the right pane.

### Implementation Status: 🔲 TODO

**Reference:** User provided mockup showing:
- **Left pane**: Chat interface with compact result cards (icon, title, "Click to view report →")
- **Right pane**: Full report view with executive summary, sections for each category, source citations

**Planned Implementation:**

1. **Chat card component** — Compact card in the message thread:
   - Brand name + metric + direction
   - Validated count badge (e.g., "8/12 validated")
   - "Click to view report →" action
   - Timestamp and model used

2. **Detail pane component** — Right-side panel (replaces current inline display):
   - Header: Brand, Market, Metric, Time Period, Change Summary
   - Section 1: Executive Summary
   - Section 2: Market/Macro Drivers (validated findings with source badges)
   - Section 3: Brand-specific Insights
   - Section 4: Competitive Landscape
   - Source trust indicators (green shield for trusted, amber for reputable, grey for unverified)
   - Export button

3. **Streaming behavior**:
   - As SSE events arrive, populate the detail pane in real-time
   - Show loading skeleton while waiting for each section
   - Card in chat updates with final validation count when complete

---

## 7. Evaluation Framework

### Requirement

> **Citation accuracy** — validate proportion of outputs that come from trusted sources vs. non-trusted (expect a high ratio from trusted sources).
>
> **Adherence to rules** — have rules been followed e.g. not including social media posts, no inference.
>
> **Recency** — validate if sources are in the correct time period given.
>
> **Wider OOB evaluations** — e.g., adversarial testing.
>
> Based on initial feedback, develop 'ground source truth data sets' to measure against. Create test cases of what a good answer looks like for a certain prompt, for us to implement measurement tests against for (a) accuracy, and (b) consistency.

### Implementation Status: 🟡 PARTIAL

| Evaluation | Status | Details |
|------------|--------|---------|
| Citation accuracy (trusted ratio) | ✅ Done | `source_policy.trusted_ratio` in response. `/sources` endpoint enables configuration. |
| Social media filtering | ✅ Done | 13 social platforms blocked. All results filtered before validation. |
| No inference rule | ✅ Done | Validation and summary prompts explicitly prevent inference. |
| Recency validation | 🔲 TODO | Need to add date extraction from sources and compare to requested time period. |
| Adversarial testing | 🔲 TODO | Need test suite with adversarial prompts (injection, off-topic, ambiguous). |
| Ground truth datasets | 🔲 TODO | Need curated test cases with expected "good answers" for accuracy/consistency testing. |
| Consistency testing | 🔲 TODO | Need automated tests that run the same prompt N times and measure output variance. |
| Eval dashboard | 🔲 TODO | Need UI for viewing evaluation metrics across runs. `/runs` endpoint exists for basic telemetry. |

**Planned Implementation:**

1. **Recency validation** — Parse source dates from search results, flag sources outside the requested time period.

2. **Ground truth test suite** — Create `eval_ground_truth.json` with:
   ```json
   {
     "test_cases": [
       {
         "prompt": "Why did Nike salience increase in Q4 2025?",
         "expected_brand": "Nike",
         "expected_metric": "salience",
         "expected_findings": ["campaign", "store opening", "competitor activity"],
         "min_validation_rate": 0.5,
         "min_trusted_ratio": 0.6
       }
     ]
   }
   ```

3. **Consistency test** — Run same prompt 3x, measure:
   - Do the same categories get validated?
   - Is the validation rate within ±15%?
   - Do the same key findings appear?

---

## 8. Confidence Thresholds

### Requirement

> V2 validates each hypothesis with a binary, should there be a confidence score threshold below which a hypothesis is excluded from the final report? Currently everything validated=true gets included regardless of evidence strength.
>
> For now return all.
> Once we get hands on testing — will give feedback on outputs.
> Save the reasoning process per prompt so we can assess + debug.

### Implementation Status: 🟡 PARTIAL

| Feature | Status | Details |
|---------|--------|--------|
| Binary validation (current) | ✅ Done | All `validated=true` results included in final report |
| Confidence score on results | 🔲 TODO | Add a 1-10 confidence score from the LLM during validation |
| Confidence threshold filtering | 🔲 TODO | Add configurable threshold in settings (for future, not POC) |
| Reasoning trace saved per prompt | 🔲 TODO | Save full reasoning chain: raw search results, validation prompts, LLM responses |

**Planned Implementation:**

1. **Reasoning trace** — For each hypothesis, save:
   - The search query used
   - Raw search results returned (URLs, titles, content snippets)
   - The validation prompt sent to LLM
   - The raw LLM response (before JSON extraction)
   - The extracted validation result
   - This enables post-hoc assessment of why a hypothesis was validated or rejected

2. **Confidence score** — Modify validation prompt to return `{"validated": true/false, "confidence": 1-10, "evidence": "..."}`. For now, include all results regardless of confidence. Threshold filtering will be added based on hands-on testing feedback.

---

## 9. Source Priority & Labelling

### Requirement

> Keep trusted sources. Look for trusted sources first. Keep excluded sources — social media, competitors.
>
> Add two labels in line with output:
> - 'Verified source'
> - 'Non verified source'
>
> Prioritise trusted sources:
> 1. **1st priority** = Trusted sources (Reuters, Bloomberg, FT, etc.)
> 2. **2nd priority** = Brand website for the brand being searched (where relevant)
> 3. **3rd priority** = Open search (but NOT competitor research firms i.e. Ipsos, or social)
>
> Maria to share list of competitor sources.

### Implementation Status: 🟡 PARTIAL

| Feature | Status | Details |
|---------|--------|--------|
| Trusted sources list | ✅ Done | 24 sources with trust scores, configurable via `/sources` API |
| Social media exclusion | ✅ Done | 13 platforms blocked |
| Source scoring & sorting | ✅ Done | Results sorted by trust_score descending |
| `is_trusted` flag on results | ✅ Done | Each result tagged with `is_trusted: true/false` |
| "Verified" / "Non verified" labels | 🔲 TODO | Frontend display labels based on `is_trusted` flag |
| Brand website priority (tier 2) | 🔲 TODO | Auto-detect brand domain and boost its score |
| Competitor research firm exclusion | 🔲 TODO | Need list from Maria (Ipsos, etc.) — add to `COMPETITOR_DOMAINS` blocklist |
| 3-tier priority scoring | 🔲 TODO | Implement priority: trusted (10) → brand site (8) → open (3), competitors (0/blocked) |

**Planned Implementation:**

1. **Brand website detection** — After parsing the brand from the question, auto-generate the likely brand domain (e.g., "Nike" → `nike.com`, `about.nike.com`) and give it tier-2 priority.

2. **Competitor exclusion list** — Add `COMPETITOR_DOMAINS` (Ipsos, Nielsen, GfK, etc.) alongside `SOCIAL_MEDIA_DOMAINS`. Block these from appearing in results.

3. **Frontend labels** — In the report detail view, each source citation gets:
   - 🟢 **Verified source** badge (green) for `is_trusted: true`
   - 🟡 **Non verified source** badge (amber) for `is_trusted: false`

---

## 10. Reasoning Trace & Debug Logging

### Requirement

> Save the reasoning process per prompt so we can assess + debug.

### Implementation Status: 🔲 TODO

**Planned Implementation:**

1. **Per-hypothesis trace** — Each hypothesis gets a `reasoning_trace` object:
   ```json
   {
     "hypothesis": "Nike launched a campaign...",
     "search_query": "nike campaign Q4 2025",
     "search_results_raw": [{"url": "...", "title": "...", "snippet": "..."}],
     "validation_prompt": "Hypothesis: Nike launched... Search Results: ...",
     "llm_response_raw": "{\"validated\": true, \"evidence\": \"...\"}",
     "validation_result": {"validated": true, "evidence": "..."},
     "timestamp": "2026-02-13T15:50:00Z"
   }
   ```

2. **Debug endpoint** — Add `/runs/{run_id}/trace` to retrieve full reasoning trace for a specific run.

3. **Storage** — Initially in-memory (like current `RUN_LOG`), later persist to Azure Blob or Cosmos DB for long-term analysis.

4. **Frontend** — Add a "Debug" or "Trace" button in the report detail view that shows the raw reasoning for each hypothesis (collapsible panel).

---

## 11. Model Selection

### Requirement

> Test and compare deployed Azure OpenAI models to find the optimal model for web search grounding.

### Implementation Status: ✅ IMPLEMENTED (v16)

**Testing Results (see `model_comparison_report.md`):**

| Model | Validated | Rate | Tier |
|-------|-----------|------|------|
| 🏆 gpt-4-1-nano | 10/12 | 83.3% | Nano |
| 🥈 gpt-4-1-mini | 9/12 | 75.0% | Mini |
| 🥉 gpt-4o | 8/12 | 66.7% | Full |
| gpt-4o-latest | 6/12 | 50.0% | Full |
| gpt-4-1 | 5/12 | 41.7% | Full |
| gpt-5-mini | — | — | ⛔ Timeout |
| gpt-5-nano | — | — | ⛔ Timeout |

**Current Configuration:**
- `OPENAI_SEARCH_MODEL=gpt-4-1-nano` (default for web search)
- `OPENAI_MODEL=gpt-4o-mini` (for non-search LLM calls)
- 7 deployments available via `/models` endpoint
- Per-request model override via `model` field on request

**Frontend:**

| Feature | Status | Details |
|---------|--------|---------|
| Model selector in settings | 🔲 TODO | `/models` endpoint ready, needs UI dropdown |

---

## API Endpoints Summary

| Endpoint | Method | Status | Description |
|----------|--------|--------|-------------|
| `/research` | POST | ✅ | Synchronous research pipeline |
| `/research/stream` | POST | ✅ | SSE streaming research pipeline |
| `/models` | GET | ✅ | List available model deployments |
| `/sources` | GET | ✅ v17 | Get trusted sources configuration |
| `/sources` | PUT | ✅ v17 | Update trusted sources list |
| `/sources/reset` | POST | ✅ v17 | Reset sources to defaults |
| `/runs` | GET | ✅ | Get telemetry for recent runs |
| `/health` | GET | ✅ | Health check |

---

## Deployment History

| Version | Date | Key Changes |
|---------|------|-------------|
| v14 | 2026-02-13 | Dual-query search, per-request model selection, temperature fix |
| v15 | 2026-02-13 | Added gpt-4-1-mini, gpt-4-1-nano, gpt-5-nano deployments |
| v16 | 2026-02-13 | Set default to gpt-4-1-nano, updated model descriptions |
| v17 | 2026-02-13 | Trusted sources, social media filtering, no-inference rule, executive summary, source policy stats |

---

## Priority Backlog

| Priority | Feature | Effort | Dependencies |
|----------|---------|--------|-------------|
| 🔴 P0 | Split-pane UI with streaming detail view | Medium | Frontend redesign |
| 🔴 P0 | Trusted sources editor in Settings | Small | `/sources` API (done) |
| 🔴 P0 | Verified/Non-verified source labels in UI | Small | `is_trusted` flag (done) |
| 🟡 P1 | Metric validation & follow-up questions | Medium | `VALID_METRICS` dictionary |
| 🟡 P1 | Default brand/market/category in Settings | Small | Settings store update |
| 🟡 P1 | Model selector in Settings | Small | `/models` API (done) |
| 🟡 P1 | Reasoning trace saved per hypothesis | Medium | Backend trace logging |
| 🟡 P1 | Competitor research firm exclusion list | Small | List from Maria (Ipsos, etc.) |
| 🟡 P1 | Brand website tier-2 priority scoring | Small | Parse brand → domain mapping |
| 🟢 P2 | Confidence score (1-10) from LLM | Small | Validation prompt update |
| 🟢 P2 | Recency validation | Small | Date extraction from sources |
| 🟢 P2 | Ground truth test suite | Medium | Test case curation |
| 🟢 P2 | Consistency testing framework | Medium | Automated test runner |
| 🟢 P2 | Debug/Trace viewer in report detail | Medium | Reasoning trace (P1) |
| 🟢 P2 | Evaluation dashboard | Large | `/runs` enhancement + UI |
