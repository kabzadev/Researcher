import { useState, useMemo } from 'react'
import { Search, Clock, ChevronDown, ChevronRight, Trash2, ExternalLink, Sparkles, AlertTriangle } from 'lucide-react'
import { getHistoryGrouped, deleteEntry, clearHistory } from '../lib/historyStore'

export function History() {
    const [search, setSearch] = useState('')
    const [expandedGroup, setExpandedGroup] = useState<string | null>(null)
    const [expandedEntry, setExpandedEntry] = useState<string | null>(null)
    const [refreshKey, setRefreshKey] = useState(0)

    const groups = useMemo(() => getHistoryGrouped(), [refreshKey])

    const filtered = useMemo(() => {
        if (!search.trim()) return groups
        const q = search.toLowerCase()
        return groups.filter(
            g =>
                g.question.toLowerCase().includes(q) ||
                g.entries.some(e => e.brand?.toLowerCase().includes(q) || e.provider?.toLowerCase().includes(q))
        )
    }, [groups, search])

    const totalEntries = groups.reduce((sum, g) => sum + g.entries.length, 0)

    const handleDeleteEntry = (id: string) => {
        deleteEntry(id)
        setRefreshKey(k => k + 1)
    }

    const handleClearAll = () => {
        if (window.confirm('Clear all research history? This cannot be undone.')) {
            clearHistory()
            setRefreshKey(k => k + 1)
        }
    }

    return (
        <div className="h-full overflow-y-auto p-6 space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-lg font-semibold text-slate-900">Research History</h2>
                    <p className="text-sm text-slate-500 mt-0.5">
                        {totalEntries} {totalEntries === 1 ? 'research run' : 'research runs'} across {groups.length} unique {groups.length === 1 ? 'question' : 'questions'}
                    </p>
                </div>
                {totalEntries > 0 && (
                    <button
                        onClick={handleClearAll}
                        className="px-3 py-2 text-sm rounded-lg border border-rose-200 text-rose-600 bg-white hover:bg-rose-50 flex items-center gap-1.5"
                    >
                        <Trash2 className="w-3.5 h-3.5" />
                        Clear All
                    </button>
                )}
            </div>

            {/* Search */}
            <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input
                    type="text"
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    placeholder="Search questions, brands, providers..."
                    className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-slate-300 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                />
            </div>

            {/* Empty state */}
            {filtered.length === 0 && (
                <div className="bg-white border border-slate-200 rounded-xl p-8 text-center">
                    <Clock className="w-10 h-10 text-slate-300 mx-auto mb-3" />
                    <p className="text-slate-600 font-medium">
                        {totalEntries === 0 ? 'No research history yet' : 'No matching results'}
                    </p>
                    <p className="text-sm text-slate-400 mt-1">
                        {totalEntries === 0
                            ? 'Research results will be saved here automatically when you run queries.'
                            : 'Try a different search term.'}
                    </p>
                </div>
            )}

            {/* Grouped results */}
            <div className="space-y-3">
                {filtered.map(group => {
                    const isGroupOpen = expandedGroup === group.questionKey
                    const latestEntry = group.entries[0]
                    const runCount = group.entries.length

                    return (
                        <div
                            key={group.questionKey}
                            className="bg-white border border-slate-200 rounded-xl overflow-hidden"
                        >
                            {/* Group header */}
                            <button
                                type="button"
                                onClick={() => setExpandedGroup(isGroupOpen ? null : group.questionKey)}
                                className="w-full px-4 py-3.5 flex items-start gap-3 text-left hover:bg-slate-50 transition-colors"
                            >
                                <div className="mt-0.5 flex-shrink-0">
                                    {isGroupOpen ? (
                                        <ChevronDown className="w-4 h-4 text-slate-400" />
                                    ) : (
                                        <ChevronRight className="w-4 h-4 text-slate-400" />
                                    )}
                                </div>
                                <div className="flex-1 min-w-0">
                                    <p className="text-sm font-medium text-slate-900 truncate">{group.question}</p>
                                    <div className="flex items-center gap-3 mt-1">
                                        <span className="text-xs text-slate-400">
                                            {new Date(latestEntry.timestamp).toLocaleDateString(undefined, {
                                                month: 'short',
                                                day: 'numeric',
                                                year: 'numeric',
                                            })}
                                        </span>
                                        {latestEntry.brand && latestEntry.brand !== 'help' && (
                                            <span className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-700">
                                                {latestEntry.brand}
                                            </span>
                                        )}
                                        <span className={`text-xs px-2 py-0.5 rounded-full ${latestEntry.provider === 'anthropic'
                                            ? 'bg-violet-50 text-violet-700'
                                            : 'bg-emerald-50 text-emerald-700'
                                            }`}>
                                            {latestEntry.provider === 'anthropic' ? 'Claude' : 'OpenAI'}
                                        </span>
                                    </div>
                                </div>
                                {runCount > 1 && (
                                    <span className="flex-shrink-0 text-xs px-2.5 py-1 rounded-full bg-amber-50 text-amber-700 border border-amber-200 font-medium">
                                        {runCount} runs
                                    </span>
                                )}
                            </button>

                            {/* Expanded group */}
                            {isGroupOpen && (
                                <div className="border-t border-slate-100">
                                    {group.entries.map((entry, idx) => {
                                        const isEntryOpen = expandedEntry === entry.id
                                        return (
                                            <div key={entry.id} className={idx > 0 ? 'border-t border-slate-100' : ''}>
                                                {/* Entry header row */}
                                                <div className="flex items-center gap-2 px-4 py-2.5 bg-slate-50/50">
                                                    <button
                                                        type="button"
                                                        onClick={() => setExpandedEntry(isEntryOpen ? null : entry.id)}
                                                        className="flex items-center gap-2 flex-1 min-w-0 text-left"
                                                    >
                                                        {isEntryOpen ? (
                                                            <ChevronDown className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
                                                        ) : (
                                                            <ChevronRight className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
                                                        )}
                                                        <span className="text-xs text-slate-500 whitespace-nowrap">
                                                            {new Date(entry.timestamp).toLocaleString()}
                                                        </span>
                                                        <span className={`text-xs px-1.5 py-0.5 rounded ${entry.provider === 'anthropic'
                                                            ? 'bg-violet-100 text-violet-700'
                                                            : 'bg-emerald-100 text-emerald-700'
                                                            }`}>
                                                            {entry.provider === 'anthropic' ? 'Claude' : 'GPT'}
                                                        </span>
                                                        {entry.latencyMs != null && (
                                                            <span className="text-xs text-slate-400">{(entry.latencyMs / 1000).toFixed(1)}s</span>
                                                        )}
                                                    </button>
                                                    <button
                                                        type="button"
                                                        onClick={() => handleDeleteEntry(entry.id)}
                                                        className="p-1 text-slate-400 hover:text-rose-500 rounded"
                                                        title="Delete this run"
                                                    >
                                                        <Trash2 className="w-3.5 h-3.5" />
                                                    </button>
                                                </div>

                                                {/* Expanded entry detail */}
                                                {isEntryOpen && (
                                                    <div className="px-6 py-4 space-y-4">
                                                        {/* Coaching response */}
                                                        {entry.coaching && (
                                                            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
                                                                <div className="flex items-center gap-1.5 font-medium mb-1">
                                                                    <AlertTriangle className="w-4 h-4" />
                                                                    Clarification needed
                                                                </div>
                                                                <p className="whitespace-pre-wrap">{entry.coaching.message || entry.content}</p>
                                                                {entry.coaching.suggested_questions?.length > 0 && (
                                                                    <div className="mt-2">
                                                                        <p className="text-xs font-medium text-amber-700 mb-1">Suggested questions:</p>
                                                                        <ul className="list-disc list-inside text-xs space-y-0.5">
                                                                            {entry.coaching.suggested_questions.map((sq: string, i: number) => (
                                                                                <li key={i}>{sq}</li>
                                                                            ))}
                                                                        </ul>
                                                                    </div>
                                                                )}
                                                            </div>
                                                        )}

                                                        {/* Main content */}
                                                        {!entry.coaching && (
                                                            <div className="text-sm text-slate-700 whitespace-pre-wrap">{entry.content}</div>
                                                        )}

                                                        {/* Thinking trace */}
                                                        {entry.thinking && entry.thinking.length > 0 && (
                                                            <details className="group">
                                                                <summary className="cursor-pointer text-xs text-slate-500 flex items-center gap-1.5">
                                                                    <Sparkles className="w-3.5 h-3.5" />
                                                                    Hypotheses validated ({entry.thinking.length})
                                                                </summary>
                                                                <div className="mt-2 p-3 bg-slate-50 rounded-lg text-xs text-slate-600 space-y-1">
                                                                    {entry.thinking.map((t, i) => (
                                                                        <div key={i}>{t}</div>
                                                                    ))}
                                                                </div>
                                                            </details>
                                                        )}

                                                        {/* Drivers */}
                                                        {entry.drivers && (
                                                            <div className="space-y-3">
                                                                <DriverBlock
                                                                    title="🌍 Market / Macro"
                                                                    drivers={entry.drivers.macro}
                                                                    color="blue"
                                                                />
                                                                <DriverBlock
                                                                    title="🏷️ Brand"
                                                                    drivers={entry.drivers.brand}
                                                                    color="green"
                                                                />
                                                                <DriverBlock
                                                                    title="⚔️ Competitive"
                                                                    drivers={entry.drivers.competitive}
                                                                    color="amber"
                                                                />
                                                            </div>
                                                        )}

                                                        {/* Meta */}
                                                        <div className="flex flex-wrap gap-3 text-[11px] text-slate-400 pt-2 border-t border-slate-100">
                                                            {entry.runId && <span>Run: {entry.runId.slice(0, 8)}</span>}
                                                            {entry.brand && <span>Brand: {entry.brand}</span>}
                                                            {entry.direction && <span>Direction: {entry.direction}</span>}
                                                            {entry.metrics?.length ? <span>Metrics: {entry.metrics.join(', ')}</span> : null}
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        )
                                    })}
                                </div>
                            )}
                        </div>
                    )
                })}
            </div>

            <p className="text-xs text-slate-500">
                History is stored in your browser's local storage. It persists across sessions but is specific to this device/browser.
            </p>
        </div>
    )
}

function DriverBlock({
    title,
    drivers,
    color,
}: {
    title: string
    drivers: { hypothesis: string; evidence: string; source?: string; url?: string }[]
    color: 'blue' | 'green' | 'amber'
}) {
    if (!drivers || drivers.length === 0) return null

    const borderColors = {
        blue: 'border-blue-500 text-blue-700',
        green: 'border-emerald-500 text-emerald-700',
        amber: 'border-amber-500 text-amber-700',
    }

    return (
        <div>
            <h4 className={`text-xs font-semibold border-b pb-1.5 mb-2 ${borderColors[color]}`}>{title}</h4>
            <div className="space-y-2">
                {drivers.map((d, i) => (
                    <div key={i} className="pl-3 border-l-2 border-slate-200 text-sm">
                        <p className="font-medium text-slate-800">• {d.hypothesis}</p>
                        <p className="text-slate-600 mt-0.5 ml-4">
                            → {d.evidence}
                            {d.url && (
                                <a
                                    href={d.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="inline-flex items-center gap-0.5 ml-1.5 text-primary hover:underline text-xs"
                                >
                                    [{d.source || 'Source'}]
                                    <ExternalLink className="w-3 h-3" />
                                </a>
                            )}
                        </p>
                    </div>
                ))}
            </div>
        </div>
    )
}
