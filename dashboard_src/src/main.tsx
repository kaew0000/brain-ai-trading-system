import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'

/**
 * Global Error Boundary — catches render errors anywhere in the tree
 * and shows a branded recovery UI instead of a blank screen.
 */
class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean; error?: Error }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="h-screen flex items-center justify-center bg-surface text-text-primary font-mono p-6">
          <div className="max-w-md w-full space-y-5 text-center border border-border rounded-lg p-6 bg-surface-1">
            <div className="text-4xl">⚠</div>
            <h1 className="text-lg font-bold tracking-wider">DASHBOARD ERROR</h1>
            <p className="text-sm text-text-secondary leading-relaxed">
              {this.state.error?.message || 'An unexpected error occurred in the UI.'}
            </p>
            <button
              onClick={() => window.location.reload()}
              className="px-5 py-2 bg-accent-blue/20 border border-accent-blue/50 rounded text-xs font-bold tracking-wider hover:bg-accent-blue/30 transition-colors focus:outline-none focus:ring-2 focus:ring-accent-blue/50"
            >
              RELOAD DASHBOARD
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </BrowserRouter>
  </React.StrictMode>
)
