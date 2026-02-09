import { useState } from 'react'
import './index.css'
import { Layout } from './components/Layout'
import { ChatInterface } from './components/ChatInterface'
import { Dashboard } from './components/Dashboard'

type Page = 'research' | 'dashboard'

function App() {
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [page, setPage] = useState<Page>('research')

  return (
    <Layout
      sidebarOpen={sidebarOpen}
      onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
      page={page}
      onSelectPage={setPage}
    >
      {page === 'research' ? <ChatInterface /> : <Dashboard />}
    </Layout>
  )
}

export default App
