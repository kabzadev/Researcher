import { useState, useRef, useEffect, useCallback } from 'react'
import { Send, Loader2, ExternalLink, Sparkles, X, Download, ChevronRight, Shield, ShieldAlert, Clock, FileText } from 'lucide-react'
import { saveToHistory } from '../lib/historyStore'
import { loadSettings } from '../lib/settingsStore'
import jsPDF from 'jspdf'

// ─── Types ──────────────────────────────────────────────────────────────────

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  provider?: string
  runId?: string
  feedback?: 1 | -1
  // Compact card data (persisted in chat)
  reportCard?: ReportCard
  // Full report data (loaded in detail pane)
  reportData?: ReportData | null
  thinking?: string[]
}

interface ReportCard {
  brand: string
  metric: string
  direction: string
  timePeriod?: string
  validatedCount: number
  totalHypotheses: number
  trustedRatio?: number
  latencyMs?: number
  status: 'streaming' | 'complete' | 'error'
  streamProgress?: string
}

interface ReportData {
  question: string
  brand: string
  metrics: string[]
  direction: string
  timePeriod?: string
  providerUsed: string
  executiveSummary?: string
  sourcePolicy?: {
    trusted_source_count: number
    total_source_count: number
    trusted_ratio: number
    social_media_filtered: boolean
  }
  sections: {
    market: ValidatedItem[]
    brand: ValidatedItem[]
    competitive: ValidatedItem[]
  }
  hypotheses?: any
  validated_hypotheses?: any
  summary?: any
  runId?: string
  latencyMs?: number
  webSearches?: number
  llmCalls?: number
  tokensIn?: number
  tokensOut?: number
}

interface ValidatedItem {
  hypothesis: string
  evidence: string
  source?: string
  sourceTitle?: string
  trustScore?: number
  tier?: string
  sourceName?: string
  isTrusted?: boolean
  status?: string
}

// ─── Component ──────────────────────────────────────────────────────────────

