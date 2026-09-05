import React, { useState, useEffect, useCallback } from 'react'
import ModalShell from './ModalShell'

const AGENT_OPTIONS = [
  { value: 'planner', label: 'Planner' },
  { value: 'researcher', label: 'Researcher' },
  { value: 'writer', label: 'Writer' },
  { value: 'reviewer', label: 'Reviewer' },
]

const EMPTY_FORM = {
  name: '',
  description: '',
  trigger_keywords: '',
  agents: ['planner', 'researcher', 'writer', 'reviewer'],
  content: '',
  enabled: true,
}

export default function SkillsModal({ isOpen, onClose }) {
  const [skills, setSkills] = useState([])
  const [editing, setEditing] = useState(null) // null = list, 'new' = create, object = edit
  const [form, setForm] = useState(EMPTY_FORM)
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [previewTask, setPreviewTask] = useState('')
  const [previewResult, setPreviewResult] = useState([])
  const [previewLoading, setPreviewLoading] = useState(false)
  const [tab, setTab] = useState('mine') // 'mine' | 'global'
  const [drafts, setDrafts] = useState([])
  const [draftsLoading, setDraftsLoading] = useState(false)

  const loadSkills = useCallback(async () => {
    try {
      const res = await fetch('/api/skills')
      if (res.ok) setSkills(await res.json())
    } catch {}
  }, [])

  useEffect(() => {
    if (isOpen) {
      setError(null)
      loadSkills()
    }
  }, [isOpen, loadSkills])

  const loadDrafts = useCallback(async () => {
    setDraftsLoading(true)
    try {
      const res = await fetch('/api/evolution/drafts?status=pending')
      if (res.ok) setDrafts(await res.json())
    } catch {} finally {
      setDraftsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (isOpen && tab === 'evolution') loadDrafts()
  }, [isOpen, tab, loadDrafts])

  const startCreate = () => {
    setForm(EMPTY_FORM)
    setEditing('new')
    setPreviewResult([])
  }

  const startEdit = (skill) => {
    setForm({
      name: skill.name,
      description: skill.description,
      trigger_keywords: (skill.trigger_keywords || []).join(', '),
      agents: skill.agents || [],
      content: skill.content,
      enabled: skill.enabled,
    })
    setEditing(skill)
  }

  const handleSave = async () => {
    if (!form.name.trim() || !form.content.trim()) {
      setError('名称和指令内容不能为空')
      return
    }
    if (form.agents.length === 0) {
      setError('至少选择一个生效 Agent')
      return
    }
    setSaving(true)
    setError(null)
    const payload = {
      name: form.name.trim(),
      description: form.description.trim(),
      trigger_keywords: form.trigger_keywords.split(',').map((s) => s.trim()).filter(Boolean),
      agents: form.agents,
      content: form.content,
      enabled: form.enabled,
    }
    try {
      const res = await fetch(editing === 'new' ? '/api/skills' : `/api/skills/${editing.id}`, {
        method: editing === 'new' ? 'POST' : 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setError(data.detail || `保存失败: HTTP ${res.status}`)
        return
      }
      setEditing(null)
      loadSkills()
    } catch (e) {
      setError(e.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleToggle = async (skill) => {
    try {
      await fetch(`/api/skills/${skill.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !skill.enabled }),
      })
      loadSkills()
    } catch {}
  }

  const handleDelete = async (skill) => {
    if (!window.confirm(`确认删除技能「${skill.name}」？`)) return
    try {
      await fetch(`/api/skills/${skill.id}`, { method: 'DELETE' })
      if (editing?.id === skill.id) setEditing(null)
      loadSkills()
    } catch {}
  }

  const handlePreview = async () => {
    if (!previewTask.trim()) return
    setPreviewLoading(true)
    try {
      const res = await fetch('/api/skills/match', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task: previewTask.trim() }),
      })
      if (res.ok) {
        const data = await res.json()
        setPreviewResult(data.matches && data.matches.length > 0 ? data.matches : [])
      }
    } catch {} finally {
      setPreviewLoading(false)
    }
  }

  const handleGlobalToggle = async (skill) => {
    try {
      await fetch(`/api/skills/${skill.id}/pref`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !skill.enabled_for_me }),
      })
      loadSkills()
    } catch {}
  }

  const handleDraftAccept = async (draft, promoteGlobal) => {
    try {
      const res = await fetch(`/api/evolution/drafts/${draft.id}/accept`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ promote_global: promoteGlobal }),
      })
      if (res.ok) {
        loadDrafts()
        loadSkills()
      }
    } catch {}
  }

  const handleDraftReject = async (draft) => {
    if (!window.confirm(`拒绝进化建议「${draft.draft_name}」？`)) return
    try {
      await fetch(`/api/evolution/drafts/${draft.id}/reject`, { method: 'POST' })
      loadDrafts()
    } catch {}
  }

  if (!isOpen) return null

  const mine = skills.filter((s) => s.owner_id)
  const globals = skills.filter((s) => !s.owner_id)
  const visibleSkills = tab === 'mine' ? mine : globals

  return (
    <ModalShell isOpen={isOpen} onClose={onClose} title="技能管理" width="lg">
          {error && (
            <div className="error-box mb-4">
              {error}
            </div>
          )}

          {editing === null ? (
            <>
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setTab('mine')}
                    className={`px-3 py-1.5 text-sm rounded-lg transition-all ${
                      tab === 'mine'
                        ? 'text-[var(--accent)] bg-[var(--accent-glow)]'
                        : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
                    }`}
                  >
                    我的技能
                  </button>
                  <button
                    onClick={() => setTab('global')}
                    className={`px-3 py-1.5 text-sm rounded-lg transition-all ${
                      tab === 'global'
                        ? 'text-[var(--accent)] bg-[var(--accent-glow)]'
                        : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
                    }`}
                  >
                    全局技能
                  </button>
                  <button
                    onClick={() => setTab('evolution')}
                    className={`px-3 py-1.5 text-sm rounded-lg transition-all ${
                      tab === 'evolution'
                        ? 'text-[var(--accent)] bg-[var(--accent-glow)]'
                        : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
                    }`}
                  >
                    进化建议
                  </button>
                </div>
                <div className="flex items-center gap-3">
                  <p className="text-sm text-[var(--text-muted)]">
                    {tab === 'evolution' ? `草稿 ${drafts.length} 条` : `共 ${visibleSkills.length} 个`}
                  </p>
                  {tab === 'mine' && (
                <button
                  onClick={startCreate}
                  className="btn-primary"
                >
                      新建技能
                    </button>
                  )}
                </div>
              </div>

              <div className="space-y-2">
                {tab === 'evolution' ? (
                  <>
                    {draftsLoading && (
                      <p className="text-sm text-[var(--text-muted)]">加载中...</p>
                    )}
                    {!draftsLoading && drafts.length === 0 && (
                      <p className="text-sm text-[var(--text-muted)] py-6 text-center">
                        暂无待确认的进化建议
                      </p>
                    )}
                    {drafts.map((d) => (
                      <div key={d.id} className="p-3 rounded-xl bg-[var(--surface-card)] border border-[var(--border-subtle)]">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-[var(--text-primary)]">{d.draft_name}</span>
                          <span className={`text-[10px] px-1.5 py-0.5 rounded ${d.review_score >= 0.75 ? 'bg-[var(--success)]/10 text-[var(--success)]' : 'bg-[var(--error-bg)] text-[var(--error)]'}`}>
                            评分 {d.review_score}
                          </span>
                        </div>
                        {d.lesson && <p className="text-xs text-[var(--text-secondary)] mt-1.5">{d.lesson}</p>}
                        <p className="text-xs text-[var(--text-muted)] mt-1 line-clamp-3">{d.draft_content}</p>
                        <div className="flex gap-2 mt-3">
                          <button
                            onClick={() => handleDraftAccept(d, false)}
                            className="btn-primary"
                          >
                            接受
                          </button>
                          <button
                            onClick={() => handleDraftAccept(d, true)}
                            className="btn-ghost"
                          >
                            发布全局
                          </button>
                          <button
                            onClick={() => handleDraftReject(d)}
                            className="btn-danger"
                          >
                            拒绝
                          </button>
                        </div>
                      </div>
                    ))}
                  </>
                ) : visibleSkills.map((skill) => (
                  <div
                    key={skill.id}
                    className="flex items-center gap-3 p-3 rounded-xl bg-[var(--surface-card)] border border-[var(--border-subtle)]"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-[var(--text-primary)] truncate">{skill.name}</span>
                        {!skill.enabled && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--surface-hover)] text-[var(--text-muted)]">
                            已停用
                          </span>
                        )}
                      </div>
                      {skill.description && (
                        <p className="text-xs text-[var(--text-muted)] truncate mt-0.5">{skill.description}</p>
                      )}
                      <div className="flex items-center gap-2 mt-1.5">
                        {(skill.agents || []).map((a) => (
                          <span key={a} className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--accent-glow)] text-[var(--accent)]">
                            {a}
                          </span>
                        ))}
                      </div>
                    </div>
                    {tab === 'global' ? (
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={skill.enabled_for_me}
                          onChange={() => handleGlobalToggle(skill)}
                          className="w-4 h-4 rounded accent-[var(--accent)]"
                        />
                        <span className="text-xs text-[var(--text-muted)]">
                          {skill.enabled_for_me ? '启用' : '停用'}
                        </span>
                      </label>
                    ) : (
                      <>
                        <label className="flex items-center gap-2 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={skill.enabled}
                            onChange={() => handleToggle(skill)}
                            className="w-4 h-4 rounded accent-[var(--accent)]"
                          />
                          <span className="text-xs text-[var(--text-muted)]">{skill.enabled ? '启用' : '停用'}</span>
                        </label>
                    <button
                      onClick={() => startEdit(skill)}
                      className="btn-ghost"
                    >
                          编辑
                        </button>
                    <button
                      onClick={() => handleDelete(skill)}
                      className="btn-danger"
                    >
                          删除
                        </button>
                      </>
                    )}
                  </div>
                ))}
              </div>

              <div className="mt-6 p-4 rounded-xl bg-[var(--surface-card)] border border-[var(--border-subtle)]">
                <h3 className="text-sm font-medium text-[var(--text-secondary)] mb-2">触发匹配预览</h3>
                <div className="flex gap-2">
                  <input
                    value={previewTask}
                    onChange={(e) => setPreviewTask(e.target.value)}
                    placeholder="输入研究任务文本，查看哪些技能会命中"
                    className="input"
                  />
                  <button
                    onClick={handlePreview}
                    disabled={previewLoading}
                    className="btn-ghost disabled:opacity-50"
                  >
                    {previewLoading ? '匹配中...' : '预览'}
                  </button>
                </div>
                {previewResult.length > 0 && (
                  <div className="mt-3 space-y-2">
                    {previewResult.map((m) => (
                      <div key={m.agent} className="text-xs text-[var(--text-secondary)]">
                        <span className="font-medium text-[var(--text-muted)] capitalize mr-1.5">
                          {m.agent}
                        </span>
                        {(m.skills || []).map((s) => (
                          <span key={s.id} className="mr-1.5 px-2 py-0.5 rounded-full bg-[var(--accent-glow)] text-[var(--accent)]">
                            {s.name}
                          </span>
                        ))}
                      </div>
                    ))}
                  </div>
                )}
                {previewResult.length === 0 && previewTask.trim() && (
                  <p className="mt-3 text-xs text-[var(--text-muted)]">
                    没有命中的技能（基于任务标题；实际研究中子任务/计划也会参与匹配）
                  </p>
                )}
              </div>
            </>
          ) : (
            <div className="space-y-4">
              <div>
                <label className="label">名称 *</label>
                <input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="如 deep-tech-analysis"
                  className="input"
                />
              </div>
              <div>
                <label className="label">描述</label>
                <input
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  placeholder="一句话描述技能用途"
                  className="input"
                />
              </div>
              <div>
                <label className="label">
                  触发关键词（逗号分隔，留空则恒生效）
                </label>
                <input
                  value={form.trigger_keywords}
                  onChange={(e) => setForm({ ...form, trigger_keywords: e.target.value })}
                  placeholder="AI, 大模型, 技术"
                  className="input"
                />
                <p className="text-[11px] text-[var(--text-muted)] mt-1.5 leading-relaxed">
                  填简短词命中率更高（如：报告、竞品、代码审查）；任务标题或研究子任务里出现即触发。留空 = 始终生效。
                </p>
              </div>
              <div>
                <label className="label mb-2">生效 Agent *</label>
                <div className="flex flex-wrap gap-2">
                  {AGENT_OPTIONS.map((opt) => (
                    <label
                      key={opt.value}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-[var(--border-subtle)] text-sm text-[var(--text-secondary)] cursor-pointer"
                    >
                      <input
                        type="checkbox"
                        checked={form.agents.includes(opt.value)}
                        onChange={() =>
                          setForm({
                            ...form,
                            agents: form.agents.includes(opt.value)
                              ? form.agents.filter((a) => a !== opt.value)
                              : [...form.agents, opt.value],
                          })
                        }
                        className="w-4 h-4 rounded accent-[var(--accent)]"
                      />
                      {opt.label}
                    </label>
                  ))}
                </div>
              </div>
              <div>
                <label className="label">指令内容 *</label>
                <textarea
                  value={form.content}
                  onChange={(e) => setForm({ ...form, content: e.target.value })}
                  rows={8}
                  placeholder="输入注入到 Agent system prompt 的指令正文"
                  className="input resize-y"
                />
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.enabled}
                  onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
                  className="w-4 h-4 rounded accent-[var(--accent)]"
                />
                <span className="text-sm text-[var(--text-secondary)]">启用</span>
              </label>
              <div className="flex gap-2 pt-1">
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="btn-primary"
                >
                  {saving ? '保存中...' : '保存'}
                </button>
                <button
                  onClick={() => setEditing(null)}
                  className="btn-ghost"
                >
                  取消
                </button>
              </div>
            </div>
          )}
    </ModalShell>
  )
}
