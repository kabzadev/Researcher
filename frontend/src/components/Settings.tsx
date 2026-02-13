import { useState, useEffect, useRef } from 'react'
import { Save, RotateCcw, Info, Trash2, AlertTriangle } from 'lucide-react'
import { loadSettings, saveSettings, resetSettings, DEFAULT_SETTINGS, type AppSettings } from '../lib/settingsStore'

export function Settings() {
    const [settings, setSettings] = useState<AppSettings>(() => loadSettings())
    const [saved, setSaved] = useState(false)
    const [dirty, setDirty] = useState(false)
    const [confirmingClear, setConfirmingClear] = useState(false)
    const clearTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

    // Load on mount
    useEffect(() => {
        setSettings(loadSettings())
    }, [])

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

    const handleSave = () => {
        saveSettings(settings)
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
        // Second click — nuke everything
        sessionStorage.clear()
        localStorage.removeItem('researcher_history_v1')
        localStorage.removeItem('researcher_settings_v1')
        // Hard navigation to break out of HMR and force password prompt
        window.location.replace(window.location.origin)
    }

    const hypothesisTotal = settings.maxHypothesesPerCategory * 3

    return (
        <div className="h-full overflow-y-auto p-6 space-y-6 max-w-3xl mx-auto">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-lg font-semibold text-slate-900">Settings</h2>
                    <p className="text-sm text-slate-500 mt-0.5">Configure research behaviour and LLM prompts.</p>
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

            {/* System prompt */}
            <div className="bg-white border border-slate-200 rounded-xl p-5">
                <h3 className="font-medium text-slate-900">System prompt</h3>
                <p className="text-sm text-slate-500 mt-0.5 mb-3">
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
                <p><strong>Where are settings stored?</strong> In your browser's localStorage — they persist across sessions but are specific to this device.</p>
                <p><strong>When do they take effect?</strong> On the next research query you submit. Active queries are not affected.</p>
            </div>
        </div>
    )
}