export function ChatInterface() {
  const defaultWelcome: Message[] = [
    {
      id: '1',
      role: 'assistant',
      content:
        'Hello! I\'m your research assistant. I can help you understand changes in brand metrics by researching external factors.\n\n' +
        '**Currently supported:** Questions about Salient (mental availability) changes for fashion retail brands.\n\n' +
        '**Example:** "Salience fell by 6 points in Q3 2025 for new look, can you help find external reasons for decreased mental availability?"'
    }
  ]

  const [messages, setMessages] = useState<Message[]>(() => {
    try {
      const raw = sessionStorage.getItem('researcher_chat_messages_v2')
      if (!raw) return defaultWelcome
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed) && parsed.length) return parsed
      return defaultWelcome
    } catch {
      return defaultWelcome
    }
  })
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [provider] = useState<'anthropic' | 'openai'>('openai')
  const [appPassword, setAppPassword] = useState<string>(() => sessionStorage.getItem('researcher_app_password') || '')
  const [passwordInput, setPasswordInput] = useState('')
  const [feedbackModal, setFeedbackModal] = useState<{ open: boolean; messageId?: string; runId?: string; provider?: string; question?: string }>({ open: false })
  const [feedbackText, setFeedbackText] = useState('')
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null)
  const [detailPaneOpen, setDetailPaneOpen] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  const lastMessageCountRef = useRef(messages.length)
  useEffect(() => {
    if (messages.length > lastMessageCountRef.current) {
      scrollToBottom()
      lastMessageCountRef.current = messages.length
    }
  }, [messages])

  // Persist chat history
  useEffect(() => {
    try {
      sessionStorage.setItem('researcher_chat_messages_v2', JSON.stringify(messages))
    } catch { /* ignore */ }
  }, [messages])

  // Auto-open detail pane when a report starts streaming
  useEffect(() => {
    if (selectedReportId) {
      setDetailPaneOpen(true)
    }
  }, [selectedReportId])

  const API_URL = 'https://kaia-researcher-api.icyglacier-f068d1b2.eastus.azurecontainerapps.io'

  const selectReport = useCallback((messageId: string) => {
    setSelectedReportId(messageId)
    setDetailPaneOpen(true)
  }, [])

  const selectedReport = messages.find(m => m.id === selectedReportId)

  // ─── Send handler ────────────────────────────────────────────────────────

  const handleSend = async () => {
    if (!input.trim() || isLoading) return

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input
    }

    setMessages(prev => [...prev, userMessage])
    setInput('')
    setIsLoading(true)

    const assistantId = (Date.now() + 1).toString()

    try {
      const extractHostname = (url: string): string => {
        try { return new URL(url).hostname.replace('www.', '') }
        catch { return 'Source' }
      }

      const transformValidated = (item: any): ValidatedItem => ({
        hypothesis: item.hypothesis || '',
        evidence: item.evidence || item.driver || '',
        source: item.source || item.source_urls?.[0] || '',
        sourceTitle: item.source_title || (item.source ? extractHostname(item.source) : ''),
        trustScore: item.trust_score ?? 3,
        tier: item.tier || 'unverified',
        sourceName: item.source_name || '',
        isTrusted: item.is_trusted ?? false,
        status: item.status || '',
      })

      // Create initial card message
      const cardMessage: Message = {
        id: assistantId,
        role: 'assistant',
        content: '',
        provider,
        reportCard: {
          brand: '…',
          metric: '…',
          direction: '…',
          validatedCount: 0,
          totalHypotheses: 0,
          status: 'streaming',
          streamProgress: 'Starting research…'
        },
        reportData: null,
      }
      setMessages(prev => [...prev, cardMessage])
      setSelectedReportId(assistantId)

      const settings = loadSettings()

      // Streaming mode (SSE)
      const response = await fetch(`${API_URL}/research/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${appPassword}`
        },
        body: JSON.stringify({
          question: input, provider,
          system_prompt: settings.systemPrompt || undefined,
          max_hypotheses_per_category: settings.maxHypothesesPerCategory
        })
      })

      if (!response.ok) {
        const txt = await response.text()
        throw new Error(`HTTP ${response.status}: ${txt}`)
      }
      if (!response.body) throw new Error('Streaming not supported by browser')

      const decoder = new TextDecoder()
      const reader = response.body.getReader()
      let buffer = ''

      // Accumulate state across SSE messages
      let parsedData: any = {}
      let validatedItems: { market: ValidatedItem[], brand: ValidatedItem[], competitive: ValidatedItem[] } = { market: [], brand: [], competitive: [] }
      let executiveSummary = ''
      let sourcePolicy: any = null
      let completedCount = 0
      let totalCount = 0

      const updateCard = (patch: Partial<ReportCard>) => {
        setMessages(prev => prev.map(m => {
          if (m.id !== assistantId) return m
          return { ...m, reportCard: { ...m.reportCard!, ...patch } }
        }))
      }

      const updateReport = (patch: Partial<ReportData>) => {
        setMessages(prev => prev.map(m => {
          if (m.id !== assistantId) return m
          const existing = m.reportData || {
            question: input,
            brand: parsedData.brand || '',
            metrics: parsedData.metrics || [],
            direction: parsedData.direction || '',
            providerUsed: provider,
            sections: { market: [], brand: [], competitive: [] },
          } as ReportData
          return { ...m, reportData: { ...existing, ...patch } }
        }))
      }

      while (true) {
        const { value, done } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''

        for (const part of parts) {
          const lines = part.split('\n').filter(Boolean)
          const eventLine = lines.find(l => l.startsWith('event:'))
          const dataLine = lines.find(l => l.startsWith('data:'))
          if (!eventLine || !dataLine) continue

          const event = eventLine.replace('event:', '').trim()
          const raw = dataLine.replace('data:', '').trim()

          let data: any
          try { data = JSON.parse(raw) } catch { continue }

          if (event === 'parsed') {
            parsedData = data
            updateCard({
              brand: data.brand || '…',
              metric: data.metric || data.metrics?.[0] || '…',
              direction: data.direction || '…',
              timePeriod: data.time_period,
              streamProgress: `Parsed: ${data.brand}`
            })
            updateReport({
              brand: data.brand,
              metrics: Array.isArray(data.metric) ? data.metric : [data.metric || data.metrics?.[0] || 'salience'],
              direction: data.direction,
              timePeriod: data.time_period,
            })
          }

          if (event === 'hypotheses') {
            // hypothesesData captured for future reasoning trace
            const total = (data.market?.length || 0) + (data.brand?.length || 0) + (data.competitive?.length || 0)
            totalCount = total
            updateCard({
              totalHypotheses: total,
              streamProgress: `Generated ${total} hypotheses…`
            })
            updateReport({ hypotheses: data })
          }

          if (event === 'status') {
            if (data.stage === 'search') {
              totalCount = data.total_hypotheses || totalCount
              updateCard({
                totalHypotheses: totalCount,
                streamProgress: `Searching (0/${totalCount})…`
              })
            }
          }

          if (event === 'hypothesis_result') {
            completedCount = data.completed || completedCount + 1
            updateCard({
              streamProgress: `Searching (${completedCount}/${totalCount})…`,
              validatedCount: data.validated
                ? (messages.find(m => m.id === assistantId)?.reportCard?.validatedCount || 0) + 1
                : (messages.find(m => m.id === assistantId)?.reportCard?.validatedCount || 0),
            })

            // Add to validated items if validated
            if (data.validated && data.category) {
              const item = transformValidated(data)
              const cat = data.category as 'market' | 'brand' | 'competitive'
              if (validatedItems[cat]) {
                validatedItems[cat] = [...validatedItems[cat], item]
                updateReport({ sections: { ...validatedItems } })
                // Update card count
                const total = validatedItems.market.length + validatedItems.brand.length + validatedItems.competitive.length
                updateCard({ validatedCount: total })
              }
            }
          }

          if (event === 'executive_summary') {
            executiveSummary = data.summary || ''
            updateReport({ executiveSummary })
          }

          if (event === 'final') {
            // Final payload — build complete report
            const finalSections: ReportData['sections'] = { market: [], brand: [], competitive: [] }
            for (const cat of ['market', 'brand', 'competitive'] as const) {
              for (const item of data.validated_hypotheses?.[cat] || []) {
                finalSections[cat].push(transformValidated(item))
              }
            }

            const validatedTotal = finalSections.market.length + finalSections.brand.length + finalSections.competitive.length

            const finalReport: ReportData = {
              question: data.question || input,
              brand: data.brand || parsedData.brand || '',
              metrics: data.metrics || [parsedData.metric || 'salience'],
              direction: data.direction || parsedData.direction || '',
              timePeriod: data.time_period || parsedData.time_period,
              providerUsed: data.provider_used || provider,
              executiveSummary: data.executive_summary || executiveSummary,
              sourcePolicy: data.source_policy || sourcePolicy,
              sections: finalSections,
              hypotheses: data.hypotheses,
              validated_hypotheses: data.validated_hypotheses,
              summary: data.summary,
              runId: data.run_id,
              latencyMs: data.latency_ms,
              webSearches: data.web_searches,
              llmCalls: data.llm_calls,
              tokensIn: data.tokens_in,
              tokensOut: data.tokens_out,
            }

            const finalCard: ReportCard = {
              brand: finalReport.brand,
              metric: finalReport.metrics?.[0] || 'salience',
              direction: finalReport.direction,
              timePeriod: finalReport.timePeriod,
              validatedCount: validatedTotal,
              totalHypotheses: totalCount,
              trustedRatio: finalReport.sourcePolicy?.trusted_ratio,
              latencyMs: finalReport.latencyMs,
              status: 'complete',
            }

            // Build thinking list
            const thinking: string[] = []
            for (const cat of ['market', 'brand', 'competitive'] as const) {
              for (const item of finalSections[cat]) {
                thinking.push(`✅ ${item.hypothesis}`)
              }
            }

            // Build content for chat (compact summary)
            const contentLines: string[] = []
            if (validatedTotal > 0) {
              contentLines.push(`Research complete for **${finalReport.brand}** — ${validatedTotal} validated findings.`)
            } else {
              contentLines.push(`Research complete for **${finalReport.brand}** — no validated findings.`)
            }

            setMessages(prev => prev.map(m => {
              if (m.id !== assistantId) return m
              return {
                ...m,
                content: contentLines.join('\n'),
                reportCard: finalCard,
                reportData: finalReport,
                runId: data.run_id,
                thinking,
              }
            }))

            // Save to history
            saveToHistory({
              question: input,
              provider: data.provider_used || provider,
              runId: data.run_id,
              latencyMs: data.latency_ms,
              content: contentLines.join('\n'),
              brand: finalReport.brand,
              direction: finalReport.direction,
              metrics: finalReport.metrics,
              thinking,
              drivers: {
                macro: (data.summary?.macro_drivers || []).map((d: any) => ({
                  hypothesis: d.hypothesis || '', evidence: d.driver || d.evidence || '',
                  url: d.source_urls?.[0] || d.source || '', source: d.source_title || ''
                })),
                brand: (data.summary?.brand_drivers || []).map((d: any) => ({
                  hypothesis: d.hypothesis || '', evidence: d.driver || d.evidence || '',
                  url: d.source_urls?.[0] || d.source || '', source: d.source_title || ''
                })),
                competitive: (data.summary?.competitive_drivers || []).map((d: any) => ({
                  hypothesis: d.hypothesis || '', evidence: d.driver || d.evidence || '',
                  url: d.source_urls?.[0] || d.source || '', source: d.source_title || ''
                })),
              },
            })
          }
        }
      }
    } catch (error: any) {
      const raw = (error?.message || '').toString()
      let errorMsg = "Sorry, there was an error processing your request."

      const m = raw.match(/HTTP\s+(\d+):\s*(.*)/s)
      const status = m ? parseInt(m[1], 10) : null
      const body = m ? (m[2] || '') : ''

      if (status === 401) {
        try { sessionStorage.removeItem('researcher_app_password') } catch { }
        setAppPassword('')
        errorMsg = "⚠️ **Unauthorized (401)** — please re-enter the password."
      } else if (status === 500) {
        errorMsg = "⚠️ **Server Error (500)** — try again in ~15s."
      } else if (raw.includes('CORS')) {
        errorMsg = "⚠️ **Connection Error** — service may be starting up (~30s cold start)."
      } else if (status) {
        errorMsg = `⚠️ **Request Failed (${status})** — ${body || raw}`
      }

      setMessages(prev => prev.map(m => (m.id === assistantId ? {
        ...m,
        content: errorMsg,
        reportCard: m.reportCard ? { ...m.reportCard, status: 'error' as const, streamProgress: 'Error' } : undefined,
      } : m)))
    } finally {
      setIsLoading(false)
    }
  }

  // ─── Password gate ────────────────────────────────────────────────────────

  if (!appPassword) {
    const submitPassword = () => {
      const v = passwordInput.trim()
      if (!v) return
      sessionStorage.setItem('researcher_app_password', v)
      setAppPassword(v)
    }
    return (
      <div className="flex flex-col h-full max-w-md mx-auto justify-center p-6">
        <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Researcher Access</h2>
          <p className="text-sm text-slate-500 mt-1">Enter the app password to continue.</p>
          <div className="mt-4 flex gap-2">
            <input type="password" value={passwordInput}
              onChange={(e) => setPasswordInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') submitPassword() }}
              placeholder="Password"
              className="flex-1 rounded-xl border border-slate-300 px-4 py-3 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
            />
            <button type="button" onClick={submitPassword} className="px-4 py-2 bg-primary text-white rounded-xl hover:bg-primary-dark transition-colors">Enter</button>
          </div>
          <p className="mt-3 text-[11px] text-slate-400">Credentials stored only in your browser session.</p>
        </div>
      </div>
    )
  }

  // ─── Main UI: Split Pane ──────────────────────────────────────────────────

  return (
    <div className="flex h-full overflow-hidden">
      {/* ═══ LEFT PANE: Chat ═══ */}
      <div className={`flex flex-col ${detailPaneOpen ? 'w-[420px] min-w-[380px]' : 'flex-1 max-w-4xl mx-auto'} border-r border-slate-200 transition-all duration-300`}>
        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {messages.map((message) => (
            <div key={message.id} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              {message.role === 'user' ? (
                // User bubble
                <div className="max-w-[85%] rounded-2xl px-4 py-3 bg-primary text-white">
                  <div className="whitespace-pre-wrap text-sm">{message.content}</div>
                </div>
              ) : message.reportCard ? (
                // Research report card
                <ResearchCard
                  message={message}
                  isSelected={selectedReportId === message.id}
                  onClick={() => selectReport(message.id)}
                  onFeedback={(rating) => {
                    if (rating === -1) {
                      setFeedbackText('')
                      setFeedbackModal({ open: true, messageId: message.id, runId: message.runId, provider: message.provider })
                    } else {
                      setMessages(prev => prev.map(m => m.id === message.id ? { ...m, feedback: 1 } : m))
                      fetch(`${API_URL}/feedback`, {
                        method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${appPassword}` },
                        body: JSON.stringify({ run_id: message.runId, rating: 1, provider: message.provider })
                      }).catch(console.error)
                    }
                  }}
                />
              ) : (
                // Plain assistant message (welcome, errors, coaching)
                <div className="max-w-[85%] rounded-2xl px-4 py-3 bg-white border border-slate-200 shadow-sm">
                  {message.provider && (
                    <div className="mb-2">
                      <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700">⚡ GPT</span>
                    </div>
                  )}
                  <div className="whitespace-pre-wrap text-sm">{message.content}</div>
                </div>
              )}
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* Input area */}
        <div className="p-4 border-t border-slate-200 bg-white">
          <div className="flex gap-2">
            <textarea value={input} onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }}
              placeholder="Ask about brand metric changes…"
              className="flex-1 resize-none rounded-xl border border-slate-300 px-4 py-3 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent min-h-[56px] max-h-32 text-sm"
              rows={1}
            />
            <button onClick={handleSend} disabled={!input.trim() || isLoading}
              className="px-4 py-2 bg-primary text-white rounded-xl hover:bg-primary-dark disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
            >
              {isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            </button>
          </div>
          <div className="mt-2 flex items-center justify-between">
            <p className="text-xs text-slate-400">Press Enter to send · Shift+Enter for new line</p>
            <span className="text-[10px] text-slate-300">All API keys in Azure Key Vault</span>
          </div>
        </div>
      </div>

      {/* ═══ RIGHT PANE: Report Detail ═══ */}
      {detailPaneOpen && selectedReport?.reportData && (
        <ReportDetailPane
          report={selectedReport.reportData}
          card={selectedReport.reportCard!}
          onClose={() => { setDetailPaneOpen(false); setSelectedReportId(null) }}
        />
      )}

      {/* Feedback Modal */}
      {feedbackModal.open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/40" onClick={() => setFeedbackModal({ open: false })} />
          <div className="relative bg-white w-full max-w-lg rounded-2xl border border-slate-200 shadow-xl p-5">
            <h3 className="font-semibold text-slate-900">What was wrong?</h3>
            <p className="text-xs text-slate-500 mt-1">This helps us improve. (Stored for model/prompt tuning.)</p>
            <textarea value={feedbackText} onChange={(e) => setFeedbackText(e.target.value)}
              placeholder="e.g. missed competitor news, wrong region, no citations…"
              className="mt-3 w-full min-h-[120px] rounded-xl border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            />
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" className="px-3 py-2 text-sm rounded-xl border border-slate-300 bg-white hover:bg-slate-50" onClick={() => setFeedbackModal({ open: false })}>Cancel</button>
              <button type="button" className="px-3 py-2 text-sm rounded-xl bg-rose-600 text-white hover:bg-rose-700" onClick={async () => {
                if (feedbackModal.messageId) {
                  setMessages(prev => prev.map(m => m.id === feedbackModal.messageId ? { ...m, feedback: -1 } : m))
                }
                try {
                  await fetch(`${API_URL}/feedback`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${appPassword}` },
                    body: JSON.stringify({ run_id: feedbackModal.runId, rating: -1, comment: feedbackText, provider: feedbackModal.provider })
                  })
                } catch (err) { console.error('Feedback error:', err) }
                setFeedbackModal({ open: false })
              }}>Submit</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Research Card Component ────────────────────────────────────────────────

function ResearchCard({ message, isSelected, onClick, onFeedback }: {
  message: Message
  isSelected: boolean
  onClick: () => void
  onFeedback: (rating: 1 | -1) => void
}) {
  const card = message.reportCard!
  const isStreaming = card.status === 'streaming'
  const isError = card.status === 'error'

  return (
    <div className="w-full max-w-[95%]">
      {/* Provider badge */}
      <div className="flex items-center gap-2 mb-1.5 ml-1">
        <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 font-medium">⚡ GPT</span>
        <span className="text-xs text-slate-400">
          {new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </span>
        {card.latencyMs && (
          <span className="text-xs text-slate-400 flex items-center gap-1">
            <Clock className="w-3 h-3" /> {(card.latencyMs / 1000).toFixed(1)}s
          </span>
        )}
      </div>

      {/* Card */}
      <button
        type="button"
        onClick={onClick}
        className={`w-full text-left rounded-2xl border-2 px-4 py-3.5 transition-all duration-200 hover:shadow-md ${isSelected
          ? 'border-primary bg-primary/5 shadow-md'
          : isError
            ? 'border-red-300 bg-red-50'
            : 'border-slate-200 bg-white hover:border-primary/40'
          }`}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3 min-w-0">
            <div className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 ${isStreaming ? 'bg-primary/10' : isError ? 'bg-red-100' : 'bg-primary/10'
              }`}>
              {isStreaming ? (
                <Loader2 className="w-5 h-5 text-primary animate-spin" />
              ) : isError ? (
                <ShieldAlert className="w-5 h-5 text-red-500" />
              ) : (
                <FileText className="w-5 h-5 text-primary" />
              )}
            </div>
            <div className="min-w-0">
              <p className="font-semibold text-slate-900 text-sm truncate">
                {card.brand} — {card.metric} {card.direction}
              </p>
              <p className="text-xs text-slate-500 mt-0.5">
                {isStreaming ? card.streamProgress : isError ? 'Research failed' : 'Click to view report'}
              </p>
            </div>
          </div>
          {!isStreaming && !isError && (
            <ChevronRight className="w-5 h-5 text-slate-400 flex-shrink-0 mt-1" />
          )}
        </div>

        {/* Stats row */}
        {card.status === 'complete' && (
          <div className="mt-3 flex items-center gap-3 text-xs">
            <span className={`px-2 py-0.5 rounded-full font-medium ${card.validatedCount > 0 ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'
              }`}>
              {card.validatedCount}/{card.totalHypotheses} validated
            </span>
            {card.trustedRatio !== undefined && (
              <span className="px-2 py-0.5 rounded-full bg-blue-50 text-blue-600 flex items-center gap-1">
                <Shield className="w-3 h-3" /> {card.trustedRatio}% trusted
              </span>
            )}
            {card.timePeriod && (
              <span className="text-slate-400">{card.timePeriod}</span>
            )}
          </div>
        )}
      </button>

      {/* Feedback row */}
      {message.runId && card.status === 'complete' && (
        <div className="flex items-center gap-2 mt-1.5 ml-1">
          <button type="button"
            className={`px-2 py-0.5 rounded-lg text-xs border ${message.feedback === 1 ? 'bg-emerald-50 border-emerald-200 text-emerald-700' : 'bg-white border-slate-200 hover:bg-slate-50 text-slate-500'}`}
            onClick={(e) => { e.stopPropagation(); onFeedback(1) }}
          >👍</button>
          <button type="button"
            className={`px-2 py-0.5 rounded-lg text-xs border ${message.feedback === -1 ? 'bg-rose-50 border-rose-200 text-rose-700' : 'bg-white border-slate-200 hover:bg-slate-50 text-slate-500'}`}
            onClick={(e) => { e.stopPropagation(); onFeedback(-1) }}
          >👎</button>
          <span className="text-[10px] text-slate-300 ml-1">Run: {message.runId?.slice(0, 8)}</span>
        </div>
      )}
    </div>
  )
}

// ─── Report Detail Pane ─────────────────────────────────────────────────────

function ReportDetailPane({ report, card, onClose }: {
  report: ReportData
  card: ReportCard
  onClose: () => void
}) {
  const isStreaming = card.status === 'streaming'

  const totalValidated = report.sections.market.length + report.sections.brand.length + report.sections.competitive.length

  return (
    <div className="flex-1 flex flex-col bg-white overflow-hidden min-w-0">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 bg-white flex-shrink-0">
        <div className="flex items-start gap-3 min-w-0">
          <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center flex-shrink-0">
            <FileText className="w-5 h-5 text-primary" />
          </div>
          <div className="min-w-0">
            <h2 className="font-semibold text-slate-900 truncate">
              {report.brand} — {report.metrics?.[0] || 'Metric'} Analysis
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              {report.metrics?.[0] || 'Metric'} Analysis Report
              {isStreaming && <span className="ml-2 text-primary animate-pulse">● Streaming…</span>}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <button className="px-3 py-1.5 text-xs rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 flex items-center gap-1.5" onClick={async () => {
            try {
              console.log('[Export] Starting PDF export…', { brand: report.brand, metrics: report.metrics })
              await exportReportAsPDF(report)
              console.log('[Export] PDF export completed')
            } catch (err) {
              console.error('[Export] PDF export failed:', err)
              alert('PDF export failed: ' + (err instanceof Error ? err.message : String(err)))
            }
          }}>
            <Download className="w-3.5 h-3.5" /> Export
          </button>
          <button className="p-1.5 rounded-lg hover:bg-slate-100 transition-colors" onClick={onClose}>
            <X className="w-5 h-5 text-slate-400" />
          </button>
        </div>
      </div>

      {/* Report body */}
      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
        {/* Meta bar */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <MetaBox label="Brand" value={report.brand} />
          <MetaBox label="Direction" value={report.direction || '—'} />
          <MetaBox label="Metric" value={report.metrics?.[0] || '—'} />
          <MetaBox label="Period" value={report.timePeriod || 'Not specified'} />
        </div>

        {/* Source policy badges */}
        {report.sourcePolicy && (
          <div className="flex items-center gap-3 flex-wrap">
            <span className="px-2.5 py-1 rounded-full text-xs bg-emerald-50 text-emerald-700 flex items-center gap-1.5 font-medium">
              <Shield className="w-3.5 h-3.5" />
              {report.sourcePolicy.trusted_source_count}/{report.sourcePolicy.total_source_count} verified sources ({report.sourcePolicy.trusted_ratio}%)
            </span>
            {report.sourcePolicy.social_media_filtered && (
              <span className="px-2.5 py-1 rounded-full text-xs bg-red-50 text-red-600 flex items-center gap-1.5">
                <ShieldAlert className="w-3.5 h-3.5" /> Social media filtered
              </span>
            )}
          </div>
        )}

        {/* Executive Summary */}
        {report.executiveSummary ? (
          <div className="bg-gradient-to-br from-primary/5 to-slate-50 border border-primary/20 rounded-xl p-5">
            <h3 className="font-semibold text-slate-900 mb-2 flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-primary" /> Executive Summary
            </h3>
            <p className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">{report.executiveSummary}</p>
          </div>
        ) : isStreaming ? (
          <div className="bg-slate-50 border border-slate-200 rounded-xl p-5 animate-pulse">
            <div className="h-4 bg-slate-200 rounded w-1/3 mb-3"></div>
            <div className="h-3 bg-slate-200 rounded w-full mb-2"></div>
            <div className="h-3 bg-slate-200 rounded w-4/5"></div>
          </div>
        ) : null}

        {/* Section: Market / Macro Drivers */}
        <ReportSection
          title="Market & Macro Drivers"
          icon="🌍"
          color="blue"
          items={report.sections.market}
          isStreaming={isStreaming}
        />

        {/* Section: Brand-specific Insights */}
        <ReportSection
          title="Brand-specific Insights"
          icon="🏷️"
          color="emerald"
          items={report.sections.brand}
          isStreaming={isStreaming}
        />

        {/* Section: Competitive Landscape */}
        <ReportSection
          title="Competitive Landscape"
          icon="⚔️"
          color="amber"
          items={report.sections.competitive}
          isStreaming={isStreaming}
        />

        {/* Telemetry footer */}
        {report.latencyMs && (
          <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 text-xs text-slate-500 grid grid-cols-2 md:grid-cols-4 gap-3">
            <div><span className="font-medium text-slate-600">Latency:</span> {(report.latencyMs / 1000).toFixed(1)}s</div>
            <div><span className="font-medium text-slate-600">Searches:</span> {report.webSearches || 0}</div>
            <div><span className="font-medium text-slate-600">LLM Calls:</span> {report.llmCalls || 0}</div>
            <div><span className="font-medium text-slate-600">Tokens:</span> {((report.tokensIn || 0) + (report.tokensOut || 0)).toLocaleString()}</div>
          </div>
        )}

        {/* No results message */}
        {!isStreaming && totalValidated === 0 && (
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-5 text-center">
            <p className="text-sm text-amber-800 font-medium">No validated findings were found.</p>
            <p className="text-xs text-amber-600 mt-1">Try refining your query with more specific brand, metric, or time period details.</p>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Sub-components ─────────────────────────────────────────────────────────

function MetaBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">
      <p className="text-[10px] uppercase tracking-wider text-slate-400 font-medium">{label}</p>
      <p className="text-sm font-semibold text-slate-800 mt-0.5 capitalize">{value}</p>
    </div>
  )
}

function ReportSection({ title, icon, color, items, isStreaming }: {
  title: string
  icon: string
  color: 'blue' | 'emerald' | 'amber'
  items: ValidatedItem[]
  isStreaming: boolean
}) {
  const colorMap = {
    blue: { border: 'border-blue-500', bg: 'bg-blue-50', text: 'text-blue-700', badge: 'bg-blue-100 text-blue-700' },
    emerald: { border: 'border-emerald-500', bg: 'bg-emerald-50', text: 'text-emerald-700', badge: 'bg-emerald-100 text-emerald-700' },
    amber: { border: 'border-amber-500', bg: 'bg-amber-50', text: 'text-amber-700', badge: 'bg-amber-100 text-amber-700' },
  }
  const c = colorMap[color]

  if (!isStreaming && items.length === 0) return null

  return (
    <div>
      <h3 className={`font-semibold text-sm border-b-2 pb-2 mb-3 flex items-center gap-2 ${c.border} ${c.text}`}>
        <span>{icon}</span> {title}
        {items.length > 0 && (
          <span className={`text-xs px-1.5 py-0.5 rounded-full ml-auto ${c.badge}`}>{items.length}</span>
        )}
      </h3>
      <div className="space-y-3">
        {items.map((item, idx) => (
          <div key={idx} className={`pl-4 border-l-2 ${c.border} py-1`}>
            <div className="flex items-start justify-between gap-2">
              <p className="font-medium text-slate-800 text-sm">{item.hypothesis}</p>
              {/* Verified / Non-verified badge */}
              {item.isTrusted !== undefined && (
                <span className={`flex-shrink-0 text-[10px] px-2 py-0.5 rounded-full whitespace-nowrap flex items-center gap-1 ${item.isTrusted
                  ? 'bg-emerald-100 text-emerald-700'
                  : 'bg-amber-100 text-amber-700'
                  }`}>
                  {item.isTrusted ? <Shield className="w-3 h-3" /> : <ShieldAlert className="w-3 h-3" />}
                  {item.isTrusted ? 'Verified' : 'Non-verified'}
                </span>
              )}
            </div>
            <p className="text-sm text-slate-600 mt-1">→ {item.evidence}</p>
            {item.source && (
              <a href={item.source} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-1 mt-1 text-xs text-primary hover:underline"
              >
                [{item.sourceName || item.sourceTitle || 'Source'}]
                {item.trustScore && <span className="text-slate-400">({item.trustScore}/10)</span>}
                <ExternalLink className="w-3 h-3" />
              </a>
            )}
          </div>
        ))}
        {isStreaming && items.length === 0 && (
          <div className="animate-pulse space-y-2">
            <div className="h-3 bg-slate-100 rounded w-3/4"></div>
            <div className="h-3 bg-slate-100 rounded w-1/2"></div>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Helpers ────────────────────────────────────────────────────────────────

async function exportReportAsPDF(report: ReportData) {
  const brand = (report.brand || 'brand').replace(/[^a-zA-Z0-9]/g, '_')
  const metric = (report.metrics?.[0] || 'report').replace(/[^a-zA-Z0-9]/g, '_')
  const filename = `${brand}_${metric}_analysis.pdf`

  const pdf = new jsPDF('p', 'mm', 'a4')
  const pageWidth = pdf.internal.pageSize.getWidth()
  const pageHeight = pdf.internal.pageSize.getHeight()
  const margin = 15
  const maxWidth = pageWidth - margin * 2
  let y = margin

  const checkPage = (needed: number) => {
    if (y + needed > pageHeight - margin) {
      pdf.addPage()
      y = margin
    }
  }

  const addText = (text: string, size: number, style: 'normal' | 'bold' = 'normal', color: [number, number, number] = [30, 30, 30]) => {
    pdf.setFontSize(size)
    pdf.setFont('helvetica', style)
    pdf.setTextColor(...color)
    const lines = pdf.splitTextToSize(text, maxWidth)
    const lineHeight = size * 0.45
    for (const line of lines) {
      checkPage(lineHeight)
      pdf.text(line, margin, y)
      y += lineHeight
    }
  }

  const addSpacer = (h: number) => { y += h }

  // ── Title ──
  addText(`${report.brand || 'Brand'} — ${(report.metrics || ['Analysis']).join(', ')} Analysis`, 18, 'bold', [20, 20, 80])
  addSpacer(2)
  addText(`Generated ${new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })}`, 9, 'normal', [120, 120, 120])
  addSpacer(6)

  // ── Executive Summary ──
  if (report.executiveSummary) {
    addText('Executive Summary', 13, 'bold', [30, 30, 30])
    addSpacer(2)
    addText(report.executiveSummary, 10, 'normal', [50, 50, 50])
    addSpacer(6)
  }

  // ── Sections ──
  const sectionLabels: Record<string, string> = {
    market: 'Market & Macro Drivers',
    brand: 'Brand-specific Insights',
    competitive: 'Competitive Landscape',
  }

  for (const cat of ['market', 'brand', 'competitive'] as const) {
    const items = report.sections?.[cat]
    if (!items || items.length === 0) continue

    // Section header
    checkPage(12)
    addText(`${sectionLabels[cat]} (${items.length})`, 13, 'bold', [30, 30, 80])
    addSpacer(3)

    for (const f of items) {
      checkPage(18)

      // Hypothesis
      addText(`• ${f.hypothesis || 'Hypothesis'}`, 10, 'bold')
      addSpacer(1)

      // Evidence
      if (f.evidence) {
        addText(`  → ${f.evidence}`, 9, 'normal', [60, 60, 60])
        addSpacer(1)
      }

      // Source + score
      const parts: string[] = []
      if (f.sourceName) parts.push(`[${f.sourceName}]`)
      if (f.trustScore != null) parts.push(`(${f.trustScore}/10)`)
      if (f.status) parts.push(f.status === 'verified' ? '✓ Verified' : '✗ Non-verified')
      if (parts.length) {
        addText(`  ${parts.join(' ')}`, 8, 'normal', [100, 100, 100])
      }
      addSpacer(4)
    }

    addSpacer(4)
  }

  // ── Telemetry footer ──
  const hasStats = report.webSearches || report.llmCalls || report.tokensIn || report.latencyMs
  if (hasStats) {
    checkPage(12)
    const stats = [
      report.webSearches && `Searches: ${report.webSearches}`,
      report.llmCalls && `LLM calls: ${report.llmCalls}`,
      report.tokensIn && `Tokens: ${report.tokensIn.toLocaleString()}`,
      report.latencyMs && `Duration: ${(report.latencyMs / 1000).toFixed(1)}s`,
    ].filter(Boolean).join('  •  ')
    if (stats) {
      addText('─'.repeat(60), 8, 'normal', [200, 200, 200])
      addSpacer(2)
      addText(stats, 8, 'normal', [140, 140, 140])
    }
  }

  const blob = pdf.output('blob')
  await saveBlobAsFile(blob, filename)
}

/**
 * Save a Blob to disk with a proper filename.
 * Primary: File System Access API (showSaveFilePicker) — native Save dialog.
 * Fallback: base64 data-URI anchor download.
 */
async function saveBlobAsFile(blob: Blob, filename: string) {
  // --- Method 1: File System Access API (Chrome 86+) ---
  if ('showSaveFilePicker' in window) {
    try {
      const handle = await (window as any).showSaveFilePicker({
        suggestedName: filename,
        types: [{
          description: 'PDF Document',
          accept: { 'application/pdf': ['.pdf'] },
        }],
      })
      const writable = await handle.createWritable()
      await writable.write(blob)
      await writable.close()
      console.log('[Export] Saved via File System Access API')
      return
    } catch (err: any) {
      if (err?.name === 'AbortError') return // user cancelled the dialog
      console.warn('[Export] showSaveFilePicker failed, falling back:', err)
    }
  }

  // --- Method 2: base64 data-URI anchor ---
  try {
    const reader = new FileReader()
    const dataUrl: string = await new Promise((resolve, reject) => {
      reader.onload = () => resolve(reader.result as string)
      reader.onerror = reject
      reader.readAsDataURL(blob)
    })
    const a = document.createElement('a')
    a.href = dataUrl
    a.download = filename
    a.style.display = 'none'
    document.body.appendChild(a)
    a.click()
    // Give the browser plenty of time before cleanup
    setTimeout(() => document.body.removeChild(a), 10000)
    console.log('[Export] Saved via data-URI anchor')
  } catch (err) {
    console.error('[Export] data-URI fallback also failed:', err)
    alert('PDF export failed. Please try again or use a different browser.')
  }
}
