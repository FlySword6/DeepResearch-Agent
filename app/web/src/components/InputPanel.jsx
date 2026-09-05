import React, { useState, useRef } from 'react'

const depthOptions = [
  { value: 'quick', label: '快速', description: '约 1-3 分钟', icon: '⚡' },
  { value: 'standard', label: '标准', description: '约 5-10 分钟', icon: '📊' },
  { value: 'deep', label: '深度', description: '约 10-20 分钟', icon: '🔍' },
]

const engineOptions = [
  { value: 'langgraph', label: 'LangGraph', description: '状态图编排' },
  { value: 'harness', label: 'Harness', description: '运行时调度' },
]

const ALLOWED_EXTS = ['.pdf', '.md', '.txt', '.csv', '.json', '.docx']
const MAX_BYTES = 20 * 1024 * 1024 // UPLOAD_MAX_BYTES
const ACCEPT = ALLOWED_EXTS.join(',')

export default function InputPanel({ onSubmit, isLoading }) {
  const [task, setTask] = useState('')
  const [depth, setDepth] = useState('standard')
  const [useRag, setUseRag] = useState(false)
  const [engine, setEngine] = useState('langgraph')
  const [files, setFiles] = useState([])        // [{ name, size, file }]
  const [fileErrors, setFileErrors] = useState([]) // [{ name, message }]
  const inputRef = useRef(null)

  const addFiles = (selected) => {
    const errs = []
    const accepted = []
    setFileErrors([])
    for (const f of selected) {
      const ext = (f.name.match(/\.[^.]+$/) || [''])[0].toLowerCase()
      if (!ALLOWED_EXTS.includes(ext)) {
        errs.push({ name: f.name, message: `不支持的文件类型: ${ext}（支持 ${ALLOWED_EXTS.join(' ')}）` })
        continue
      }
      if (f.size > MAX_BYTES) {
        errs.push({ name: f.name, message: '文件过大，上限 20MB' })
        continue
      }
      if (!files.some((x) => x.name === f.name) && !accepted.some((x) => x.name === f.name)) accepted.push({ name: f.name, size: f.size, file: f })
    }
    setFiles((prev) => [...prev, ...accepted])
    setFileErrors((prev) => [...prev, ...errs])
  }

  const removeFile = (name) => {
    setFiles((prev) => prev.filter((x) => x.name !== name))
    setFileErrors((prev) => prev.filter((x) => x.name !== name))
  }
  const formatSize = (b) => (b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${(b / 1024).toFixed(1)} KB`)

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!task.trim() || isLoading) return
    onSubmit({ task: task.trim(), depth, useRag, engine, files })
  }

  return (
    <div className="animate-fade-in max-w-3xl mx-auto">
      <div className="mb-8">
        <h2 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)]">
          研究课题
        </h2>
        <p className="text-sm text-[var(--text-muted)] mt-1">
          输入你想研究的任何主题，AI Agent 将自动完成搜索、分析与报告生成
        </p>
      </div>

      <form onSubmit={handleSubmit} className="glass-card p-6 space-y-5">
        {/* Textarea */}
        <div className="relative">
          <textarea
            id="task"
            rows={4}
            className="w-full px-4 py-3.5 rounded-xl bg-[var(--surface)] border border-[var(--border-subtle)] text-[var(--text-primary)] placeholder-[var(--text-muted)] text-sm resize-none focus:outline-none focus:border-[var(--border-accent)] focus:shadow-[0_0_12px_var(--accent-glow)] transition-all"
            placeholder="输入研究课题，例如：分析 2026 年 AI Agent 行业趋势并生成投资分析报告"
            value={task}
            onChange={(e) => setTask(e.target.value)}
            disabled={isLoading}
          />
        </div>

        {/* Reference files */}
        <div>
          <label className="block text-xs font-medium text-[var(--text-muted)] mb-3 uppercase tracking-wider">
            参考文件（可选）
          </label>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept={ACCEPT}
            className="hidden"
            onChange={(e) => { addFiles([...e.target.files]); e.target.value = '' }}
            disabled={isLoading}
          />
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={isLoading}
            className="w-full p-4 rounded-xl border border-dashed border-[var(--border-subtle)] text-sm text-[var(--text-muted)] hover:border-[var(--border-accent)] hover:text-[var(--text-secondary)] transition-all"
          >
            <span className="flex items-center justify-center gap-2">📎 选择文件（PDF / MD / TXT / CSV / JSON / DOCX，单个 ≤ 20MB）</span>
          </button>
          {fileErrors.length > 0 && (
            <ul className="mt-2 space-y-1">
              {fileErrors.map((er, i) => (
                <li key={i} className="text-xs text-[var(--error)]">{er.name}: {er.message}</li>
              ))}
            </ul>
          )}
          {files.length > 0 && (
            <ul className="mt-2 space-y-1.5">
              {files.map((f) => (
                <li key={f.name} className="flex items-center justify-between px-3 py-2 rounded-lg bg-[var(--surface)] border border-[var(--border-subtle)]">
                  <span className="text-sm text-[var(--text-secondary)] truncate">
                    <span className="text-[var(--text-primary)]">{f.name}</span>
                    <span className="text-[var(--text-muted)] text-xs ml-2">{formatSize(f.size)}</span>
                  </span>
                  <button
                    type="button"
                    onClick={() => removeFile(f.name)}
                    disabled={isLoading}
                    className="text-xs text-[var(--text-muted)] hover:text-[var(--error)] transition-colors"
                    aria-label={`移除 ${f.name}`}
                  >移除</button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Depth selector */}
        <div>
          <label className="block text-xs font-medium text-[var(--text-muted)] mb-3 uppercase tracking-wider">
            研究深度
          </label>
          <div className="grid grid-cols-3 gap-3">
            {depthOptions.map((opt) => (
              <button
                key={opt.value}
                type="button"
                className={`p-3.5 rounded-xl border text-left transition-all ${
                  depth === opt.value
                    ? 'border-[var(--border-accent)] bg-[var(--accent-glow)] shadow-[0_0_12px_var(--accent-glow)]'
                    : 'border-[var(--border-subtle)] bg-[var(--surface)] hover:bg-[var(--surface-hover)] hover:border-[var(--border-default)]'
                }`}
                onClick={() => setDepth(opt.value)}
                disabled={isLoading}
              >
                <div className="flex items-center gap-2">
                  <span className="text-lg">{opt.icon}</span>
                  <span className={`font-medium text-sm ${
                    depth === opt.value ? 'text-[var(--accent)]' : 'text-[var(--text-primary)]'
                  }`}>
                    {opt.label}
                  </span>
                </div>
                <div className="text-xs text-[var(--text-muted)] mt-1.5 flex items-center gap-1">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>
                  </svg>
                  {opt.description}
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Workflow engine selector */}
        <div>
          <label className="block text-xs font-medium text-[var(--text-muted)] mb-3 uppercase tracking-wider">
            工作流引擎
          </label>
          <div className="grid grid-cols-2 gap-3">
            {engineOptions.map((opt) => (
              <button
                key={opt.value}
                type="button"
                className={`p-3.5 rounded-xl border text-left transition-all ${
                  engine === opt.value
                    ? 'border-[var(--border-accent)] bg-[var(--accent-glow)] shadow-[0_0_12px_var(--accent-glow)]'
                    : 'border-[var(--border-subtle)] bg-[var(--surface)] hover:bg-[var(--surface-hover)] hover:border-[var(--border-default)]'
                }`}
                onClick={() => setEngine(opt.value)}
                disabled={isLoading}
              >
                <div className={`font-medium text-sm ${
                  engine === opt.value ? 'text-[var(--accent)]' : 'text-[var(--text-primary)]'
                }`}>
                  {opt.label}
                </div>
                <div className="text-xs text-[var(--text-muted)] mt-1.5">{opt.description}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Options row */}
        <div className="flex items-center justify-between pt-1">
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2.5 cursor-pointer group">
              <div className={`relative w-9 h-5 rounded-full transition-all ${
                useRag ? 'bg-[var(--accent)]' : 'bg-[var(--surface-card)] border border-[var(--border-subtle)]'
              }`}>
                <div className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-all shadow-sm ${
                  useRag ? 'translate-x-4' : 'translate-x-0'
                }`} />
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={useRag}
                  onChange={() => setUseRag(!useRag)}
                  disabled={isLoading}
                />
              </div>
              <span className="text-sm text-[var(--text-secondary)] group-hover:text-[var(--text-primary)] transition-colors">
                RAG 知识库
              </span>
            </label>

            <KnowledgeModalButton />
          </div>

          <button
            type="submit"
            disabled={isLoading || !task.trim()}
            className={`px-6 py-2.5 rounded-xl font-medium text-sm transition-all ${
              isLoading || !task.trim()
                ? 'bg-[var(--surface-card)] text-[var(--text-muted)] cursor-not-allowed border border-[var(--border-subtle)]'
                : 'bg-[var(--accent)] text-white hover:shadow-[0_0_20px_var(--accent-glow)] active:scale-[0.97]'
            }`}
          >
            {isLoading ? (
              <span className="flex items-center gap-2">
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                研究中...
              </span>
            ) : (
              <span className="flex items-center gap-2">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <path d="M4 2l10 6-10 6V2z" fill="currentColor" />
                </svg>
                开始研究
              </span>
            )}
          </button>
        </div>
      </form>
    </div>
  )
}

