import { useEffect, useMemo, useState } from 'react'
import { Play, RefreshCcw } from 'lucide-react'

// Keep consistent with other components (production-safe default).
const API_URL = import.meta.env.VITE_API_URL || 'https://kaia-researcher-api.icyglacier-f068d1b2.eastus.azurecontainerapps.io'

type EvalQuestion = {
  id: string
  text: string
  tags?: string[]
}

type Score = {
  score: number
  drivers_total: number
  sections_nonempty: number
  citations_total: number
  unique_domains: number
}

type EvalResultRow = {
  question_id: string
  provider: string
  score: Score
  response: any
}

export function Eval() {
  const appPassword = sessionStorage.getItem('researcher_app_password') || ''

  const [questions, setQuestions] = useState<EvalQuestion[]>([])
  const [results, setResults] = useState<EvalResultRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let mounted = true
      ; (async () => {
        try {
          setError(null)
          const res = await fetch(`${API_URL}/eval/questions`, {
            headers: {
              Authorization: `Bearer ${appPassword}`
            }
          })
          if (!res.ok) {
            const txt = await res.text()
            throw new Error(`Failed to load eval questions (${res.status}): ${txt}`)
          }
          const data = await res.json()
          if (mounted) setQuestions(data.questions || [])
        } catch (e: any) {
          if (mounted) setError(e?.message || String(e))
        }
      })()

    return () => {
      mounted = false
    }
  }, [appPassword])

  const grouped = useMemo(() => {
    const byQ: Record<string, { openai?: EvalResultRow; anthropic?: EvalResultRow }> = {}
    for (const r of results) {
      byQ[r.question_id] = byQ[r.question_id] || {}
      if (r.provider === 'openai') byQ[r.question_id].openai = r
      if (r.provider === 'anthropic') byQ[r.question_id].anthropic = r
    }
    return byQ
  }, [results])

  const runEval = async () => {
    try {
      setLoading(true)
      setError(null)
      setResults([])

      const res = await fetch(`${API_URL}/eval/run`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${appPassword}`
        },
        body: JSON.stringify({ providerA: 'openai', providerB: 'anthropic', limit: 3 })
      })

      if (!res.ok) {
        const txt = await res.text()
        throw new Error(`Eval failed (${res.status}): ${txt}`)
      }

      const data = await res.json()
      setResults(data.results || [])
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="h-full overflow-y-auto p-4 md:p-6">
      <div className="max-w-5xl mx-auto">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Eval</h2>
            <p className="text-sm text-slate-600 mt-1">
              Run the fixed 10-question eval set against both providers and compare scores.
            </p>
          </div>

          <div className="flex gap-2">
            <button
              type="button"
              onClick={runEval}
              disabled={loading || !appPassword}
              className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-primary text-white text-sm hover:bg-primary-dark disabled:opacity-50"
            >
              {loading ? <RefreshCcw className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
              {loading ? 'Running…' : 'Run Eval'}
            </button>
          </div>
        </div>

        {!appPassword && (
          <div className="mt-4 p-4 rounded-xl border border-amber-200 bg-amber-50 text-amber-900 text-sm">
            You’re not authenticated yet. Go to Research, enter the app password, then come back here.
          </div>
        )}

        {error && (
          <div className="mt-4 p-4 rounded-xl border border-rose-200 bg-rose-50 text-rose-900 text-sm whitespace-pre-wrap">
            {error}
          </div>
        )}

        <div className="mt-6">
          <h3 className="text-sm font-semibold text-slate-800">Questions</h3>
          <ol className="mt-2 space-y-2 list-decimal list-inside text-sm text-slate-700">
            {questions.map((q) => (
              <li key={q.id}>
                <span className="font-medium mr-2">{q.id}</span>
                {q.text}
              </li>
            ))}
          </ol>
        </div>

        {results.length > 0 && (
          <div className="mt-8">
            <h3 className="text-sm font-semibold text-slate-800">Results</h3>
            <div className="mt-3 space-y-4">
              {questions.map((q) => {
                const row = grouped[q.id] || {}
                const a = row.anthropic
                const o = row.openai

                const Cell = ({ r }: { r?: EvalResultRow }) => (
                  <div className="rounded-xl border border-slate-200 bg-white p-4">
                    {!r ? (
                      <div className="text-sm text-slate-500">No result</div>
                    ) : (
                      <>
                        <div className="flex items-center justify-between">
                          <div className="text-sm font-semibold text-slate-900">{r.provider}</div>
                          <div className="text-sm font-semibold text-slate-900">Score: {r.score?.score ?? '—'}</div>
                        </div>
                        <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-slate-600">
                          <div>Drivers: {r.score?.drivers_total ?? 0}</div>
                          <div>Sections: {r.score?.sections_nonempty ?? 0}</div>
                          <div>Citations: {r.score?.citations_total ?? 0}</div>
                          <div>Domains: {r.score?.unique_domains ?? 0}</div>
                        </div>
                        <details className="mt-3">
                          <summary className="cursor-pointer text-xs text-slate-500">View response JSON</summary>
                          <pre className="mt-2 p-3 bg-slate-50 rounded-lg text-[11px] overflow-x-auto">
                            {JSON.stringify(r.response, null, 2)}
                          </pre>
                        </details>
                      </>
                    )}
                  </div>
                )

                return (
                  <div key={q.id} className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                    <div className="text-sm font-medium text-slate-800">{q.id}: {q.text}</div>
                    <div className="mt-3 grid md:grid-cols-2 gap-3">
                      <Cell r={o} />
                      <Cell r={a} />
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
