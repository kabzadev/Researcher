import { Menu, X, Search, MessageSquare, Settings, FileText } from 'lucide-react'

interface LayoutProps {
  children: React.ReactNode
  sidebarOpen: boolean
  onToggleSidebar: () => void
}

export function Layout({ children, sidebarOpen, onToggleSidebar }: LayoutProps) {
  return (
    <div className="flex h-screen bg-slate-50">
      {/* Left Sidebar */}
      <aside
        className={`bg-white border-r border-slate-200 transition-all duration-300 ${
          sidebarOpen ? 'w-64' : 'w-0 overflow-hidden'
        }`}
      >
        <div className="p-4 border-b border-slate-200">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-primary rounded-lg flex items-center justify-center">
              <Search className="w-5 h-5 text-white" />
            </div>
            <span className="font-semibold text-slate-800">Researcher</span>
          </div>
        </div>

        <nav className="p-2">
          <NavItem icon={<MessageSquare className="w-4 h-4" />} label="New Research" active />
          <NavItem icon={<FileText className="w-4 h-4" />} label="History" />
          <NavItem icon={<Settings className="w-4 h-4" />} label="Settings" />
        </nav>

        <div className="absolute bottom-0 w-full p-4 border-t border-slate-200 bg-white">
          <div className="text-xs text-slate-500">
            <p className="font-medium">Researcher v0.1</p>
            <p>Hypothesis-driven research</p>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="bg-white border-b border-slate-200 px-4 py-3 flex items-center gap-3">
          <button
            onClick={onToggleSidebar}
            className="p-2 hover:bg-slate-100 rounded-lg transition-colors"
          >
            {sidebarOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
          <h1 className="font-semibold text-slate-800">Research Assistant</h1>
          <div className="flex-1" />
          <div className="flex items-center gap-2">
            <span className="px-3 py-1 bg-primary/10 text-primary text-sm rounded-full">
              Beta
            </span>
          </div>
        </header>

        {/* Page Content */}
        <main className="flex-1 overflow-hidden">
          {children}
        </main>
      </div>
    </div>
  )
}

function NavItem({ icon, label, active = false }: { icon: React.ReactNode; label: string; active?: boolean }) {
  return (
    <a
      href="#"
      className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
        active
          ? 'bg-primary/10 text-primary font-medium'
          : 'text-slate-600 hover:bg-slate-100'
      }`}
    >
      {icon}
      {label}
    </a>
  )
}
