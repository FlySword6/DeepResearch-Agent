import React, { useState, useCallback, useEffect } from 'react'
import InputPanel from './components/InputPanel'
import AgentTrace from './components/AgentTrace'
import ReportViewer from './components/ReportViewer'
import SettingsModal from './components/SettingsModal'
import SkillsModal from './components/SkillsModal'
import ProfileModal from './components/ProfileModal'
import AuthModal from './components/AuthModal'
import { AuthProvider, useAuth } from './contexts/AuthContext'

const NAV_ITEMS = [
  { label: '研究', id: 'research' },
  { label: '历史', id: 'history' },
]

// Keeps one live SSE connection per *running* task so every task streams
// independently; switching views only changes which task is displayed.
function TaskStream({ taskId, onEvent }) {
  React.useEffect(() => {
    if (!taskId) return undefined
    const es = new EventSource(`/api/research/${taskId}/stream`)
    es.onopen = () => onEvent(taskId, 'connected', {})
    es.onmessage = (event) => {
      try {
        onEvent(taskId, 'message', JSON.parse(event.data))
      } catch {}
    }
    const types = [
      'agent_status',
      'agent_result',
      'skills_matched',
      'tool_call',
      'tool_result',
      'report_chunk',
      'node_error',
      'completed',
      'error',
    ]
    types.forEach((t) => {
      es.addEventListener(t, (event) => {
        try {
          onEvent(taskId, t, JSON.parse(event.data))
        } catch {}
        if (t === 'completed' || t === 'error') es.close()
      })
    })
    return () => es.close()
  }, [taskId, onEvent])
  return null
}

