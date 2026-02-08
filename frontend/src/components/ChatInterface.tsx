import { useState, useRef, useEffect } from 'react'
import { Send, Loader2, ExternalLink, Sparkles } from 'lucide-react'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
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

const MOCK_RESPONSE: Message = {
  id: '2',
  role: 'assistant',
  content: 'Based on my research, here are the external factors that may have contributed to the decrease in mental availability:',
  thinking: [
    '✅ Online shopping shift reduces high-street exposure',
    '❌ Competitor advertising increase',
    '✅ Store closures in key locations',
    '✅ Economic downturn affecting fashion spending',
    '❌ Celebrity partnership campaign',
  ],
  drivers: {
    macro: [
      {
        hypothesis: 'Online shopping shift reduces high-street brand exposure',
        evidence: 'UK online fashion sales grew 12.3% in 2025, while high-street footfall declined 8.7%. Less incidental brand encounters.',
        source: 'ft.com',
        url: 'https://ft.com/fashion-retail-2025'
      },
      {
        hypothesis: 'Economic downturn affecting discretionary spending',
        evidence: '77% of UK adults plan to reduce fashion spending in 2025 due to cost-of-living pressures.',
        source: 'marketingweek.com',
        url: 'https://marketingweek.com/uk-consumer-spending'
      },
      {
        hypothesis: 'Competitor media dominance in Q3 2025',
        evidence: 'Rivals increased marketing spend by estimated 15-20% during same period, capturing consumer attention.',
        source: 'thedrum.com',
        url: 'https://thedrum.com/fashion-marketing'
      }
    ],
    brand: [
      {
        hypothesis: 'Closure of key high-street stores',
        evidence: 'New Look closed 12 underperforming stores in Q3 2025, reducing physical brand presence in major shopping areas.',
        source: 'bloomberg.com',
        url: 'https://bloomberg.com/new-look-stores'
      }
    ],
    competitive: [
      {
        hypothesis: 'Zara celebrity tie-in campaign',
        evidence: 'Zara launched major celebrity partnership in September 2025, generating significant media coverage and social buzz.',
        source: 'adage.com',
        url: 'https://adage.com/zara-campaign'
      },
      {
        hypothesis: 'H&M AI-powered digital campaign',
        evidence: 'H&M introduced AI-driven personalization campaign with heavy digital ad spend across Q3 2025.',
        source: 'campaignlive.com',
        url: 'https://campaignlive.com/hm-ai'
      },
      {
        hypothesis: 'M&S heavy media coverage',
        evidence: 'Marks & Spencer dominated fashion trade press in Q3 with sustainability initiative and new collection launches.',
        source: 'marketingweek.com',
        url: 'https://marketingweek.com/ms-coverage'
      }
    ]
  }
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
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

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

    // Simulate API delay
    await new Promise(resolve => setTimeout(resolve, 2000))

    setMessages(prev => [...prev, MOCK_RESPONSE])
    setIsLoading(false)
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
