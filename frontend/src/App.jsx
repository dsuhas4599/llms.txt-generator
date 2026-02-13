import { useState, useEffect } from 'react'
import './App.css'

const API_BASE = import.meta.env.VITE_API_URL || ''

function App() {
  const [sites, setSites] = useState([])
  const [sitesLoading, setSitesLoading] = useState(true)
  const [crawlingIds, setCrawlingIds] = useState([])
  const [addUrls, setAddUrls] = useState('')
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState(null)
  const [viewingSite, setViewingSite] = useState(null)
  const [viewingContent, setViewingContent] = useState(null)
  const [viewingLoading, setViewingLoading] = useState(false)
  const [panelWidth, setPanelWidth] = useState(480)
  const [isResizing, setIsResizing] = useState(false)

  useEffect(() => {
    if (crawlingIds.length === 0) return
    const interval = setInterval(() => {
      fetch(`${API_BASE}/api/sites`)
        .then((r) => r.ok ? r.json() : [])
        .then((data) => {
          setSites(data)
          setCrawlingIds((prev) =>
            prev.filter((id) => !data.find((s) => s.id === id && s.last_generated_at))
          )
        })
        .catch(() => {})
    }, 5000)
    return () => clearInterval(interval)
  }, [crawlingIds])

  useEffect(() => {
    fetch(`${API_BASE}/api/sites`)
      .then(async (r) => {
        if (r.ok) return r.json()
        const data = await r.json().catch(() => ({}))
        setError(data.detail || `Failed to load sites (${r.status})`)
        return []
      })
      .then(setSites)
      .catch((err) => {
        setError(err.message || 'Failed to load sites')
        setSites([])
      })
      .finally(() => setSitesLoading(false))
  }, [])

  function refetchSites() {
    fetch(`${API_BASE}/api/sites`)
      .then(async (r) => {
        if (r.ok) {
          setError(null)
          return r.json()
        }
        const data = await r.json().catch(() => ({}))
        setError(data.detail || `Failed to load sites (${r.status})`)
        return []
      })
      .then(setSites)
      .catch(() => setSites([]))
  }

  async function handleRefresh(siteId) {
    setCrawlingIds((prev) => [...prev, siteId])
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/api/sites/${siteId}/crawl`, { method: 'POST' })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) setError(data.detail || 'Crawl failed')
      else refetchSites()
    } catch (err) {
      setError(err.message || 'Network error')
    } finally {
      setCrawlingIds((prev) => prev.filter((id) => id !== siteId))
    }
  }

  const isValidUrl = (s) => /^https?:\/\/[^\s/$.?#].[^\s]*$/i.test(s.trim())

  async function handleAddSites(e) {
    e.preventDefault()
    const urls = addUrls
      .split(',')
      .map((u) => u.trim())
      .filter(Boolean)
    if (urls.length === 0) {
      setError('Enter one or more website URLs, comma-separated.')
      return
    }
    const invalid = urls.filter((u) => !isValidUrl(u))
    if (invalid.length) {
      setError(`Invalid URL(s): ${invalid.slice(0, 3).join(', ')}${invalid.length > 3 ? '…' : ''}`)
      return
    }
    setAdding(true)
    setError(null)
    const createdIds = []
    try {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), 45000)
      try {
        for (const u of urls) {
          const res = await fetch(`${API_BASE}/api/sites`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: u }),
            signal: controller.signal,
          })
          const data = await res.json().catch(() => ({}))
          if (res.ok && data.id) createdIds.push(data.id)
          else if (res.status === 409) setError(data.detail || `${u} already exists in your sites`)
          else setError(data.detail || `Failed to add ${u}`)
        }
      } finally {
        clearTimeout(timeoutId)
      }
      setAddUrls('')
      refetchSites()
      if (createdIds.length) {
        setCrawlingIds((prev) => [...prev, ...createdIds])
      }
    } catch (err) {
      const msg = err.name === 'AbortError'
        ? 'Request timed out. Is the backend running?'
        : (err.message || 'Network error')
      setError(msg)
    } finally {
      setAdding(false)
    }
  }

  function handleShowSite(site) {
    setViewingSite(site)
    setViewingContent(null)
    setViewingLoading(true)
    setError(null)
    fetch(`${API_BASE}/api/sites/${site.id}/llms.txt`)
      .then((r) => {
        if (!r.ok) throw new Error('No llms.txt yet')
        return r.text()
      })
      .then(setViewingContent)
      .catch((err) => setError(err.message))
      .finally(() => setViewingLoading(false))
  }

  function handleClosePanel() {
    setViewingSite(null)
    setViewingContent(null)
  }

  useEffect(() => {
    if (!isResizing) return
    const minW = 280
    const maxW = Math.min(800, window.innerWidth * 0.85)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    function onMove(e) {
      const w = window.innerWidth - e.clientX
      setPanelWidth(Math.min(maxW, Math.max(minW, w)))
    }
    function onUp() {
      setIsResizing(false)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
  }, [isResizing])

  function handleCopyFromPanel() {
    if (!viewingContent) return
    navigator.clipboard.writeText(viewingContent).then(() => setError(null))
  }

  function handleDownloadFromPanel() {
    if (!viewingContent) return
    const blob = new Blob([viewingContent], { type: 'text/plain;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'llms.txt'
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <div className="app-layout">
      <div className="app-main">
        <header className="header">
          <h1>llms.txt Generator</h1>
          <p className="tagline">Generate <a href="https://llmstxt.org/" target="_blank" rel="noopener noreferrer">llms.txt</a> files for your monitored sites</p>
        </header>

        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}

        <section className="sites">
          <h2>Your sites</h2>
          <form onSubmit={handleAddSites} className="form-inline">
            <input
              type="text"
              placeholder="https://example.com, https://other.com"
              value={addUrls}
              onChange={(e) => setAddUrls(e.target.value)}
              disabled={adding}
              className="input-inline input-urls"
            />
            <button type="submit" className="btn-secondary" disabled={adding || !addUrls.trim()}>
              {adding ? 'Adding…' : 'Add & crawl'}
            </button>
          </form>
          <p className="muted hint">Enter one or more URLs (comma-separated). Sites are added with monitoring enabled and crawled immediately.</p>
          {sitesLoading ? (
            <p className="muted">Loading…</p>
          ) : sites.length === 0 ? (
            <p className="muted">No sites yet. Add URL(s) above and click Add & crawl.</p>
          ) : (
            <ul className="sites-list">
              {sites.map((s) => (
                <li key={s.id} className="site-row">
                  <div className="site-info">
                    <span className="site-url">{s.root_url}</span>
                    {s.last_generated_at && (
                      <span className="site-meta">Updated {new Date(s.last_generated_at).toLocaleDateString()}</span>
                    )}
                  </div>
                  <div className="site-actions">
                    <button
                      type="button"
                      className="btn-secondary btn-sm"
                      onClick={() => handleRefresh(s.id)}
                      disabled={crawlingIds.includes(s.id)}
                    >
                      {crawlingIds.includes(s.id) ? 'Crawling…' : 'Refresh'}
                    </button>
                    {s.last_generated_at && (
                      <button
                        type="button"
                        className="btn-secondary btn-sm"
                        onClick={() => handleShowSite(s)}
                      >
                        Show
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <aside
        className={`panel ${viewingSite ? 'panel-open' : ''} ${isResizing ? 'panel-resizing' : ''}`}
        style={viewingSite ? { width: panelWidth } : undefined}
      >
        {viewingSite && (
          <>
            <div
              className="panel-resize-handle"
              onMouseDown={(e) => { e.preventDefault(); setIsResizing(true) }}
            />
            <div className="panel-header">
              <span className="panel-url">{viewingSite.root_url}</span>
              <button type="button" className="btn-close" onClick={handleClosePanel} aria-label="Close">
                ×
              </button>
            </div>
            <div className="panel-actions">
              <button type="button" className="btn-secondary btn-sm" onClick={handleCopyFromPanel} disabled={!viewingContent}>
                Copy
              </button>
              <button type="button" className="btn-secondary btn-sm" onClick={handleDownloadFromPanel} disabled={!viewingContent}>
                Download
              </button>
            </div>
            <div className="panel-content">
              {viewingLoading ? (
                <p className="muted">Loading…</p>
              ) : (
                <pre className="output"><code>{viewingContent}</code></pre>
              )}
            </div>
          </>
        )}
      </aside>
    </div>
  )
}

export default App
