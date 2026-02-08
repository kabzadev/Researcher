import { useState, useRef, useEffect } from 'react'
import { Send, Loader2, ExternalLink, Sparkles } from 'lucide-react'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  provider?: string
  drivers?: {
    macro: Driver[]
    brand: Driver[]
    competitive: Driver[]
  }
  thinking?: string[]
}

interface Driver {
  hypothesis: string
  evidence: string
  source?: string
  url?: string
}

export function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '1',
      role: 'assistant',
      content: 'Hello! I\'m your research assistant. I can help you understand changes in brand metrics by researching external factors.\n\n**Currently supported:** Questions about Salient (mental availability) changes for fashion retail brands.\n\n**Example:** "Salience fell by 6 points in Q3 2025 for new look, can you help find external reasons for decreased mental availability?"'
    }
  ])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [provider, setProvider] = useState<'anthropic' | 'openai'>('anthropic')
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const API_URL = 'https://researcher-api.thankfulwave-8ed54622.eastus2.azurecontainerapps.io'

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

    try {
      // Create a placeholder assistant message we will update as SSE events arrive
      const assistantId = (Date.now() + 1).toString()
      setMessages(prev => [
        ...prev,
        {
          id: assistantId,
          role: 'assistant',
          content: 'Researching…',
          provider
        }
      ])

      const response = await fetch(`${API_URL}/research/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: input, provider })
      })

      if (!response.ok) {
        throw new Error(`API error: ${response.status}`)
      }

      if (!response.body) {
        throw new Error('Streaming not supported by browser')
      }

      const decoder = new TextDecoder()
      const reader = response.body.getReader()
      let buffer = ''

      const extractHostname = (url: string): string => {
        try {
          return new URL(url).hostname.replace('www.', '')
        } catch {
          return 'Source'
        }
      }

      const transformDriver = (d: any): Driver => ({
        hypothesis: d.hypothesis || '',
        evidence: d.driver || d.evidence || '',
        url: d.source_urls?.[0] || d.source || d.url || '',
        source: d.source_title || (d.source_urls?.[0] ? extractHostname(d.source_urls[0]) : d.source ? extractHostname(d.source) : 'Source')
      })

      const updateAssistant = (patch: Partial<Message>) => {
        setMessages(prev => prev.map(m => (m.id === assistantId ? { ...m, ...patch } : m)))
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
          try {
            data = JSON.parse(raw)
          } catch {
            continue
          }

          if (event === 'status') {
            if (data.stage === 'search') {
              updateAssistant({ content: `Researching… (0/${data.total_hypotheses || 0})` })
            }
          }

          if (event === 'hypothesis_result') {
            const completed = data.completed || 0
            const total = data.total || 0
            updateAssistant({ content: `Researching… (${completed}/${total})` })
          }

          if (event === 'final') {
            const hasFindings =
              (data.summary?.macro_drivers?.length || 0) > 0 ||
              (data.summary?.brand_drivers?.length || 0) > 0 ||
              (data.summary?.competitive_drivers?.length || 0) > 0

            let assistantMessage: Message

            if (!hasFindings) {
              assistantMessage = {
                id: assistantId,
                role: 'assistant',
                content: `I researched **${data.brand}** for the ${data.direction} in ${data.metrics?.[0] || 'salience'}, but no validating evidence was found from web searches.\n\nThis could mean:\n• The news hasn't been indexed yet\n• The search queries need refinement\n• No major external factors were reported during this period`,
                provider: data.provider_used || provider,
                thinking: [
                  ...(data.validated_hypotheses?.market || []).map((h: any) => `❌ ${h.hypothesis} (no evidence)`),
                  ...(data.validated_hypotheses?.brand || []).map((h: any) => `❌ ${h.hypothesis} (no evidence)`),
                  ...(data.validated_hypotheses?.competitive || []).map((h: any) => `❌ ${h.hypothesis} (no evidence)`)
                ],
                drivers: { macro: [], brand: [], competitive: [] }
              }
            } else {
              assistantMessage = {
                id: assistantId,
                role: 'assistant',
                content: `Based on my research for **${data.brand}**, here are the external factors that may have contributed to the ${data.direction} in ${data.metrics?.[0] || 'salience'}:`,
                provider: data.provider_used || provider,
                thinking: [
                  ...(data.validated_hypotheses?.market || []).map((h: any) => `✅ ${h.hypothesis}`),
                  ...(data.validated_hypotheses?.brand || []).map((h: any) => `✅ ${h.hypothesis}`),
                  ...(data.validated_hypotheses?.competitive || []).map((h: any) => `✅ ${h.hypothesis}`)
                ],
                drivers: {
                  macro: (data.summary?.macro_drivers || []).map(transformDriver),
                  brand: (data.summary?.brand_drivers || []).map(transformDriver),
                  competitive: (data.summary?.competitive_drivers || []).map(transformDriver)
                }
              }
            }

            // Replace placeholder with final structured message
            setMessages(prev => prev.map(m => (m.id === assistantId ? assistantMessage : m)))
          }
        }
      }
    } catch (error: any) {
      let errorMsg = "Sorry, there was an error processing your request."
      
      if (error.response?.status === 402) {
        errorMsg = "⚠️ **API Credits Exhausted**\n\nThe Anthropic API key has no remaining credits. Please add credits at:\nhttps://console.anthropic.com/settings/plans\n\nAlternatively, we can switch to OpenAI if you have credits there."
      } else if (error.response?.status === 500) {
        errorMsg = "⚠️ **Server Error**\n\nThe research service encountered an error. Please try again in a moment."
      } else if (error.message?.includes('CORS')) {
        errorMsg = "⚠️ **Connection Error**\n\nCannot connect to the research API. The service may be starting up (cold start takes ~30 seconds). Please try again."
      }
      
      setMessages(prev => [...prev, {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: errorMsg
      }])
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="flex flex-col h-full max-w-4xl mx-auto">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-3 ${
                message.role === 'user'
                  ? 'bg-primary text-white'
                  : 'bg-white border border-slate-200 shadow-sm'
              }`}
            >
              {/* Provider badge for assistant messages */}
              {message.role === 'assistant' && message.provider && (
                <div className="mb-2">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    message.provider === 'anthropic' 
                      ? 'bg-violet-100 text-violet-700' 
                      : 'bg-emerald-100 text-emerald-700'
                  }`}>
                    {message.provider === 'anthropic' ? '🤖 Claude' : '⚡ GPT'}
                  </span>
                </div>
              )}
              <div className="whitespace-pre-wrap">{message.content}</div>

              {/* Research Results */}
              {message.drivers && (
                <div className="mt-4 pt-4 border-t border-slate-200">
                  {/* Thinking Summary */}
                  {message.thinking && (
                    <details className="mb-4">
                      <summary className="cursor-pointer text-sm text-slate-500 flex items-center gap-2">
                        <Sparkles className="w-4 h-4" />
                        Thought process...
                      </summary>
                      <div className="mt-2 p-3 bg-slate-50 rounded-lg text-xs text-slate-600 space-y-1">
                        <p className="font-medium text-slate-700 mb-2">Hypotheses validated:</p>
                        {message.thinking.map((thought, i) => (
                          <div key={i}>{thought}</div>
                        ))}
                      </div>
                    </details>
                  )}

                  {/* Market News */}
                  <DriverSection
                    title="🌍 Market News"
                    color="blue"
                    drivers={message.drivers.macro}
                  />

                  {/* Brand News */}
                  <DriverSection
                    title="🏷️ Brand News (New Look)"
                    color="green"
                    drivers={message.drivers.brand}
                  />

                  {/* Competitor News */}
                  <DriverSection
                    title="⚔️ Competitor News"
                    color="amber"
                    drivers={message.drivers.competitive}
                  />
                </div>
              )}
            </div>
          </div>
        ))}

        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-white border border-slate-200 rounded-2xl px-4 py-3 flex items-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin text-primary" />
              <span className="text-sm text-slate-600">Researching...</span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Provider Toggle */}
      <div className="px-4 py-2 bg-slate-50 border-t border-slate-200">
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-500">LLM Provider:</span>
            <div className="flex gap-2">
              <button
                onClick={() => setProvider('anthropic')}
                disabled={isLoading}
                className={`px-3 py-1 text-xs rounded-full transition-colors ${
                  provider === 'anthropic'
                    ? 'bg-violet-600 text-white'
                    : 'bg-white text-slate-600 border border-slate-300 hover:bg-slate-100'
                } disabled:opacity-50`}
              >
                Anthropic
              </button>
              <button
                onClick={() => setProvider('openai')}
                disabled={isLoading}
                className={`px-3 py-1 text-xs rounded-full transition-colors ${
                  provider === 'openai'
                    ? 'bg-emerald-600 text-white'
                    : 'bg-white text-slate-600 border border-slate-300 hover:bg-slate-100'
                } disabled:opacity-50`}
              >
                OpenAI
              </button>
            </div>
          </div>
          <p className="text-[10px] text-slate-400">
            All API keys stored in Azure Key Vault • No inline secrets
          </p>
        </div>
      </div>

      {/* Input */}
      <div className="p-4 border-t border-slate-200 bg-white">
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSend()
              }
            }}
            placeholder="Ask about brand metric changes..."
            className="flex-1 resize-none rounded-xl border border-slate-300 px-4 py-3 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent min-h-[56px] max-h-32"
            rows={1}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            className="px-4 py-2 bg-primary text-white rounded-xl hover:bg-primary-dark disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          Press Enter to send, Shift+Enter for new line
        </p>
      </div>
    </div>
  )
}

function DriverSection({ title, color, drivers }: { title: string; color: 'blue' | 'green' | 'amber'; drivers: Driver[] }) {
  if (!drivers || drivers.length === 0) return null

  const colorClasses = {
    blue: 'border-blue-500 text-blue-700',
    green: 'border-emerald-500 text-emerald-700',
    amber: 'border-amber-500 text-amber-700'
  }

  return (
    <div className="mb-4 last:mb-0">
      <h3 className={`font-semibold text-sm border-b-2 pb-2 mb-3 ${colorClasses[color]}`}>
        {title}
      </h3>
      <div className="space-y-3">
        {drivers.map((driver, index) => (
          <div key={index} className="pl-3 border-l-2 border-slate-200">
            <p className="font-medium text-slate-800">• {driver.hypothesis}</p>
            <p className="text-sm text-slate-600 mt-1 ml-4">
              → {driver.evidence}
              {driver.url && (
                <a
                  href={driver.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 ml-2 text-primary hover:underline text-xs"
                >
                  [{driver.source}]
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
