# Researcher

AI-powered research assistant for business metrics analysis and hypothesis validation through parallel web search.

---

## Overview

Researcher is an intelligent research system that automatically investigates business questions by extracting metadata, generating hypotheses across multiple dimensions (macro, brand, competitor), and validating them through parallel web searches.

---

## Stakeholder Feedback

> **Jen & Will's Reaction:** "We presented the result to them today, and they think this is exactly what we need and this is super useful."

---

## Requirements

- **OpenAI API Key** - Required for model inference

---

## Approach

This approach differs from Microsoft's methodology (which was found to not work effectively).

### Workflow

```
┌─────────────────┐
│ User Question   │
└────────┬────────┘
         ▼
┌─────────────────────────┐
│ Extract Question        │
│ Metadata                │
│                         │
│ • Target brand          │
│ • Metric                │
│ • Metric direction      │
│   (increase/decrease)   │
│ • Time period           │
│   (e.g., Q3 2025)       │
└────────┬────────────────┘
         ▼
┌─────────────────────────┐
│ Generate Hypotheses     │
│                         │
│ • Macro factors         │
│ • Brand factors         │
│ • Competitor factors    │
│                         │
│ Example: "Online        │
│ shopping reduced        │
│ high-street store       │
│ visits"                 │
└────────┬────────────────┘
         ▼
┌─────────────────────────┐
│ For Each Hypothesis:    │
│ Parallel Execution      │
│                         │
│ ┌─────────────┐ ┌─────┐ │
│ │ Query Gen   │ │ ... │ │
│ │ Web Search  │ │     │ │
│ │ Validate    │ │     │ │
│ └─────────────┘ └─────┘ │
└────────┬────────────────┘
         ▼
┌─────────────────────────┐
│ Summarize Validated     │
│ Hypotheses              │
└────────┬────────────────┘
         ▼
┌─────────────────────────┐
│ Output Final Results    │
└─────────────────────────┘
```

### Hypothesis Validation Pipeline

For each generated hypothesis, the system:

1. **Query Generation** - Creates targeted web search queries geared towards validating or invalidating the hypothesis
   - Example: *"online shopping trend and impact on high street brand in UK 2025"*

2. **Web Search** - Executes searches across multiple sources

3. **Validation** - Analyzes results to validate or invalidate the hypothesis

4. **Summary Generation** *(for validated hypotheses only)* - Creates a concise summary of sources that support the hypothesis

5. **Result Combination** - Aggregates summaries from all validated hypotheses

6. **Final Output** - Presents comprehensive research findings

---

## Experiment Results

### Screenshot

![Experiment Result](docs/experiment-result.png)

*Screenshot of the experiment showing the system in action*

### Current Limitations

⚠️ **Important:** The only accepted question is the one tested in the screenshot. This is due to context being added manually during the experimental phase.

---

## Project Structure

```
Researcher/
├── README.md
├── docs/
│   └── experiment-result.png
├── notebook/
│   └── experiment.ipynb
├── src/
│   └── (implementation files)
└── requirements.txt
```

---

## Usage

```bash
# Set up environment
export OPENAI_API_KEY="your-key-here"

# Run experiment
python src/researcher.py
```

---

## Roadmap

- [ ] Expand context handling beyond manual input
- [ ] Support arbitrary business questions
- [ ] Add more data sources beyond web search
- [ ] Implement confidence scoring for hypotheses
- [ ] Add visualization for hypothesis networks

---

## Notes

- The Microsoft approach was evaluated but found unsuitable for this use case
- Parallel hypothesis validation significantly improves research coverage
- Focus is on actionable insights for business metrics analysis
