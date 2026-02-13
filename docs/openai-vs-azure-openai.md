# Public OpenAI vs Azure OpenAI — Comparison Guide

> **Context**: This document captures the differences discovered while deploying the KAIA Researcher application to both platforms. It includes general platform comparisons and specific technical differences that affect our codebase.

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Authentication](#authentication)
3. [API Compatibility — The Responses API](#api-compatibility--the-responses-api)
4. [Web Search Tool Differences](#web-search-tool-differences)
5. [Citation / Source Extraction](#citation--source-extraction)
6. [Performance & Latency](#performance--latency)
7. [Rate Limits & Throughput](#rate-limits--throughput)
8. [Pricing Comparison](#pricing-comparison)
9. [Model Availability](#model-availability)
10. [Enterprise & Compliance](#enterprise--compliance)
11. [SDK & Client Library Usage](#sdk--client-library-usage)
12. [KAIA Researcher — Code Differences](#kaia-researcher--code-differences)
13. [Deployment Checklist](#deployment-checklist)

---

## Executive Summary

| Dimension | Public OpenAI API | Azure OpenAI |
|---|---|---|
| **Endpoint** | `api.openai.com` | `<resource>.openai.azure.com` |
| **Auth** | API key (bearer token) | API key **or** Entra ID (Managed Identity) |
| **Model freshness** | Day-0 access | Weeks to months lag |
| **Responses API** | ✅ GA (Aug 2025) | ✅ GA (Aug 2025), some tool differences |
| **Web Search** | `web_search` tool | `web_search_preview` tool (Bing grounding) |
| **Citation format** | `action.sources` on `web_search_call` | `url_citation` annotations on message |
| **SLA** | Best-effort | 99.9% uptime SLA |
| **Data residency** | US/global | Choose region (EU, US, etc.) |
| **Content filtering** | Moderate | Configurable (can be stricter) |
| **Compliance** | SOC 2, GDPR | SOC 2, HIPAA, ISO 27001, FedRAMP, GDPR |

---

## Authentication

### Public OpenAI

```python
from openai import OpenAI
client = OpenAI(api_key="sk-...")
```

Simple API key auth. Keys are managed in the OpenAI dashboard.

### Azure OpenAI

Azure supports **two** authentication methods:

#### Option A: API Key
```python
from openai import AzureOpenAI
client = AzureOpenAI(
    api_key="<key>",
    azure_endpoint="https://<resource>.openai.azure.com",
    api_version="2025-04-01-preview",
)
```

> ⚠️ **Important**: Many enterprise Azure subscriptions have policies that **enforce `disableLocalAuth=true`**, blocking key-based auth entirely. This is common in MCAPS and regulated tenants.

#### Option B: Managed Identity (Recommended for Azure)
```python
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

credential = DefaultAzureCredential()
token_provider = get_bearer_token_provider(
    credential, "https://cognitiveservices.azure.com/.default"
)

client = AzureOpenAI(
    azure_ad_token_provider=token_provider,
    azure_endpoint="https://<resource>.openai.azure.com",
    api_version="2025-04-01-preview",
)
```

**Prerequisites for Managed Identity:**
1. Container App (or App Service, VM, etc.) must have a **system-assigned managed identity** enabled
2. The identity must be granted the **`Cognitive Services OpenAI User`** role on the Azure OpenAI resource
3. `azure-identity` package must be installed (`pip install azure-identity>=1.15.0`)

---

## API Compatibility — The Responses API

Both platforms support the OpenAI **Responses API** (as of August 2025), but with key differences:

| Feature | Public OpenAI | Azure OpenAI |
|---|---|---|
| `client.responses.create()` | ✅ | ✅ |
| `api_version` parameter | Not required | **Required** — use `2025-04-01-preview` or later |
| `web_search` tool | ✅ `{"type": "web_search"}` | ❌ Not supported |
| `web_search_preview` tool | ❌ Not recognized | ✅ `{"type": "web_search_preview"}` |
| `include` param for sources | Returns sources in `action.sources` | Sources returned as `url_citation` annotations |
| Chat Completions API | ✅ `client.chat.completions.create()` | ✅ Same interface |
| Model parameter | Model name (e.g., `gpt-4o`) | **Deployment name** (must match your deployment) |

### API Version (Azure Only)

Azure requires an explicit `api_version`. For the Responses API with web search:

```
2025-04-01-preview  ← Minimum for web_search_preview
2024-10-21          ← Chat Completions only (no Responses API)
```

---

## Web Search Tool Differences

This is the most impactful difference for the KAIA Researcher.

### Public OpenAI — `web_search`

```python
resp = client.responses.create(
    model="gpt-4o",
    tools=[{"type": "web_search"}],
    tool_choice="auto",
    include=["web_search_call.action.sources"],
    input="Nike brand news UK 2024",
)
```

- Uses OpenAI's native search infrastructure
- Sources returned in `output[0].action.sources[]`
- Each source has: `url`, `title`, `snippet`
- Generally faster (single-hop)

### Azure OpenAI — `web_search_preview`

```python
resp = client.responses.create(
    model="gpt-4o",                           # Must match deployment name
    tools=[{"type": "web_search_preview"}],   # Different tool type!
    tool_choice="auto",
    include=["web_search_call.action.sources"],
    input="Nike brand news UK 2024",
)
```

- Uses **Bing Search** grounding under the hood
- `action.sources` is **empty** (returns `[]`)
- Sources returned as `url_citation` **annotations** on the message content
- Requires subscription-level feature enablement (see below)

### Enabling Web Search on Azure

Web search is blocked by default. You must unblock it per-subscription:

```bash
# Unblock the web_search tool
az feature unregister \
  --name OpenAI.BlockedTools.web_search \
  --namespace Microsoft.CognitiveServices \
  --subscription "<subscription-id>"

# Propagate the change
az provider register -n Microsoft.CognitiveServices
```

---

## Citation / Source Extraction

This is the critical API response difference that affects how we extract references.

### Public OpenAI Response Structure

```json
{
  "output": [
    {
      "type": "web_search_call",
      "action": {
        "type": "search",
        "sources": [
          {
            "url": "https://example.com/article",
            "title": "Article Title",
            "snippet": "Relevant content..."
          }
        ]
      }
    },
    {
      "type": "message",
      "content": [
        {
          "type": "output_text",
          "text": "Based on my research..."
        }
      ]
    }
  ]
}
```

### Azure OpenAI Response Structure

```json
{
  "output": [
    {
      "type": "web_search_call",
      "action": {
        "type": "search",
        "queries": ["Nike brand UK 2024"],
        "sources": null
      }
    },
    {
      "type": "message",
      "content": [
        {
          "type": "output_text",
          "text": "Nike has faced challenges in the UK [Source](https://example.com)...",
          "annotations": [
            {
              "type": "url_citation",
              "start_index": 40,
              "end_index": 95,
              "url": "https://example.com/article",
              "title": "Article Title"
            }
          ]
        }
      ]
    }
  ]
}
```

### Cross-Compatible Extraction Code

```python
sources = []
message_text = ""

for item in response.get("output", []):
    if item["type"] == "web_search_call":
        # Standard OpenAI: sources in action
        for s in (item.get("action", {}).get("sources") or []):
            sources.append({"title": s["title"], "url": s["url"]})

    elif item["type"] == "message":
        for c in item.get("content", []):
            if c.get("text"):
                message_text = c["text"]
            # Azure OpenAI: sources in annotations
            for annot in (c.get("annotations") or []):
                if annot["type"] == "url_citation":
                    sources.append({"title": annot["title"], "url": annot["url"]})
```

---

## Performance & Latency

| Factor | Public OpenAI | Azure OpenAI |
|---|---|---|
| First-call latency | ~200ms | ~500-1500ms (Managed Identity token acquisition) |
| Subsequent call latency | ~500-800ms | ~600-1000ms |
| Web search overhead | ~1-2s (native search) | ~2-5s (Bing grounding, additional hop) |
| Cold start | N/A (multi-tenant) | Possible if Container App scales to 0 |
| Token acquisition | Instant (API key) | Token caching after first call |

### Why Azure Feels Slower for KAIA Researcher

The research pipeline makes **12+ API calls** per query:
1. **1 call** — Parse the question (extract brand, metrics, direction)
2. **1 call** — Generate hypotheses (market, brand, competitive)
3. **12 calls** — Validate each hypothesis with web search (4 per category × 3 categories)
4. **1 call** — Generate final summary

With Azure's per-call overhead of ~1-3s:
- **Public OpenAI total**: ~20-30 seconds
- **Azure OpenAI total**: ~40-60 seconds

### Mitigation Strategies

1. **Increase TPM capacity** — Deploy with 80K+ TPM instead of 30K
2. **Reduce hypotheses** — Use `max_hypotheses_per_category: 3` (9 total vs 12)
3. **Provisioned Throughput (PTU)** — Pre-allocate capacity for consistent latency
4. **Regional selection** — Deploy Azure OpenAI in the same region as the Container App

---

## Rate Limits & Throughput

### Public OpenAI

| Tier | RPM (Requests/min) | TPM (Tokens/min) |
|---|---|---|
| Tier 1 (free) | 500 | 30,000 |
| Tier 2 | 5,000 | 450,000 |
| Tier 3 | 5,000 | 800,000 |
| Tier 5 | 10,000 | 10,000,000 |

### Azure OpenAI

| SKU | Default TPM | Max TPM |
|---|---|---|
| Standard (S0) | 30,000 | 240,000+ |
| Provisioned (PTU) | Dedicated capacity | Based on PTU count |

**Key difference**: Azure TPM is set **per deployment**, not per account. If a research query uses ~84K tokens across 15 calls, a 30K TPM deployment will throttle (429 errors).

---

## Pricing Comparison (GPT-4o, Feb 2026)

| | Public OpenAI | Azure OpenAI |
|---|---|---|
| **Input** (per 1M tokens) | $2.50 | $5.00 |
| **Output** (per 1M tokens) | $10.00 | $15.00 |
| **Web search** | Included in token cost | Included (Bing grounding) |
| **SLA** | None | 99.9% |
| **Data residency** | No guarantee | Choose region |

> **Note**: Azure OpenAI is more expensive per-token but includes enterprise features (SLA, compliance, VNet integration, Managed Identity). For regulated industries this is typically worth the premium.

### GPT-4o Mini

| | Public OpenAI | Azure OpenAI |
|---|---|---|
| **Input** (per 1M tokens) | $0.15 | $0.15 |
| **Output** (per 1M tokens) | $0.60 | $0.60 |

---

## Model Availability

| Model | Public OpenAI | Azure OpenAI | Lag |
|---|---|---|---|
| GPT-4o | ✅ | ✅ | Same day |
| GPT-4o Mini | ✅ | ✅ | Same day |
| GPT-5 | ✅ (Sep 2025) | ✅ (Sep 2025) | ~2 weeks |
| GPT-5 Mini | ✅ | ✅ | ~2 weeks |
| o1 / o1-mini (reasoning) | ✅ | ✅ | ~4 weeks |
| GPT-image-1 | ✅ | ✅ (Apr 2025) | ~2 months |
| Realtime (audio) | ✅ | ✅ | ~4 weeks |
| Fine-tuned models | ✅ | ✅ | Limited availability |

---

## Enterprise & Compliance

| Feature | Public OpenAI | Azure OpenAI |
|---|---|---|
| SOC 2 | ✅ | ✅ |
| HIPAA | ❌ | ✅ (with BAA) |
| ISO 27001 | ❌ | ✅ |
| FedRAMP | ❌ | ✅ (Gov regions) |
| GDPR | ✅ | ✅ |
| VNet / Private Endpoint | ❌ | ✅ |
| Content Safety filtering | Basic | Configurable |
| Data retention | 30 days (opt-out available) | 0 days (no data stored) |
| Managed Identity | ❌ | ✅ |
| Azure Policy integration | N/A | ✅ |
| SLA | Best effort | 99.9% |

---

## SDK & Client Library Usage

Both platforms use the same `openai` Python package, but initialization differs:

### Public OpenAI
```python
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}],
)
```

### Azure OpenAI
```python
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

credential = DefaultAzureCredential()
token_provider = get_bearer_token_provider(
    credential, "https://cognitiveservices.azure.com/.default"
)

client = AzureOpenAI(
    azure_ad_token_provider=token_provider,
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version="2025-04-01-preview",
)

# model parameter = deployment name (not model name)
response = client.chat.completions.create(
    model="gpt-4o",  # This must match your Azure deployment name
    messages=[{"role": "user", "content": "Hello"}],
)
```

### Key SDK Differences

| | Public OpenAI | Azure OpenAI |
|---|---|---|
| Package | `openai` | `openai` + `azure-identity` |
| Client class | `OpenAI` | `AzureOpenAI` |
| Auth parameter | `api_key` | `api_key` or `azure_ad_token_provider` |
| `api_version` | Not used | **Required** |
| `model` param | Model name | Deployment name (must match exactly) |
| Base URL | Auto (`api.openai.com`) | Must provide `azure_endpoint` |

---

## KAIA Researcher — Code Differences

The KAIA Researcher backend (`backend/main.py`) handles both platforms with these key adaptations:

### Branch Structure
- **`main`** — Public OpenAI + Anthropic Claude + Tavily search
- **`feature/azure-deployment`** — Azure OpenAI + Managed Identity + Bing web search

### Code Changes Made for Azure

| Area | Public OpenAI (main) | Azure OpenAI (feature/azure-deployment) |
|---|---|---|
| Client init | `OpenAI(api_key=...)` | `AzureOpenAI(azure_ad_token_provider=...)` |
| Dependencies | `openai` | `openai` + `azure-identity` |
| Search tool | `{"type": "web_search"}` | `{"type": "web_search_preview"}` |
| Source extraction | `action.sources[]` | `annotations[].url_citation` |
| API version | Not set | `2025-04-01-preview` |
| Environment vars | `OPENAI_API_KEY` | `AZURE_OPENAI_ENDPOINT` (no API key needed) |

### Auto-Detection in Code

The backend auto-detects which platform to use:

```python
_is_azure = bool(os.getenv("AZURE_OPENAI_ENDPOINT"))

# Tool type selection
search_tool_type = "web_search_preview" if _is_azure else "web_search"

# Client initialization
if _is_azure:
    # Uses DefaultAzureCredential (Managed Identity)
    client = AzureOpenAI(azure_ad_token_provider=token_provider, ...)
else:
    # Uses API key
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
```

---

## Deployment Checklist

### For Azure OpenAI Deployment

- [ ] Create Azure OpenAI resource with custom subdomain
- [ ] Deploy model (e.g., `gpt-4o`) with sufficient TPM (80K+ recommended)
- [ ] Enable system-assigned Managed Identity on Container App
- [ ] Assign `Cognitive Services OpenAI User` role to Container App identity
- [ ] Unblock `web_search` feature at subscription level
- [ ] Set `AZURE_OPENAI_ENDPOINT` environment variable
- [ ] Set `AZURE_OPENAI_API_VERSION=2025-04-01-preview`
- [ ] Install `azure-identity>=1.15.0` in requirements.txt
- [ ] Use `web_search_preview` tool type (not `web_search`)
- [ ] Extract citations from both `action.sources` and `annotations`

### For Public OpenAI Deployment

- [ ] Get API key from platform.openai.com
- [ ] Set `OPENAI_API_KEY` environment variable
- [ ] Optionally set `TAVILY_API_KEY` for Tavily-based search
- [ ] Use `web_search` tool type
- [ ] Extract citations from `action.sources`

---

*Last updated: February 13, 2026*
*Based on KAIA Researcher deployment experience to MCAPS-Hybrid subscription*
