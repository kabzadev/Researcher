import { useState } from 'react'
import './index.css'
import { Layout } from './components/Layout'
import { ChatInterface } from './components/ChatInterface'

function App() {
  const [sidebarOpen, setSidebarOpen] = useState(true)

  return (
    <Layout sidebarOpen={sidebarOpen} onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}>
      <ChatInterface />
    </Layout>
  )
}

export default App
