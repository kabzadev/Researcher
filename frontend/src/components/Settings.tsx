import { useState, useEffect, useRef } from 'react'
import { Save, RotateCcw, Info, Trash2, AlertTriangle, Shield, Plus, X, RefreshCw } from 'lucide-react'
import { loadSettings, saveSettings, resetSettings, DEFAULT_SETTINGS, type AppSettings } from '../lib/settingsStore'

interface TrustedSource {
    domain: string
    name: string
    trust_score: number
    tier: string
}

const API_URL = 'https://kaia-researcher-api.icyglacier-f068d1b2.eastus.azurecontainerapps.io'

export function Settings() {
    const [settings, setSettings] = useState<AppSettings>(() => loadSettings())
    const [saved, setSaved] = useState(false)
    const [dirty, setDirty] = useState(false)
    const [confirmingClear, setConfirmingClear] = useState(false)
    const clearTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

    // Trusted sources state
    const [trustedSources, setTrustedSources] = useState<TrustedSource[]>([])
    const [sourcesLoading, setSourcesLoading] = useState(true)
    const [sourcesDirty, setSourcesDirty] = useState(false)
    const [sourcesSaved, setSourcesSaved] = useState(false)
    const [newSource, setNewSource] = useState({ domain: '', name: '', trust_score: 7 })
    const [showAddSource, setShowAddSource] = useState(false)

    // Load settings from server on mount (merge with local)
    useEffect(() => {
        const fetchConfig = async () => {
            try {
                const appPassword = sessionStorage.getItem('researcher_app_password') || ''
                const res = await fetch(`${API_URL}/config`, {
                    headers: { 'Authorization': `Bearer ${appPassword}` }
                })
                if (res.ok) {
                    const serverConfig = await res.json()
                    const local = loadSettings()
                    // Server config takes precedence for prompts
                    const merged: AppSettings = {
                        ...local,
                        systemPrompt: serverConfig.systemPrompt ?? local.systemPrompt,
                        hypothesisPrompt: serverConfig.hypothesisPrompt ?? local.hypothesisPrompt,
                        maxHypothesesPerCategory: serverConfig.maxHypothesesPerCategory ?? local.maxHypothesesPerCategory,
                        minVerifiedSourcePct: serverConfig.minVerifiedSourcePct ?? local.minVerifiedSourcePct,
                        activePromptTab: local.activePromptTab, // UI-only, keep local
                    }
                    setSettings(merged)
                    saveSettings(merged) // sync local
                }
            } catch (e) {
                console.error('Failed to load server config:', e)
                setSettings(loadSettings())
            }
        }
        fetchConfig()
    }, [])

    // Load trusted sources from backend
    useEffect(() => {
        fetchSources()
    }, [])

    const fetchSources = async () => {
        setSourcesLoading(true)
        try {
            const appPassword = sessionStorage.getItem('researcher_app_password') || ''
            const res = await fetch(`${API_URL}/sources`, {
                headers: { 'Authorization': `Bearer ${appPassword}` }
            })
            if (res.ok) {
                const data = await res.json()
                setTrustedSources(data.trusted_sources || [])
            }
        } catch (e) {
            console.error('Failed to load sources:', e)
        } finally {
            setSourcesLoading(false)
        }
    }

    // Auto-cancel the clear confirmation after 5 seconds
    useEffect(() => {
        if (confirmingClear) {
            clearTimerRef.current = setTimeout(() => setConfirmingClear(false), 5000)
            return () => { if (clearTimerRef.current) clearTimeout(clearTimerRef.current) }
        }
    }, [confirmingClear])

    const handleChange = (patch: Partial<AppSettings>) => {
        setSettings(prev => ({ ...prev, ...patch }))
        setDirty(true)
        setSaved(false)
    }

    const handleSave = async () => {
        // Save locally
        saveSettings(settings)
        // Save to server
        try {
            const appPassword = sessionStorage.getItem('researcher_app_password') || ''
            await fetch(`${API_URL}/config`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${appPassword}`
                },
                body: JSON.stringify({
                    systemPrompt: settings.systemPrompt,
                    hypothesisPrompt: settings.hypothesisPrompt,
                    maxHypothesesPerCategory: settings.maxHypothesesPerCategory,
                    minVerifiedSourcePct: settings.minVerifiedSourcePct,
                })
            })
        } catch (e) {
            console.error('Failed to save server config:', e)
        }
        setSaved(true)
        setDirty(false)
        setTimeout(() => setSaved(false), 2500)
    }

    const handleReset = () => {
        resetSettings()
        setSettings({ ...DEFAULT_SETTINGS })
        setDirty(false)
        setSaved(false)
    }

    const handleClearAll = () => {
        if (!confirmingClear) {
            setConfirmingClear(true)
            return
        }
        sessionStorage.clear()
        localStorage.removeItem('researcher_history_v1')
        localStorage.removeItem('researcher_settings_v1')
        window.location.replace(window.location.origin)
    }

    // Trusted sources handlers
    const handleSaveSources = async () => {
        try {
            const appPassword = sessionStorage.getItem('researcher_app_password') || ''
            const res = await fetch(`${API_URL}/sources`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${appPassword}`
                },
                body: JSON.stringify({ trusted_sources: trustedSources })
            })
            if (res.ok) {
                setSourcesSaved(true)
                setSourcesDirty(false)
                setTimeout(() => setSourcesSaved(false), 2500)
            }
        } catch (e) {
            console.error('Failed to save sources:', e)
        }
    }

    const handleResetSources = async () => {
        try {
            const appPassword = sessionStorage.getItem('researcher_app_password') || ''
            await fetch(`${API_URL}/sources/reset`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${appPassword}` }
            })
            await fetchSources()
            setSourcesDirty(false)
        } catch (e) {
            console.error('Failed to reset sources:', e)
        }
    }

    const handleAddSource = () => {
        if (!newSource.domain.trim()) return
        setTrustedSources(prev => [...prev, {
            domain: newSource.domain.trim().toLowerCase(),
            name: newSource.name.trim() || newSource.domain.trim(),
            trust_score: newSource.trust_score,
            tier: newSource.trust_score >= 9 ? 'trusted' : newSource.trust_score >= 7 ? 'reputable' : 'custom',
        }])
        setNewSource({ domain: '', name: '', trust_score: 7 })
        setShowAddSource(false)
        setSourcesDirty(true)
    }

    const handleRemoveSource = (idx: number) => {
        setTrustedSources(prev => prev.filter((_, i) => i !== idx))
        setSourcesDirty(true)
    }

    const handleSourceScoreChange = (idx: number, score: number) => {
        setTrustedSources(prev => prev.map((s, i) => {
            if (i !== idx) return s
            return {
                ...s,
                trust_score: score,
                tier: score >= 9 ? 'trusted' : score >= 7 ? 'reputable' : 'custom',
            }
        }))
        setSourcesDirty(true)
    }

    const hypothesisTotal = settings.maxHypothesesPerCategory * 3

    // Group sources by tier for display
    const trustedTier = trustedSources.filter(s => s.tier === 'trusted')
    const reputableTier = trustedSources.filter(s => s.tier === 'reputable')
    const customTier = trustedSources.filter(s => s.tier !== 'trusted' && s.tier !== 'reputable')

    return (
        <div className="h-full overflow-y-auto p-6 space-y-6 max-w-3xl mx-auto">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-lg font-semibold text-slate-900">Settings</h2>
                    <p className="text-sm text-slate-500 mt-0.5">Configure research behaviour, source policy, and LLM prompts.</p>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={handleReset}
                        className="px-3 py-2 text-sm rounded-lg border border-slate-300 text-slate-600 bg-white hover:bg-slate-50 flex items-center gap-1.5"
                    >
                        <RotateCcw className="w-3.5 h-3.5" />
                        Reset defaults
                    </button>
                    <button
                        onClick={handleSave}
                        disabled={!dirty}
                        className="px-4 py-2 text-sm rounded-lg bg-primary text-white hover:bg-primary-dark disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5 transition-colors"
                    >
                        <Save className="w-3.5 h-3.5" />
                        {saved ? 'Saved ✓' : 'Save'}
                    </button>
                </div>
            </div>

            {/* ═══ TRUSTED SOURCES ═══ */}
            <div className="bg-white border border-slate-200 rounded-xl p-5">
                <div className="flex items-center justify-between mb-4">
                    <div>
                        <h3 className="font-medium text-slate-900 flex items-center gap-2">
                            <Shield className="w-4 h-4 text-primary" />
                            Trusted Sources
                        </h3>
                        <p className="text-sm text-slate-500 mt-0.5">
                            Sources with higher trust scores are prioritised in search results. Social media is always excluded.
                        </p>
                    </div>
                    <div className="flex items-center gap-2">
                        <button onClick={handleResetSources}
                            className="px-2.5 py-1.5 text-xs rounded-lg border border-slate-300 text-slate-600 bg-white hover:bg-slate-50 flex items-center gap-1"
                        >
                            <RefreshCw className="w-3 h-3" /> Reset
                        </button>
                        <button onClick={handleSaveSources}
                            disabled={!sourcesDirty}
                            className="px-3 py-1.5 text-xs rounded-lg bg-primary text-white hover:bg-primary-dark disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1 transition-colors"
                        >
                            <Save className="w-3 h-3" /> {sourcesSaved ? 'Saved ✓' : 'Save Sources'}
                        </button>
                    </div>
                </div>

                {sourcesLoading ? (
                    <div className="animate-pulse space-y-2">
                        <div className="h-8 bg-slate-100 rounded"></div>
                        <div className="h-8 bg-slate-100 rounded"></div>
                        <div className="h-8 bg-slate-100 rounded"></div>
                    </div>
                ) : (
                    <div className="space-y-4">
                        {/* Trusted tier */}
                        {trustedTier.length > 0 && (
                            <SourceTierGroup
                                label="Trusted (Priority 1)"
                                color="emerald"
                                sources={trustedTier}
                                allSources={trustedSources}
                                onScoreChange={handleSourceScoreChange}
                                onRemove={handleRemoveSource}
                            />
                        )}
                        {/* Reputable tier */}
                        {reputableTier.length > 0 && (
                            <SourceTierGroup
                                label="Reputable (Priority 2)"
                                color="blue"
                                sources={reputableTier}
                                allSources={trustedSources}
                                onScoreChange={handleSourceScoreChange}
                                onRemove={handleRemoveSource}
                            />
                        )}
                        {/* Custom tier */}
                        {customTier.length > 0 && (
                            <SourceTierGroup
                                label="Custom"
                                color="slate"
                                sources={customTier}
                                allSources={trustedSources}
                                onScoreChange={handleSourceScoreChange}
                                onRemove={handleRemoveSource}
                            />
                        )}

                        {/* Add source */}
                        {showAddSource ? (
                            <div className="border border-dashed border-primary/40 rounded-lg p-3 bg-primary/5">
                                <div className="grid grid-cols-3 gap-2">
                                    <input type="text" placeholder="domain.com" value={newSource.domain}
                                        onChange={e => setNewSource(p => ({ ...p, domain: e.target.value }))}
                                        className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                                    />
                                    <input type="text" placeholder="Display name" value={newSource.name}
                                        onChange={e => setNewSource(p => ({ ...p, name: e.target.value }))}
                                        className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                                    />
                                    <div className="flex items-center gap-2">
                                        <input type="range" min={1} max={10} value={newSource.trust_score}
                                            onChange={e => setNewSource(p => ({ ...p, trust_score: Number(e.target.value) }))}
                                            className="flex-1 accent-primary"
                                        />
                                        <span className="text-sm font-mono w-6 text-center">{newSource.trust_score}</span>
                                    </div>
                                </div>
                                <div className="mt-2 flex justify-end gap-2">
                                    <button onClick={() => setShowAddSource(false)} className="px-3 py-1 text-xs rounded-lg border border-slate-300 text-slate-500 hover:bg-slate-50">Cancel</button>
                                    <button onClick={handleAddSource} disabled={!newSource.domain.trim()} className="px-3 py-1 text-xs rounded-lg bg-primary text-white hover:bg-primary-dark disabled:opacity-40">Add</button>
                                </div>
                            </div>
                        ) : (
                            <button onClick={() => setShowAddSource(true)}
                                className="w-full py-2 border border-dashed border-slate-300 rounded-lg text-sm text-slate-500 hover:border-primary hover:text-primary transition-colors flex items-center justify-center gap-1.5"
                            >
                                <Plus className="w-3.5 h-3.5" /> Add source
                            </button>
                        )}
                    </div>
                )}

                <div className="mt-3 flex items-center gap-2 text-xs text-slate-400">
                    <Info className="w-3.5 h-3.5 flex-shrink-0" />
                    <span>
                        <strong className="text-slate-600">{trustedSources.length}</strong> sources configured.
                        Sources are stored server-side and apply to all users.
                    </span>
                </div>
            </div>

            {/* Hypotheses per category */}
            <div className="bg-white border border-slate-200 rounded-xl p-5">
                <div className="flex items-start justify-between">
                    <div>
                        <h3 className="font-medium text-slate-900">Hypotheses per category</h3>
                        <p className="text-sm text-slate-500 mt-0.5">
                            Number of hypotheses generated for each category (Market, Brand, Competitive).
                        </p>
                    </div>
                    <div className="flex items-center gap-3">
                        <input
                            type="range"
                            min={1}
                            max={10}
                            value={settings.maxHypothesesPerCategory}
                            onChange={e => handleChange({ maxHypothesesPerCategory: Number(e.target.value) })}
                            className="w-32 accent-primary"
                        />
                        <span className="text-lg font-semibold text-slate-900 w-8 text-center">
                            {settings.maxHypothesesPerCategory}
                        </span>
                    </div>
                </div>
                <div className="mt-3 flex items-center gap-2 text-xs text-slate-400">
                    <Info className="w-3.5 h-3.5 flex-shrink-0" />
                    <span>
                        This means <strong className="text-slate-600">{hypothesisTotal} total hypotheses</strong> will
                        be generated and web-searched per query ({settings.maxHypothesesPerCategory} × 3 categories).
                        Higher = more thorough but slower and more expensive.
                    </span>
                </div>
            </div>

            {/* ═══ MIN VERIFIED SOURCES ═══ */}
            <div className="bg-white border border-slate-200 rounded-xl p-5">
                <div className="flex items-start justify-between">
                    <div>
                        <h3 className="font-medium text-slate-900">Minimum verified sources</h3>
                        <p className="text-sm text-slate-500 mt-0.5">
                            Minimum percentage of findings that must come from trusted/verified sources.
                        </p>
                    </div>
                    <div className="flex items-center gap-3">
                        <input
                            type="range"
                            min={0}
                            max={100}
                            step={5}
                            value={settings.minVerifiedSourcePct}
                            onChange={e => handleChange({ minVerifiedSourcePct: Number(e.target.value) })}
                            className="w-32 accent-primary"
                        />
                        <span className="text-lg font-semibold text-slate-900 w-12 text-center">
                            {settings.minVerifiedSourcePct}%
                        </span>
                    </div>
                </div>
                <div className="mt-3 flex items-center gap-2 text-xs text-slate-400">
                    <Shield className="w-3.5 h-3.5 flex-shrink-0" />
                    <span>
                        When results fall below <strong className="text-slate-600">{settings.minVerifiedSourcePct}%</strong> verified,
                        low-trust unverified findings are dropped to meet the threshold.
                        Set to 0% to include all findings regardless of source trust.
                    </span>
                </div>
            </div>

            {/* ═══ PROMPTS (Tabbed) ═══ */}
            <div className="bg-white border border-slate-200 rounded-xl p-5">
                <div className="flex items-center gap-1 mb-4 bg-slate-100 rounded-lg p-0.5 w-fit">
                    <button
                        onClick={() => handleChange({ activePromptTab: 'system' })}
                        className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all ${settings.activePromptTab !== 'hypothesis'
                            ? 'bg-white text-slate-900 shadow-sm'
                            : 'text-slate-500 hover:text-slate-700'
                            }`}
                    >
                        System Prompt
                    </button>
                    <button
                        onClick={() => handleChange({ activePromptTab: 'hypothesis' })}
                        className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all ${settings.activePromptTab === 'hypothesis'
                            ? 'bg-white text-slate-900 shadow-sm'
                            : 'text-slate-500 hover:text-slate-700'
                            }`}
                    >
                        Hypothesis Prompt
                    </button>
                </div>

                {settings.activePromptTab !== 'hypothesis' ? (
                    <>
                        <p className="text-sm text-slate-500 mb-3">
                            This prompt is prepended to every LLM call. It shapes the style, focus, and behaviour of the research agent.
                        </p>
                        <textarea
                            value={settings.systemPrompt}
                            onChange={e => handleChange({ systemPrompt: e.target.value })}
                            className="w-full min-h-[280px] rounded-xl border border-slate-300 px-4 py-3 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent resize-y bg-slate-50"
                            placeholder="Enter a system prompt..."
                        />
                        <div className="mt-2 flex items-center justify-between text-xs text-slate-400">
                            <span>{settings.systemPrompt.length} characters</span>
                            <button
                                type="button"
                                onClick={() => handleChange({ systemPrompt: DEFAULT_SETTINGS.systemPrompt })}
                                className="text-primary hover:underline"
                            >
                                Restore default prompt
                            </button>
                        </div>
                    </>
                ) : (
                    <>
                        <p className="text-sm text-slate-500 mb-3">
                            This prompt guides hypothesis generation. Use it to steer the type and quality of hypotheses the system produces. Leave blank to use the built-in default.
                        </p>
                        <textarea
                            value={settings.hypothesisPrompt}
                            onChange={e => handleChange({ hypothesisPrompt: e.target.value })}
                            className="w-full min-h-[280px] rounded-xl border border-slate-300 px-4 py-3 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent resize-y bg-slate-50"
                            placeholder={`Example:\n\nWhen generating hypotheses, focus on:\n- Concrete, verifiable events rather than general trends\n- Named people, products, campaigns, and dates\n- Factors specific to the brand's industry and region\n- Competitive actions from genuine competitors in the same market\n\nDo NOT generate hypotheses about unrelated industries.`}
                        />
                        <div className="mt-2 flex items-center justify-between text-xs text-slate-400">
                            <span>{settings.hypothesisPrompt.length} characters</span>
                            <button
                                type="button"
                                onClick={() => handleChange({ hypothesisPrompt: '' })}
                                className="text-primary hover:underline"
                            >
                                Clear (use default)
                            </button>
                        </div>
                    </>
                )}
            </div>

            {/* Danger Zone */}
            <div className={`border rounded-xl p-5 transition-colors ${confirmingClear ? 'bg-red-100 border-red-400' : 'bg-red-50 border-red-200'}`}>
                <div className="flex items-start justify-between gap-4">
                    <div>
                        <h3 className="font-medium text-red-900">Clear all data</h3>
                        <p className="text-sm text-red-600/80 mt-0.5">
                            Permanently delete all chat messages, research history, and saved settings. You will be prompted to re-enter the app password.
                        </p>
                        {confirmingClear && (
                            <div className="mt-3 flex items-center gap-2 text-sm font-medium text-red-700 animate-pulse">
                                <AlertTriangle className="w-4 h-4" />
                                Click again to confirm. This cannot be undone.
                            </div>
                        )}
                    </div>
                    <div className="flex flex-col items-end gap-2 flex-shrink-0">
                        <button
                            onClick={handleClearAll}
                            className={`px-4 py-2 text-sm rounded-lg text-white flex items-center gap-1.5 transition-all ${confirmingClear
                                ? 'bg-red-700 hover:bg-red-800 ring-2 ring-red-400 ring-offset-2'
                                : 'bg-red-600 hover:bg-red-700'
                                }`}
                        >
                            <Trash2 className="w-3.5 h-3.5" />
                            {confirmingClear ? 'Yes, clear everything' : 'Clear & Sign Out'}
                        </button>
                        {confirmingClear && (
                            <button
                                onClick={() => setConfirmingClear(false)}
                                className="text-xs text-red-600 hover:underline"
                            >
                                Cancel
                            </button>
                        )}
                    </div>
                </div>
            </div>

            {/* Info */}
            <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 text-xs text-slate-500 space-y-1">
                <p><strong>Where are settings stored?</strong> Prompts and hypotheses-per-category are stored server-side (shared across all users). A local copy is kept in your browser for fast loading.</p>
                <p><strong>Trusted sources</strong> are also stored server-side and shared across all users.</p>
                <p><strong>When do they take effect?</strong> On the next research query you submit. Active queries are not affected.</p>
            </div>
        </div>
    )
}

