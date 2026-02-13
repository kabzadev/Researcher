/**
 * Research History Store
 *
 * Persists research questions + full responses to localStorage so users can:
 *   1. Avoid re-running (and re-paying for) the same research
 *   2. Compare how results change over time for the same question
 */

export interface HistoryDriver {
    hypothesis: string
    evidence: string
    source?: string
    url?: string
}

export interface HistoryDrivers {
    macro: HistoryDriver[]
    brand: HistoryDriver[]
    competitive: HistoryDriver[]
}

export interface HistoryEntry {
    /** Unique ID for this entry */
    id: string
    /** The original research question */
    question: string
    /** Normalised question for grouping (lowercase, trimmed) */
    questionKey: string
    /** LLM provider used */
    provider: string
    /** Run ID from the backend */
    runId?: string
    /** ISO timestamp when the research was completed */
    timestamp: string
    /** Latency reported by backend (ms) */
    latencyMs?: number
    /** The brand extracted by the backend */
    brand?: string
    /** Metric direction (e.g. "decrease") */
    direction?: string
    /** Metrics analysed */
    metrics?: string[]
    /** The full assistant message text */
    content: string
    /** Structured driver results */
    drivers?: HistoryDrivers
    /** Coaching payload if the response was a clarification */
    coaching?: any
    /** Thinking/hypothesis validation trace */
    thinking?: string[]
}

const STORAGE_KEY = 'researcher_history_v1'
const MAX_ENTRIES = 200 // keep last N entries

function readAll(): HistoryEntry[] {
    try {
        const raw = localStorage.getItem(STORAGE_KEY)
        if (!raw) return []
        const parsed = JSON.parse(raw)
        return Array.isArray(parsed) ? parsed : []
    } catch {
        return []
    }
}

function writeAll(entries: HistoryEntry[]) {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(-MAX_ENTRIES)))
    } catch {
        // Storage full – drop oldest half
        try {
            const trimmed = entries.slice(-Math.floor(MAX_ENTRIES / 2))
            localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed))
        } catch {
            // give up
        }
    }
}

function normaliseQuestion(q: string): string {
    return q.trim().toLowerCase().replace(/\s+/g, ' ')
}

/** Save a completed research result to history */
export function saveToHistory(entry: Omit<HistoryEntry, 'id' | 'questionKey' | 'timestamp'>): HistoryEntry {
    const full: HistoryEntry = {
        ...entry,
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        questionKey: normaliseQuestion(entry.question),
        timestamp: new Date().toISOString(),
    }

    const all = readAll()
    all.push(full)
    writeAll(all)
    return full
}

/** Get all history entries, newest first */
export function getHistory(): HistoryEntry[] {
    return readAll().slice().reverse()
}

/** Get entries grouped by normalised question, newest group first */
export function getHistoryGrouped(): { questionKey: string; question: string; entries: HistoryEntry[] }[] {
    const all = readAll()
    const map = new Map<string, { question: string; entries: HistoryEntry[] }>()

    for (const entry of all) {
        const existing = map.get(entry.questionKey)
        if (existing) {
            existing.entries.push(entry)
        } else {
            map.set(entry.questionKey, { question: entry.question, entries: [entry] })
        }
    }

    // Sort entries within each group (newest first)
    const groups = Array.from(map.values()).map(g => ({
        questionKey: normaliseQuestion(g.question),
        question: g.question,
        entries: g.entries.slice().reverse(),
    }))

    // Sort groups by most recent entry
    groups.sort((a, b) => {
        const aTime = new Date(a.entries[0].timestamp).getTime()
        const bTime = new Date(b.entries[0].timestamp).getTime()
        return bTime - aTime
    })

    return groups
}

/** Delete a single entry by ID */
export function deleteEntry(id: string) {
    const all = readAll().filter(e => e.id !== id)
    writeAll(all)
}

/** Clear all history */
export function clearHistory() {
    localStorage.removeItem(STORAGE_KEY)
}

/** Count total entries */
export function historyCount(): number {
    return readAll().length
}
