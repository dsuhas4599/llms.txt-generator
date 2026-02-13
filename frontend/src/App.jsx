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
      for (const siteId of createdIds) {
        setCrawlingIds((prev) => [...prev, siteId])
        fetch(`${API_BASE}/api/sites/${siteId}/crawl`, { method: 'POST' })
          .then((r) => r.json().catch(() => ({})))
          .then(() => refetchSites())
          .catch(() => {})
          .finally(() => {
            setCrawlingIds((prev) => prev.filter((id) => id !== siteId))
            refetchSites()
          })
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

  function handleDownloadSite(siteId) {
    fetch(`${API_BASE}/api/sites/${siteId}/llms.txt`)
      .then((r) => {
        if (!r.ok) throw new Error('No llms.txt yet')
        return r.text()
      })
      .then((text) => {
        const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
        const a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = 'llms.txt'
        a.click()
        URL.revokeObjectURL(a.href)
      })
      .catch((err) => setError(err.message))
  }

  return (
    <div className="app">
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
                  <button
                    type="button"
                    className="btn-secondary btn-sm"
                    onClick={() => handleDownloadSite(s.id)}
                    disabled={!s.last_generated_at}
                  >
                    Download
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

export default App
