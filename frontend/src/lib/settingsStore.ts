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
}

const STORAGE_KEY = 'researcher_settings_v1'

const DEFAULT_SYSTEM_PROMPT = `You are a research analyst specialising in brand tracking and consumer sentiment analysis.

Your role:
- Analyse why brand metrics (especially Salience / mental availability) change over time.
- Generate hypotheses about market, brand-specific, and competitive factors.
- Validate hypotheses with web evidence and provide cited sources.

Guidelines:
- Be specific: reference real events, campaigns, store openings/closings, market shifts.
- Be evidence-based: only report findings backed by credible web sources.
- Be concise: use bullet points and structured output.
- Focus on UK fashion retail unless otherwise specified.
- Always include the time period in search queries to get relevant results.`

export const DEFAULT_SETTINGS: AppSettings = {
    systemPrompt: DEFAULT_SYSTEM_PROMPT,
    maxHypothesesPerCategory: 4,
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
