# Researcher Recommendations

Structured feedback and improvement roadmap for the Researcher system.

---

## Recommendation List

### 1. Query Generation Approach

| Aspect | Current State | Recommendation |
|--------|--------------|----------------|
| **Topic** | User question → multiple queries → web search | Use **hypothesis-based approach** to:<br>1. Make output more complete and relevant to user questions<br>2. Make search more targeted<br>3. Make it easier to understand by the model |
| **Flow** | Direct query generation | User question → hypothesis on user question → web search |
| **Future** | N/A | Orchestrator determines if hypotheses need generation and if search engine should validate/invalidate them |

### 2. Task Decomposition

| Aspect | Current State | Recommendation |
|--------|--------------|----------------|
| **Approach** | Multiple things in single step (one agent searches all topics) | **Split tasks up** - one agent only searches one specific query for one specific hypothesis |
| **Output** | Combined processing | Generate summary based on **validated hypothesis's source** (not inference) |

### 3. Prompt Context

| Aspect | Current State | Recommendation |
|--------|--------------|----------------|
| **Context** | No embedded context | Add minimum context to prompts:<br>• Metrics definition<br>• How to interpret metrics<br>• What drives metrics up/down<br>• Competitor brands for target brand |
| **Source** | N/A | RAG or predefined dictionary (**preferred**) on each metric |

### 4. Prompt Refinement

| Aspect | Current State | Recommendation |
|--------|--------------|----------------|
| **Process** | N/A | Use CS feedback to refine prompts<br>Compare with golden question set vs. desirable output |

### 5. Output Quality

| Aspect | Current State | Recommendation |
|--------|--------------|----------------|
| **Issue** | Lengthy output with unnecessary inference | Build **guardrails** (not limited to "no inference" rules) |
| **Agent Role** | Research agent does inference | Research agent **only does research**, not inference |
| **Inference** | Embedded in research | If inference needed, put in **QA orchestrator** |

### 6. Evaluation

| Aspect | Current State | Recommendation |
|--------|--------------|----------------|
| **Current** | None | Experiment with **OOTB evaluators** first |
| **Custom** | N/A | Suspect need custom evaluators/filters:<br>• Check if agent picks right sources from trusted list |
| **Auditor Approach** | N/A | Less relevant for broad Q&A<br>Focus on **filters and guardrails** for relevance/usefulness<br>Agent self-correction and error checking |

### 7. Model Choice

| Aspect | Current State | Recommendation |
|--------|--------------|----------------|
| **Current** | Limited and outdated model choices | Experiment with additional models:<br>• Reasoning models<br>• Non-reasoning models<br>• **GPT-5** etc. |

### 8. Web Search Agent

| Aspect | Current State | Recommendation |
|--------|--------------|----------------|
| **Current** | Custom search (Bing?) | Experiment with **OpenAI's built-in online search** |
| **Pros** | N/A | Easier maintenance |
| **Consider** | N/A | Cost perspective<br>Other built-in search with chosen model |

### 9. Latency Optimization

| Aspect | Current State | Recommendation |
|--------|--------------|----------------|
| **Current** | ~3 minutes runtime | Options to reduce time:<br>• Experiment with faster models<br>• **Parallel query execution** |
| **UX** | Synchronous wait | Test **deep search mode** - users continue asking while search runs |
| **Caching** | N/A | Cache queries - some questions are deterministic:<br>• One metric goes up/down for a brand<br>• Common "why" patterns |

---

## Implementation Priority

### High Priority
1. **Task Decomposition** - Split single agent into parallel hypothesis validators
2. **Prompt Context** - Add metric definitions and competitor context
3. **Output Guardrails** - Remove inference from research agent
4. **Hypothesis-Based Approach** - Refactor query generation flow

### Medium Priority
5. **Model Experimentation** - Test GPT-5 and reasoning models
6. **Evaluation Framework** - Set up OOTB evaluators, plan custom filters
7. **Web Search Migration** - Evaluate OpenAI built-in search vs. current

### Lower Priority
8. **Latency Optimization** - Parallel execution, caching layer
9. **Deep Search Mode** - UX enhancement for async processing
10. **Prompt Refinement** - CS feedback loop integration

---

## Key Architectural Decisions

### Research Agent Scope
- **DO:** Research, source gathering, validation
- **DON'T:** Inference, conclusion drawing
- **WHERE:** QA Orchestrator handles inference if needed

### Hypothesis Generation
- Generate multiple hypotheses (macro, brand, competitor)
- One agent per hypothesis/query pair (parallel execution)
- Validate against sources, not model reasoning

### Context Strategy
- Preferred: Predefined dictionary of metric definitions
- Fallback: RAG for dynamically loaded context
- Include: Interpretation guide, drivers (up/down), competitor list

---

## Success Metrics

| Metric | Target |
|--------|--------|
| Output relevance | Match golden question set outputs |
| Source quality | Pick from trusted source list |
| Latency | < 1 minute (from 3 minutes) |
| User satisfaction | CS feedback positive |
| No inference violations | 0 in research agent output |
