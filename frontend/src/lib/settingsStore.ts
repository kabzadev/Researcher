/**
 * Settings Store
 *
 * Persists user-configurable settings to localStorage:
 *   - System prompt (sent to every LLM call)
 *   - Max hypotheses per category (controls depth of research)
 */

export interface AppSettings {
    systemPrompt: string
    maxHypothesesPerCategory: number
    hypothesisPrompt: string
    activePromptTab: 'system' | 'hypothesis'
    minVerifiedSourcePct: number
}

const STORAGE_KEY = 'researcher_settings_v1'

const DEFAULT_SYSTEM_PROMPT = `You are a research analyst specialising in brand tracking and consumer sentiment analysis.

Your role:
- Analyse why brand metrics (especially Salience / mental availability) change over time.
- Generate hypotheses about market, brand-specific, and competitive factors.
- Validate hypotheses with web evidence and provide cited sources.

Guidelines:
- Be specific: reference real events, campaigns, product launches, market shifts.
- Be evidence-based: only report findings backed by credible web sources.
- Be concise: use bullet points and structured output.
- Tailor your analysis to the brand's specific industry and market context.
- Always include the time period in search queries to get relevant results.`

const DEFAULT_HYPOTHESIS_PROMPT = `When generating hypotheses, follow these rules:

INDUSTRY CONTEXT:
- First determine the brand's industry (e.g. automotive, fashion, technology, FMCG).
- ALL hypotheses must be relevant to the brand's actual industry.
- Do NOT include trends, competitors, or events from unrelated industries.

MARKET HYPOTHESES (macro trends):
- Economic conditions: consumer spending, inflation, interest rates, currency shifts.
- Industry-specific disruptions: regulation, technology shifts, supply chain events.
- Consumer behaviour changes: purchasing patterns, demographics, sentiment.
- Political, trade, or environmental factors affecting the brand's sector.

BRAND HYPOTHESES (brand's own actions):
- Each must reference a SPECIFIC action, person, product, campaign, or event.
- Include: product launches/recalls, leadership changes, PR events, controversies.
- Include: store/facility openings or closures, pricing changes, strategy shifts.
- Avoid generic statements like "brand improved marketing" — name the campaign.

COMPETITIVE HYPOTHESES:
- Each must name a SPECIFIC competitor from the brand's actual industry.
- Competitors must operate in the SAME market — never cross-industry.
- Include specific actions: campaigns, product launches, pricing moves, expansions.
- Each hypothesis should focus on a DIFFERENT competitor.

SEARCH QUERIES:
- search_query: specific and targeted (include brand/competitor name + time period).
- search_query_broad: broader fallback (include brand/competitor name + time period).

QUALITY CHECK:
- Before finalising, review each hypothesis for relevance to the brand and its industry.
- Remove anything that a domain expert would consider irrelevant or nonsensical.`

export const DEFAULT_SETTINGS: AppSettings = {
    systemPrompt: DEFAULT_SYSTEM_PROMPT,
    maxHypothesesPerCategory: 4,
    hypothesisPrompt: DEFAULT_HYPOTHESIS_PROMPT,
    activePromptTab: 'system',
    minVerifiedSourcePct: 25,
}

export function loadSettings(): AppSettings {
    try {
        const raw = localStorage.getItem(STORAGE_KEY)
        if (!raw) return { ...DEFAULT_SETTINGS }
        const parsed = JSON.parse(raw)
        return {
            systemPrompt: typeof parsed.systemPrompt === 'string' ? parsed.systemPrompt : DEFAULT_SETTINGS.systemPrompt,
            maxHypothesesPerCategory:
                typeof parsed.maxHypothesesPerCategory === 'number' &&
                    parsed.maxHypothesesPerCategory >= 1 &&
                    parsed.maxHypothesesPerCategory <= 10
                    ? parsed.maxHypothesesPerCategory
                    : DEFAULT_SETTINGS.maxHypothesesPerCategory,
            hypothesisPrompt: typeof parsed.hypothesisPrompt === 'string' ? parsed.hypothesisPrompt : '',
            activePromptTab: parsed.activePromptTab === 'hypothesis' ? 'hypothesis' : 'system',
            minVerifiedSourcePct:
                typeof parsed.minVerifiedSourcePct === 'number' &&
                    parsed.minVerifiedSourcePct >= 0 &&
                    parsed.minVerifiedSourcePct <= 100
                    ? parsed.minVerifiedSourcePct
                    : DEFAULT_SETTINGS.minVerifiedSourcePct,
        }
    } catch {
        return { ...DEFAULT_SETTINGS }
    }
}

export function saveSettings(settings: AppSettings) {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
    } catch {
        // ignore
    }
}

export function resetSettings() {
    localStorage.removeItem(STORAGE_KEY)
}