function AppInner() {
  const [theme, setTheme] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('theme') || 'light'
    }
    return 'light'
  })
  const [tasks, setTasks] = useState({}) // taskId -> { id, task, status, reportContent, error, events, isConnected }
  const [activeTaskId, setActiveTaskId] = useState(null)
  const [history, setHistory] = useState([])
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [activeTab, setActiveTab] = useState('research')
  const [histBatchMode, setHistBatchMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState([])
  const [histPage, setHistPage] = useState(1)
  const HIST_PER_PAGE = 999
  const histTotalPages = React.useMemo(() => Math.max(1, Math.ceil(history.length / HIST_PER_PAGE)), [history])
  const pagedHistory = React.useMemo(() => history.slice((histPage - 1) * HIST_PER_PAGE, histPage * HIST_PER_PAGE), [history, histPage])
  const [showSettings, setShowSettings] = useState(false)
  const [settingsConfigured, setSettingsConfigured] = useState(null)
  const [showAuth, setShowAuth] = useState(false)
  const [authMode, setAuthMode] = useState('login') // login | register
  const [showSkills, setShowSkills] = useState(false)
  const [showProfile, setShowProfile] = useState(false)

  const { user, logout, authFetch } = useAuth()

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('theme', theme)
  }, [theme])

  const toggleTheme = () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))

  const fetchHistory = useCallback(async () => {
    try {
      const response = await authFetch('/api/history?per_page=100')
      if (response.ok) {
        const data = await response.json()
        setHistory(data.tasks || data || [])
      }
    } catch {}
  }, [authFetch])

  const runningTasks = React.useMemo(
    () => Object.values(tasks).filter((t) => t.status === 'running'),
    [tasks]
  )
  const activeTask = activeTaskId ? tasks[activeTaskId] || null : null
  const activeStatus = activeTask?.status || 'idle'
  const activeReport = activeTask?.reportContent || ''
  const activeEvents = activeTask?.events || []
  const isConnected = !!activeTask?.isConnected
  const isResearching = activeStatus === 'running'
  const hasActiveResearch = !!activeTask

  // Per-task live events: update the task entry and refresh history on completion.
  const handleTaskEvent = useCallback(
    (taskId, type, data) => {
      setTasks((prev) => {
        const t = prev[taskId]
        if (!t) return prev
        const entry = {
          ...t,
          events: [...t.events, { type, data, timestamp: new Date().toISOString() }],
        }
        if (type === 'connected') entry.isConnected = true
        if (type === 'report_chunk' && data?.chunk) entry.reportContent += data.chunk
        if (type === 'completed') {
          entry.status = 'completed'
          if (data?.report) entry.reportContent = data.report
        }
        if (type === 'error') {
          entry.status = 'failed'
          entry.error = data?.message || '发生错误'
        }
        return { ...prev, [taskId]: entry }
      })
      if (type === 'completed') fetchHistory()
    },
    [fetchHistory]
  )

  const hydrateCompletedTask = useCallback(async (taskId) => {
    const [reportResponse, eventsResponse] = await Promise.all([
      authFetch(`/api/reports/${taskId}?format=markdown`),
      authFetch(`/api/research/${taskId}/events`),
    ])
    const content = reportResponse.ok ? await reportResponse.text() : ''
    const eventPayload = eventsResponse.ok
      ? await eventsResponse.json().catch(() => ({ events: [] }))
      : { events: [] }

    setTasks((prev) => {
      const existing = prev[taskId]
      if (!existing) return prev
      return {
        ...prev,
        [taskId]: {
          ...existing,
          status: content ? 'completed' : existing.status,
          reportContent: content || existing.reportContent,
          events: eventPayload.events?.length ? eventPayload.events : existing.events,
          isConnected: false,
        },
      }
    })
    if (content) fetchHistory()
  }, [authFetch, fetchHistory])

  useEffect(() => {
    if (runningTasks.length === 0) return undefined

    const timer = window.setInterval(() => {
      runningTasks.forEach(async (task) => {
        try {
          const statusResponse = await authFetch(`/api/research/${task.id}`)
          if (statusResponse.ok) {
            const statusPayload = await statusResponse.json()
            if (statusPayload.status === 'completed' || statusPayload.status === 'failed') {
              await hydrateCompletedTask(task.id)
              if (statusPayload.status === 'failed') {
                setTasks((prev) => ({
                  ...prev,
                  [task.id]: {
                    ...prev[task.id],
                    status: 'failed',
                    error: statusPayload.errors?.[0] || prev[task.id]?.error || '任务执行失败',
                    isConnected: false,
                  },
                }))
              }
            }
            return
          }

          if (statusResponse.status === 404) {
            await hydrateCompletedTask(task.id)
          }
        } catch {}
      })
    }, 3000)

    return () => window.clearInterval(timer)
  }, [runningTasks, authFetch, hydrateCompletedTask])

  // Load history on mount
  useEffect(() => {
    fetchHistory()
  }, [fetchHistory])

  // Check if LLM is configured — auto-show settings if not
  useEffect(() => {
    fetch('/api/settings')
      .then((r) => r.json())
      .then((data) => {
        setSettingsConfigured(data.configured)
        if (!data.configured) setShowSettings(true)
      })
      .catch(() => setSettingsConfigured(false))
  }, [])

  const handleSubmit = useCallback(async ({ task, depth, useRag, engine, files = [] }) => {
    setError(null)
    setSubmitting(true)
    const depthMap = { quick: 1, standard: 3, deep: 5 }
    const maxIterations = depthMap[depth] || 3

    const registerTask = (id) => {
      setTasks((prev) => ({
        ...prev,
        [id]: { id, task, status: 'running', reportContent: '', error: null, events: [], isConnected: false },
      }))
      setActiveTaskId(id)
    }

    try {
      if (files && files.length > 0) {
        // 1. Pre-create the task (no workflow started)
        const prep = await authFetch('/api/research/prepare', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ task }),
        })
        if (!prep.ok) {
          const d = await prep.json().catch(() => ({}))
          setError(d.detail || '创建任务失败')
          return
        }
        const { task_id } = await prep.json()

        // 2. Upload each file sequentially. DO NOT set Content-Type on FormData.
        for (const f of files) {
          const fd = new FormData()
          fd.append('file', f.file)
          const up = await authFetch(`/api/research/${task_id}/upload`, { method: 'POST', body: fd })
          if (!up.ok) {
            const d = await up.json().catch(() => ({}))
            setError(`上传 ${f.name} 失败: ${d.detail || '未知错误'}`)
            return
          }
        }

        // 3. Start the prepared task
        const start = await authFetch(`/api/research/${task_id}/start`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ max_iterations: maxIterations, format: 'markdown', use_rag: useRag, engine }),
        })
        if (!start.ok) {
          const d = await start.json().catch(() => ({}))
          setError(d.detail || '启动任务失败')
          return
        }
        registerTask(task_id)
      } else {
        // Existing direct flow (unchanged behavior)
        const response = await authFetch('/api/research', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ task, max_iterations: maxIterations, format: 'markdown', use_rag: useRag, engine }),
        })
        if (!response.ok) {
          const errData = await response.json().catch(() => ({}))
          setError(errData.detail || `HTTP ${response.status}: 研究请求失败`)
          return
        }
        const data = await response.json()
        registerTask(data.task_id)
      }
    } catch (err) {
      setError(err.message || '启动研究任务失败')
    } finally {
      setSubmitting(false)
    }
  }, [authFetch])

  const handleViewHistory = useCallback(async (historyTaskId) => {
    if (!historyTaskId) return
    const existing = tasks[historyTaskId]
    const histItem = history.find(
      (h) => (h.task_id || h.report_id) === historyTaskId
    )
    const isRunning =
      existing?.status === 'running' ||
      (!existing && histItem?.status === 'running')
    if (isRunning) {
      setTasks((prev) =>
        prev[historyTaskId]
          ? prev
          : {
              ...prev,
              [historyTaskId]: {
                id: historyTaskId,
                task: histItem?.task || historyTaskId,
                status: 'running',
                reportContent: '',
                error: null,
                events: [],
                isConnected: false,
              },
            }
      )
      setActiveTaskId(historyTaskId)
      setActiveTab('research')
      return
    }
    if (existing && existing.reportContent) {
      setActiveTaskId(historyTaskId)
      setActiveTab('research')
      return
    }
    try {
      const [response, eventsResponse] = await Promise.all([
        authFetch(`/api/reports/${historyTaskId}?format=markdown`),
        authFetch(`/api/research/${historyTaskId}/events`),
      ])
      if (response.ok) {
        const content = await response.text()
        const eventPayload = eventsResponse.ok
          ? await eventsResponse.json().catch(() => ({ events: [] }))
          : { events: [] }
        setTasks((prev) => ({
          ...prev,
          [historyTaskId]: {
            id: historyTaskId,
            task: histItem?.task || prev[historyTaskId]?.task || historyTaskId,
            status: 'completed',
            reportContent: content,
            error: null,
            events: eventPayload.events || prev[historyTaskId]?.events || [],
            isConnected: false,
          },
        }))
        setActiveTaskId(historyTaskId)
        setActiveTab('research')
      }
    } catch {}
  }, [authFetch, tasks, history])

  const handleReset = useCallback(() => {
    setActiveTaskId(null)
    setError(null)
    setActiveTab('research')
    setHistBatchMode(false)
    setSelectedIds([])
    setHistPage(1)
  }, [])

  const handleNavClick = useCallback((tabId) => {
    if (tabId === 'research') {
      handleReset()
      return
    }
    setActiveTab(tabId)
  }, [handleReset])

  const handleBatchDelete = useCallback(async () => {
    if (selectedIds.length === 0) return
    try {
      const response = await authFetch('/api/reports/batch-delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(selectedIds),
      })
      if (response.ok) {
        setSelectedIds([])
        setHistBatchMode(false)
        fetchHistory()
      }
    } catch {}
  }, [selectedIds, authFetch, fetchHistory])

  const toggleSelectId = useCallback((id) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    )
  }, [])

  return (
    <div className="min-h-screen bg-[var(--surface)] flex">
      {/* Sidebar */}
      <aside className="w-60 shrink-0 h-screen sticky top-0 flex flex-col glass border-r border-[var(--border-subtle)] p-4">
        <div className="flex items-center gap-3 px-2 h-12">
          <span className="w-8 h-8 rounded-xl bg-gradient-to-br from-[var(--accent)] to-[var(--accent-2)] flex items-center justify-center text-white text-lg">
            🔬
          </span>
          <div>
            <h1 className="text-base font-semibold tracking-tight text-[var(--text-primary)]">
              DeepResearch<span className="text-[var(--accent)]"> Agent</span>
            </h1>
          </div>
        </div>

        <nav className="mt-4 space-y-1">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              onClick={() => handleNavClick(item.id)}
              className={`w-full flex items-center gap-2.5 px-3 py-2 text-sm rounded-lg transition-all ${
                activeTab === item.id
                  ? 'text-[var(--accent)] bg-[var(--accent-glow)] font-medium'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-[var(--surface-hover)]'
              }`}
            >
              <span>{item.id === 'research' ? '🔍' : '🕘'}</span>
              {item.label}
            </button>
          ))}
        </nav>

        <div className="mt-6 flex-1 overflow-y-auto">
          {runningTasks.length > 0 && (
            <>
              <p className="px-3 text-[11px] font-medium uppercase tracking-wider text-[var(--text-muted)] mb-2">
                运行中 ({runningTasks.length})
              </p>
              <div className="space-y-1">
                {runningTasks.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => { setActiveTaskId(t.id); setActiveTab('research') }}
                    className={`w-full text-left px-3 py-2 rounded-lg text-xs transition-all truncate ${
                      t.id === activeTaskId
                        ? 'bg-[var(--accent-glow)] text-[var(--accent)] font-medium border border-[var(--border-accent)]'
                        : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-hover)] border border-transparent'
                    }`}
                    title={t.task || t.id}
                  >
                    <span className="inline-block w-1.5 h-1.5 rounded-full bg-[var(--accent)] animate-pulse mr-1.5 align-middle" />
                    {t.task || t.id}
                  </button>
                ))}
              </div>
              <p className="px-3 text-[11px] font-medium uppercase tracking-wider text-[var(--text-muted)] mb-2 mt-4">最近</p>
            </>
          )}
          {runningTasks.length === 0 && (
            <p className="px-3 text-[11px] font-medium uppercase tracking-wider text-[var(--text-muted)] mb-2">最近</p>
          )}
          {history.length > 0 ? (
            <div className="space-y-1">
              {history
                .filter((item) => !tasks[item.task_id] || tasks[item.task_id].status !== 'running')
                .slice(0, 8)
                .map((item) => (
                <button
                  key={item.task_id || item.report_id}
                  onClick={() => handleViewHistory(item.task_id)}
                  className={`w-full text-left px-3 py-2 rounded-lg text-xs transition-all truncate ${
                    (item.task_id || item.report_id) === activeTaskId
                      ? 'bg-[var(--accent-glow)] text-[var(--accent)] font-medium border border-[var(--border-accent)]'
                      : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-[var(--surface-hover)] border border-transparent'
                  }`}
                  title={item.task || item.task_id}
                >
                  {item.task || item.task_id}
                </button>
                ))}
            </div>
          ) : (
            <p className="px-3 text-xs text-[var(--text-muted)]">暂无记录</p>
          )}
        </div>

        <div className="pt-3 border-t border-[var(--border-subtle)]">
          {user ? (
            <div className="flex items-center gap-2 px-2 py-1.5">
              <span className="w-6 h-6 rounded-full bg-[var(--accent)]/20 flex items-center justify-center text-[11px] text-[var(--accent)] font-medium">
                {user.username[0].toUpperCase()}
              </span>
              <span className="text-xs text-[var(--text-secondary)] flex-1 truncate">{user.username}</span>
              <button onClick={logout} className="text-[11px] text-[var(--text-muted)] hover:text-[var(--error)] transition-colors">
                退出
              </button>
            </div>
          ) : (
            <button
              onClick={() => { setAuthMode('login'); setShowAuth(true) }}
              className="w-full px-3 py-2 text-xs rounded-lg border border-[var(--border-subtle)] text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:border-[var(--border-default)] transition-all"
            >
              登录
            </button>
          )}
        </div>
      </aside>

      {/* Main column */}
      <div className="flex-1 min-w-0 flex flex-col">
        <header className="sticky top-0 z-40 glass border-b border-[var(--border-subtle)]">
          <div className="h-14 px-6 flex items-center justify-between">
            <div className="text-sm font-medium text-[var(--text-secondary)]">
              {activeTab === 'research' ? '🔍 研究' : '🕘 历史'}
            </div>

            <div className="flex items-center gap-3">
            <button
              onClick={() => setShowSkills(true)}
              className="w-8 h-8 rounded-lg flex items-center justify-center text-sm border border-[var(--border-subtle)] text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-[var(--surface-hover)] transition-all"
              aria-label="技能管理"
              title="技能管理"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z"/>
                <path d="M19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15z"/>
              </svg>
            </button>
            <button
              onClick={() => setShowProfile(true)}
              className="w-8 h-8 rounded-lg flex items-center justify-center text-sm border border-[var(--border-subtle)] text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-[var(--surface-hover)] transition-all"
              aria-label="个人偏好"
              title="个人偏好"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="8" r="4"/>
                <path d="M4 21c0-4 3.6-6.5 8-6.5s8 2.5 8 6.5"/>
              </svg>
            </button>
            <button
              onClick={() => setShowSettings(true)}
              className="w-8 h-8 rounded-lg flex items-center justify-center text-sm border border-[var(--border-subtle)] text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-[var(--surface-hover)] transition-all"
              aria-label="LLM 配置"
              title="LLM 配置"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
              </svg>
            </button>
            <button
              onClick={toggleTheme}
              className="w-8 h-8 rounded-lg flex items-center justify-center text-sm border border-[var(--border-subtle)] text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-[var(--surface-hover)] transition-all"
              aria-label={theme === 'dark' ? '切换到浅色模式' : '切换到深色模式'}
            >
              {theme === 'dark' ? (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
                </svg>
              ) : (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
                </svg>
              )}
            </button>
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[var(--surface-card)] border border-[var(--border-subtle)]">
              <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-[var(--success)] shadow-[0_0_6px_var(--success)]' : 'bg-[var(--text-muted)]'}`} />
              <span className="text-xs text-[var(--text-muted)]">{isConnected ? '已连接' : '未连接'}</span>
            </div>

            {hasActiveResearch && (
              <button
                onClick={handleReset}
                className="px-4 py-2 text-sm rounded-lg border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:bg-[var(--surface-hover)] hover:border-[var(--border-default)] transition-all"
              >
                ＋ 新建研究
              </button>
            )}
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 max-w-6xl mx-auto w-full px-6 py-8">
        {error && (
          <div className="mb-8 p-4 rounded-xl bg-[var(--error-bg)] border border-[var(--error)]/20 flex items-start gap-3 animate-fade-in">
            <span className="text-[var(--error)] mt-0.5">◆</span>
            <div className="flex-1">
              <p className="text-sm font-medium text-[var(--error)]">{error}</p>
            </div>
            <button onClick={() => setError(null)} className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
            </button>
          </div>
        )}

        {/* === 历史标签：始终可访问 === */}
        {activeTab === 'history' && (
          <div className="animate-fade-in">
            {history.length > 0 ? (
              <>
                <div className="flex items-center justify-between mb-8">
                  <div>
                    <h2 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)]">历史研究</h2>
                    <p className="text-sm text-[var(--text-muted)] mt-1">共 {history.length} 条记录</p>
                  </div>
                  <div className="flex items-center gap-2">
                    {histBatchMode ? (
                      <>
                        <button
                          onClick={() => { setSelectedIds(history.map((i) => i.task_id).filter(Boolean)); }}
                          className="px-2.5 py-1.5 text-xs rounded-lg border border-[var(--border-subtle)] text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-all"
                        >
                          全选
                        </button>
                        <button
                          onClick={handleBatchDelete}
                          disabled={selectedIds.length === 0}
                          className="px-2.5 py-1.5 text-xs rounded-lg border border-[var(--error)]/40 text-[var(--error)] hover:bg-[var(--error-bg)] disabled:opacity-30 transition-all"
                        >
                          删除 {selectedIds.length ? `(${selectedIds.length})` : ''}
                        </button>
                        <button
                          onClick={() => { setHistBatchMode(false); setSelectedIds([]); }}
                          className="px-2.5 py-1.5 text-xs rounded-lg border border-[var(--border-subtle)] text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-all"
                        >
                          退出
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          onClick={fetchHistory}
                          className="px-2.5 py-1.5 text-xs rounded-lg border border-[var(--border-subtle)] text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-all"
                        >
                          刷新
                        </button>
                        <button
                          onClick={() => setHistBatchMode(true)}
                          className="px-2.5 py-1.5 text-xs rounded-lg border border-[var(--border-subtle)] text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-all"
                        >
                          管理
                        </button>
                      </>
                    )}
                  </div>
                </div>
                <div className="grid gap-3">
                  {pagedHistory.map((item, idx) => (
                    <div
                      key={item.task_id || item.report_id || idx}
                      className="glass-card group w-full overflow-hidden animate-fade-in"
                      style={{ animationDelay: `${idx * 0.04}s` }}
                    >
                      {histBatchMode && (
                        <div className="px-4 pt-3 pb-0">
                          <label className="flex items-center gap-2 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={selectedIds.includes(item.task_id)}
                              onChange={() => toggleSelectId(item.task_id)}
                              className="w-4 h-4 rounded border-[var(--border-default)] accent-[var(--accent)]"
                            />
                            <span className="text-xs text-[var(--text-muted)]">选择</span>
                          </label>
                        </div>
                      )}
                      <button
                        onClick={() => handleViewHistory(item.task_id)}
                        className="w-full px-5 py-4 text-left hover:bg-[var(--surface-hover)] transition-all"
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-medium text-sm text-[var(--text-primary)] truncate min-w-0">
                            {item.status === 'running' && (
                              <span className="inline-block w-1.5 h-1.5 rounded-full bg-[var(--accent)] animate-pulse mr-1.5 align-middle" />
                            )}
                            {item.task || item.task_id || '研究任务'}
                          </span>
                          <span className="text-xs text-[var(--text-muted)] flex-shrink-0 ml-3">
                            {item.created_at ? new Date(item.created_at).toLocaleDateString('zh-CN') : ''}
                          </span>
                        </div>
                        {item.summary && (
                          <p className="text-xs text-[var(--text-muted)] mt-1.5 truncate leading-relaxed">{item.summary}</p>
                        )}
                      </button>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="text-center py-24">
                <div className="text-5xl mb-5 opacity-40">📋</div>
                <h3 className="text-lg font-medium text-[var(--text-secondary)]">暂无历史记录</h3>
                <p className="text-sm text-[var(--text-muted)] mt-1">完成研究后，报告将出现在这里</p>
              </div>
            )}
          </div>
        )}

        {/* === 研究标签 === */}
        {activeTab === 'research' && !hasActiveResearch && (
          <>
            <InputPanel onSubmit={handleSubmit} isLoading={isResearching || submitting} />
            {history.length === 0 && (
              <div className="text-center py-16 animate-fade-in">
                <div className="text-5xl mb-5 opacity-30">🔬</div>
                <h2 className="text-xl font-semibold text-[var(--text-secondary)]">准备好开始研究了</h2>
                <p className="text-sm text-[var(--text-muted)] mt-2 max-w-md mx-auto">
                  输入一个研究课题，多 Agent 系统将自动搜索、分析并生成研究报告
                </p>
              </div>
            )}
          </>
        )}

        {activeTab === 'research' && hasActiveResearch && (
          <>
            <div className="-my-8 h-[calc(100vh-8.5rem)] flex flex-col overflow-hidden">
              {activeEvents.length > 0 && (
                <div className="shrink-0 pb-4 max-h-[36vh] overflow-y-auto pr-1">
                  <AgentTrace
                    events={activeEvents}
                    isComplete={activeStatus === 'completed'}
                    isConnected={isConnected}
                  />
                </div>
              )}
              <div key={activeTaskId || 'report'} className="flex-1 min-h-0">
                <ReportViewer
                  taskId={activeTaskId}
                  content={activeReport}
                  events={activeEvents}
                />
              </div>
            </div>
          </>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-[var(--border-subtle)] py-6">
        <div className="max-w-6xl mx-auto px-6 flex items-center justify-between">
          <span className="text-xs text-[var(--text-muted)]">
            DeepResearch Agent
          </span>
          <span className="text-xs text-[var(--text-muted)]">
            多 Agent 协作 · 自动化研究
          </span>
        </div>
      </footer>
      </div>

      {runningTasks.map((t) => (
        <TaskStream key={t.id} taskId={t.id} onEvent={handleTaskEvent} />
      ))}

      <SkillsModal isOpen={showSkills} onClose={() => setShowSkills(false)} />

      <ProfileModal isOpen={showProfile} onClose={() => setShowProfile(false)} />

      <SettingsModal
        isOpen={showSettings}
        onClose={() => setShowSettings(false)}
        onSaved={() => {
          setSettingsConfigured(true)
          window.location.reload()
        }}
      />

      <AuthModal
        isOpen={showAuth}
        onClose={() => setShowAuth(false)}
        mode={authMode}
        onSwitchMode={() => setAuthMode((m) => (m === 'login' ? 'register' : 'login'))}
      />
    </div>
  )
}

class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, message: '' }
  }

  static getDerivedStateFromError(error) {
    return {
      hasError: true,
      message: error?.message || '页面渲染异常',
    }
  }

  componentDidCatch(error) {
    console.error('App render failed:', error)
  }

  render() {
    if (!this.state.hasError) return this.props.children

    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg-primary)] px-6">
        <div className="glass-card max-w-md w-full p-6 text-center">
          <h1 className="text-lg font-semibold text-[var(--text-primary)]">页面渲染失败</h1>
          <p className="mt-2 text-sm text-[var(--text-muted)]">{this.state.message}</p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-5 px-4 py-2 rounded-lg text-sm font-semibold text-white bg-[var(--accent)]"
          >
            刷新页面
          </button>
        </div>
      </div>
    )
  }
}

export default function App() {
  return (
    <AppErrorBoundary>
      <AuthProvider>
        <AppInner />
      </AuthProvider>
    </AppErrorBoundary>
  )
}
