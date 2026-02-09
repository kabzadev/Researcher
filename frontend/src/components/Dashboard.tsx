import { useEffect, useMemo, useState } from 'react'

type Summary = {
  runs: number
  errors: number
  p50_latency_ms: number | null
  p95_latency_ms: number | null
  tokens_total: number
  tavily_searches: number
  tavily_second_passes: number
  providers: Record<string, number>
}

type Run = {
  run_id: string
  started_at: string
  latency_ms: number
  provider: string
  question: string
  brand?: string
  time_period?: string
  tavily_searches: number
  tavily_second_passes: number
  llm_calls: number
  tokens_in: number
  tokens_out: number
  tokens_total: number
  validated_counts?: { market: number; brand: number; competitive: number }
  error?: string
}

const API_URL = 'https://researcher-api.thankfulwave-8ed54622.eastus2.azurecontainerapps.io'

export function Dashboard() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [runs, setRuns] = useState<Run[]>([])
  const [loading, setLoading] = useState(false)

  const token = sessionStorage.getItem('researcher_app_password') || ''

  const headers = useMemo(() => ({
    'Authorization': `Bearer ${token}`
  }), [token])

  const refresh = async () => {
    setLoading(true)
    try {
      const [s, r] = await Promise.all([
        fetch(`${API_URL}/telemetry/summary`, { headers }).then(res => res.json()),
        fetch(`${API_URL}/telemetry/runs?limit=50`, { headers }).then(res => res.json())
      ])
      setSummary(s)
      setRuns((r.runs || []).slice().reverse())
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (!token) {
    return (
      <div className="p-6">
        <div className="bg-white border border-slate-200 rounded-xl p-4 text-sm text-slate-600">
          Dashboard is locked until you enter the app password in the main chat screen.
        </div>
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">Telemetry Dashboard</h2>
        <button
          onClick={refresh}
          className="px-3 py-2 text-sm rounded-lg border border-slate-300 bg-white hover:bg-slate-50"
          disabled={loading}
        >
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card title="Runs" value={summary?.runs ?? '—'} sub={`Errors: ${summary?.errors ?? '—'}`} />
        <Card title="Latency" value={summary?.p50_latency_ms ? `${summary?.p50_latency_ms}ms` : '—'} sub={`p95: ${summary?.p95_latency_ms ? `${summary?.p95_latency_ms}ms` : '—'}`} />
        <Card title="Tokens" value={summary?.tokens_total ?? '—'} sub={`Tavily: ${summary?.tavily_searches ?? '—'} (2nd pass ${summary?.tavily_second_passes ?? '—'})`} />
      </div>

      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-200 flex items-center justify-between">
          <h3 className="font-medium text-slate-900">Recent Runs</h3>
          <div className="text-xs text-slate-500">
            Providers: {summary?.providers ? Object.entries(summary.providers).map(([k,v]) => `${k}:${v}`).join(' • ') : '—'}
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                <th className="text-left px-4 py-2">Time</th>
                <th className="text-left px-4 py-2">Provider</th>
                <th className="text-left px-4 py-2">Brand</th>
                <th className="text-left px-4 py-2">Latency</th>
                <th className="text-left px-4 py-2">Tokens</th>
                <th className="text-left px-4 py-2">Tavily</th>
                <th className="text-left px-4 py-2">Validated</th>
                <th className="text-left px-4 py-2">Question</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.run_id} className="border-t border-slate-100">
                  <td className="px-4 py-2 text-slate-500 whitespace-nowrap">{new Date(r.started_at).toLocaleString()}</td>
                  <td className="px-4 py-2 whitespace-nowrap">{r.provider}</td>
                  <td className="px-4 py-2 whitespace-nowrap">{r.brand || '—'}</td>
                  <td className="px-4 py-2 whitespace-nowrap">{r.latency_ms}ms</td>
                  <td className="px-4 py-2 whitespace-nowrap">{r.tokens_total}</td>
                  <td className="px-4 py-2 whitespace-nowrap">{r.tavily_searches} (2nd {r.tavily_second_passes})</td>
                  <td className="px-4 py-2 whitespace-nowrap">
                    {r.validated_counts ? `${r.validated_counts.market}/${r.validated_counts.brand}/${r.validated_counts.competitive}` : '—'}
                  </td>
                  <td className="px-4 py-2 max-w-[420px] truncate" title={r.question}>{r.question}</td>
                </tr>
              ))}
              {runs.length === 0 && (
                <tr>
                  <td className="px-4 py-6 text-slate-500" colSpan={8}>No runs logged yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <p className="text-xs text-slate-500">
        Note: this is an MVP ring-buffer dashboard (last ~500 runs). Next step is durable storage + richer drilldown.
      </p>
    </div>
  )
}

function Card({ title, value, sub }: { title: string; value: any; sub?: string }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-4">
      <div className="text-xs text-slate-500">{title}</div>
      <div className="text-2xl font-semibold text-slate-900 mt-1">{value}</div>
      {sub && <div className="text-xs text-slate-500 mt-1">{sub}</div>}
    </div>
  )
}