function KnowledgeModalButton() {
  const [open, setOpen] = useState(false)
  const [content, setContent] = useState('')
  const [source, setSource] = useState('')
  const [ragQuery, setRagQuery] = useState('')
  const [ragResults, setRagResults] = useState(null)
  const [docs, setDocs] = useState([])
  const [loading, setLoading] = useState(false)
  const [ingesting, setIngesting] = useState(false)
  const [error, setError] = useState(null)
  const dragRef = useRef({ isDragging: false, startX: 0, startY: 0, panelX: 0, panelY: 0 })
  const panelRef = useRef(null)
  const [pos, setPos] = useState({ x: 0, y: 0 })

  const loadDocList = async () => {
    try {
      const r = await fetch('/api/knowledge/list')
      if (r.ok) {
        const data = await r.json()
        setDocs(data || [])
      }
    } catch {}
  }

  const handleOpen = () => {
    setOpen(true)
    setPos({ x: 0, y: 0 })
    loadDocList()
  }

  const handleMouseDown = (e) => {
    dragRef.current.isDragging = true
    dragRef.current.startX = e.clientX
    dragRef.current.startY = e.clientY
    dragRef.current.panelX = pos.x
    dragRef.current.panelY = pos.y
    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    e.preventDefault()
  }

  const handleMouseMove = (e) => {
    if (!dragRef.current.isDragging) return
    const dx = e.clientX - dragRef.current.startX
    const dy = e.clientY - dragRef.current.startY
    setPos({
      x: dragRef.current.panelX + dx,
      y: dragRef.current.panelY + dy,
    })
  }

  const handleMouseUp = () => {
    dragRef.current.isDragging = false
    document.removeEventListener('mousemove', handleMouseMove)
    document.removeEventListener('mouseup', handleMouseUp)
  }

  const handleIngest = async () => {
    if (!content.trim() || !source.trim()) return
    setIngesting(true)
    setError(null)
    try {
      const r = await fetch('/api/knowledge/ingest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content, source }),
      })
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        throw new Error(d.detail || '导入失败')
      }
      setContent('')
      setSource('')
      loadDocList()
    } catch (err) {
      setError(err.message)
    } finally {
      setIngesting(false)
    }
  }

  const handleSearch = async () => {
    if (!ragQuery.trim()) return
    setLoading(true)
    try {
      const r = await fetch(`/api/knowledge/search?q=${encodeURIComponent(ragQuery)}`)
      if (r.ok) {
        const data = await r.json()
        setRagResults(data || [])
      }
    } catch {
      setRagResults([])
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (src) => {
    try {
      const r = await fetch('/api/knowledge/docs', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: src }),
      })
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        setError(d.detail || '删除失败')
        return
      }
      loadDocList()
    } catch (err) {
      setError(err.message || '删除失败')
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={handleOpen}
        className="px-3 py-1.5 text-xs rounded-lg border border-[var(--border-subtle)] text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:border-[var(--border-default)] transition-all"
      >
        知识库
      </button>
    )
  }

  return (
    <div className="fixed inset-0 z-50" style={{ pointerEvents: open ? 'auto' : 'none' }}>
      <div className="absolute inset-0 bg-black/40" style={{ pointerEvents: 'auto' }} onClick={() => setOpen(false)} />
      <div
        ref={panelRef}
        className="absolute w-full max-w-lg max-h-[80vh] rounded-2xl bg-[var(--surface-elevated)] border border-[var(--border-default)] shadow-2xl flex flex-col animate-fade-in"
        style={{
          left: `calc(50% - 256px + ${pos.x}px)`,
          top: `calc(15% + ${pos.y}px)`,
          pointerEvents: 'auto',
        }}
      >
        {/* Draggable header with close button */}
        <div
          className="flex items-center justify-between px-6 pt-6 pb-3 shrink-0 border-b border-[var(--border-subtle)] cursor-grab active:cursor-grabbing select-none"
          onMouseDown={handleMouseDown}
        >
          <h2 className="text-base font-semibold text-[var(--text-primary)]">知识库管理</h2>
          <button onClick={() => setOpen(false)} className="w-8 h-8 flex items-center justify-center rounded-lg text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-hover)] transition-colors">
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M4 4l10 10M14 4l-10 10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
          </button>
        </div>

        {/* Scrollable content */}
        <div className="overflow-y-auto px-6 py-4">
          {error && (
            <div className="mb-4 p-3 rounded-lg bg-[var(--error-bg)] border border-[var(--error)]/20 text-xs text-[var(--error)]">
              {error}
            </div>
          )}

          {/* Ingest */}
          <div className="mb-6">
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-2 uppercase tracking-wider">导入文档</label>
            <textarea
              rows={3}
              className="w-full mb-2 px-3 py-2 rounded-lg bg-[var(--surface)] border border-[var(--border-subtle)] text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)] resize-none focus:outline-none focus:border-[var(--border-accent)]"
              placeholder="粘贴文档内容..."
              value={content}
              onChange={(e) => setContent(e.target.value)}
            />
            <div className="flex gap-2">
              <input
                type="text"
                className="flex-1 px-3 py-2 rounded-lg bg-[var(--surface)] border border-[var(--border-subtle)] text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:border-[var(--border-accent)]"
                placeholder="文档名称"
                value={source}
                onChange={(e) => setSource(e.target.value)}
              />
              <button
                onClick={handleIngest}
                disabled={ingesting || !content.trim() || !source.trim()}
                className="px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm font-medium disabled:opacity-40 hover:shadow-[0_0_12px_var(--accent-glow)] transition-all"
              >
                {ingesting ? '导入中...' : '导入'}
              </button>
            </div>
          </div>

          {/* Search */}
          <div className="mb-6">
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-2 uppercase tracking-wider">检索测试</label>
            <div className="flex gap-2">
              <input
                type="text"
                className="flex-1 px-3 py-2 rounded-lg bg-[var(--surface)] border border-[var(--border-subtle)] text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:border-[var(--border-accent)]"
                placeholder="输入检索关键词..."
                value={ragQuery}
                onChange={(e) => setRagQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              />
              <button
                onClick={handleSearch}
                disabled={loading || !ragQuery.trim()}
                className="px-4 py-2 rounded-lg border border-[var(--border-subtle)] text-[var(--text-secondary)] text-sm hover:bg-[var(--surface-hover)] disabled:opacity-40 transition-all"
              >
                检索
              </button>
            </div>
            {ragResults && ragResults.length > 0 && (
              <div className="mt-3 space-y-2">
                {ragResults.map((item, i) => (
                  <div key={i} className="p-3 rounded-lg bg-[var(--surface)] border border-[var(--border-subtle)]">
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <div className="text-xs font-medium text-[var(--accent)] truncate">
                        {item.metadata?.source || `片段 ${i + 1}`}
                      </div>
                      {typeof item.matched_chunks === 'number' && item.matched_chunks > 1 && (
                        <span className="shrink-0 text-[10px] px-1.5 py-0.5 rounded-full bg-[var(--accent-glow)] text-[var(--accent)]">
                          命中 {item.matched_chunks} 个片段
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-[var(--text-secondary)] leading-relaxed">
                      {(item.text || '').substring(0, 200)}
                    </div>
                    <div className="text-[11px] text-[var(--text-muted)] mt-1">
                      排序: Top {i + 1} · 融合得分: {typeof item.rrf_score === 'number' ? item.rrf_score.toFixed(3) : typeof item.score === 'number' ? item.score.toFixed(3) : '-'} · BM25: {typeof item.bm25_score === 'number' ? item.bm25_score.toFixed(2) : '-'} · 向量命中: {item.vector_score != null ? '是' : '否'}
                    </div>
                  </div>
                ))}
              </div>
            )}
            {ragResults && ragResults.length === 0 && (
              <p className="text-xs text-[var(--text-muted)] mt-2">未找到相关结果</p>
            )}
          </div>

          {/* Doc list */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">文档列表</span>
              <button onClick={loadDocList} className="text-xs text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors">
                刷新
              </button>
            </div>
            {docs.length > 0 ? (
              <div className="space-y-1.5">
                {docs.map((d, i) => (
                  <div key={i} className="flex items-center justify-between px-3 py-2 rounded-lg bg-[var(--surface)] border border-[var(--border-subtle)]">
                    <span className="text-sm text-[var(--text-secondary)]">
                      {d.source}
                      {d.chunks != null && (
                        <span className="text-[var(--text-muted)] text-xs ml-2">({d.chunks} 块)</span>
                      )}
                    </span>
                    <button
                      onClick={() => handleDelete(d.source)}
                      className="text-xs text-[var(--error)] hover:text-[var(--error)]/80 transition-colors"
                    >
                      删除
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-[var(--text-muted)]">知识库为空</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
