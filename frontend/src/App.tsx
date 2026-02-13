import { useState } from 'react'
import './index.css'
import { Layout } from './components/Layout'
import { ChatInterface } from './components/ChatInterface'
import { Dashboard } from './components/Dashboard'
import { Eval } from './components/Eval'
import { History } from './components/History'
import { Settings } from './components/Settings'

type Page = 'research' | 'history' | 'dashboard' | 'eval' | 'settings'

function App() {
  const [sidebarOpen, setSidebarOpen] = useState(() => {
    // Default: closed on mobile, open on desktop
    if (typeof window === 'undefined') return true
    return window.innerWidth >= 768
  })
  const [page, setPage] = useState<Page>('research')

  return (
    <Layout
      sidebarOpen={sidebarOpen}
      onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
      page={page}
      onSelectPage={setPage}
    >
      {page === 'research' ? <ChatInterface /> : page === 'history' ? <History /> : page === 'dashboard' ? <Dashboard /> : page === 'settings' ? <Settings /> : <Eval />}
    </Layout>
  )
}

export default App
