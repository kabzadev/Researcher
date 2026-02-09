# Researcher – Eval Harness + Feedback Loop (MVP)

## Goals
1) **Compare providers** (Anthropic vs OpenAI) on a fixed set of questions.
2) **Score outputs** with simple, repeatable heuristics (evidence/citations/coverage/latency/tokens).
3) Collect **user feedback** (👍/👎 + optional comment) tied to a specific run.
4) Store eval + feedback data durably so we can export it later for model/prompt tuning.

## Non-goals (for MVP)
- Perfect “truth scoring” of the internet.
- Complex auth/users/roles (single app password gate remains).
- Full historical data warehouse.

## Storage (Best practice, minimal infra)
Use **workspace-based App Insights (Log Analytics)** as the durable store:
- Emit `ResearchRunSummary …{json}…` (already implemented)
- Add `EvalRun …{json}…`
- Add `UserFeedback …{json}…`

This is durable across replicas/scale-to-zero and exportable via Kusto queries.

## A. Eval Harness (hardcoded set in repo)
### 1) Add hardcoded eval question set
File: `backend/eval_questions.py` (or JSON)
- Array of ~10 metric-change style questions
- Each question has: `id`, `text`, optional `tags` (region/category)

### 2) Backend endpoints
- `GET /eval/questions` → returns list
- `POST /eval/run` → runs all questions against both providers (or subset)
  - returns per-question results + scores
  - logs a durable `EvalRun` event per (question, provider)

### 3) Scoring (simple + explainable)
Per provider answer:
- `drivers_total` = macro + brand + competitive
- `sections_nonempty` count
- `citations_total` (# source_urls across drivers)
- `unique_domains` across citations
- `has_any_validated` (drivers_total > 0)
- `latency_ms`, `tokens_total`, `tavily_searches`

Score (0–100) example:
- 30 pts: citations_total (capped)
- 30 pts: sections_nonempty (0–3)
- 20 pts: drivers_total (capped)
- 10 pts: unique_domains
- 10 pts: penalty for empty response / missing citations

### 4) UI
Add page: **Eval** in left nav.
- Button: “Run Eval (Both Providers)”
- Shows table: question × provider, score, drivers_total, sections
- Drilldown: see response + citations

## B. Feedback Loop (thumbs up/down)
### 1) UI
On each assistant response bubble:
- 👍 button
- 👎 button
If 👎:
- Modal prompts for:
  - “What was wrong?” (free text)
  - checkboxes (optional): Missing citations, Wrong brand/region, Hallucination, Too generic, Other

### 2) Backend
- `POST /feedback`
  - body: `run_id`, `provider_used`, `question`, `rating` (+1 / -1), `comment`, `tags` (optional)
  - logs durable `UserFeedback …{json}…`

### 3) Dashboard (follow-up)
Add to dashboard later:
- thumbs up rate
- top complaint tags
- low-score + thumbs-down correlation

## Testing / Validation Checklist
- Unit-ish test: call `/eval/run` from CLI, confirm events are logged.
- UI: verify thumbs up/down sends, modal works on mobile.
- Security: all endpoints except `/health` require Bearer password.
- Data: verify Kusto queries return EvalRun + UserFeedback.

## Work Breakdown (Tasks)
1) Add eval question set file (10 questions) and endpoint `GET /eval/questions`.
2) Implement `POST /eval/run` (sequential first, then parallel if needed).
3) Implement scoring function + return schema.
4) Add Eval UI page and navigation.
5) Add thumbs up/down UI + modal.
6) Add `POST /feedback` endpoint; log to App Insights.
7) Validate end-to-end and iterate.