// ─── Source Tier Group ───────────────────────────────────────────────────────

function SourceTierGroup({ label, color, sources, allSources, onScoreChange, onRemove }: {
    label: string
    color: 'emerald' | 'blue' | 'slate'
    sources: TrustedSource[]
    allSources: TrustedSource[]
    onScoreChange: (idx: number, score: number) => void
    onRemove: (idx: number) => void
}) {
    const colorClasses = {
        emerald: 'bg-emerald-50 text-emerald-700 border-emerald-200',
        blue: 'bg-blue-50 text-blue-700 border-blue-200',
        slate: 'bg-slate-50 text-slate-700 border-slate-200',
    }

    return (
        <div>
            <p className={`text-xs font-medium px-2 py-1 rounded-t-lg border-b ${colorClasses[color]}`}>{label}</p>
            <div className="border border-t-0 border-slate-200 rounded-b-lg divide-y divide-slate-100">
                {sources.map((src) => {
                    const globalIdx = allSources.indexOf(src)
                    return (
                        <div key={`${src.domain}-${globalIdx}`} className="flex items-center gap-3 px-3 py-2 group hover:bg-slate-50">
                            <div className="flex-1 min-w-0">
                                <span className="text-sm font-medium text-slate-800">{src.name}</span>
                                <span className="text-xs text-slate-400 ml-2">{src.domain}</span>
                            </div>
                            <div className="flex items-center gap-2">
                                <input type="range" min={1} max={10} value={src.trust_score}
                                    onChange={e => onScoreChange(globalIdx, Number(e.target.value))}
                                    className="w-20 accent-primary"
                                />
                                <span className="text-xs font-mono text-slate-500 w-4 text-right">{src.trust_score}</span>
                                <button onClick={() => onRemove(globalIdx)} className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-red-50 transition-opacity">
                                    <X className="w-3.5 h-3.5 text-red-400" />
                                </button>
                            </div>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
