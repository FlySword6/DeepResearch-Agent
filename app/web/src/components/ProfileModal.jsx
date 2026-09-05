import React, { useState, useEffect } from 'react'
import ModalShell from './ModalShell'

const STYLE_OPTIONS = [
  { value: 'academic', label: '学术严谨' },
  { value: 'popular', label: '通俗易懂' },
  { value: 'business', label: '商业务实' },
  { value: 'balanced', label: '均衡' },
]

export default function ProfileModal({ isOpen, onClose }) {
  const [form, setForm] = useState({
    writing_style: 'balanced',
    domain_focus: '',
    preferred_model: '',
    extra_instructions: '',
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)

  useEffect(() => {
    if (!isOpen) return
    setError(null)
    setSuccess(null)
    fetch('/api/profile')
      .then((r) => r.json())
      .then((data) =>
        setForm({
          writing_style: data.writing_style || 'balanced',
          domain_focus: data.domain_focus || '',
          preferred_model: data.preferred_model || '',
          extra_instructions: data.extra_instructions || '',
        })
      )
      .catch(() => {})
  }, [isOpen])

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    setSuccess(null)
    try {
      const res = await fetch('/api/profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setError(data.detail || `保存失败: HTTP ${res.status}`)
        return
      }
      setSuccess('已保存')
    } catch (e) {
      setError(e.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  if (!isOpen) return null

  return (
    <ModalShell isOpen={isOpen} onClose={onClose} title="个人偏好" width="md">
      <div className="space-y-4">
          {error && (
            <div className="error-box">
              {error}
            </div>
          )}
          {success && (
            <div className="success-box">
              {success}
            </div>
          )}
          <div>
            <label className="label">写作风格</label>
            <select
              value={form.writing_style}
              onChange={(e) => setForm({ ...form, writing_style: e.target.value })}
              className="input"
            >
              {STYLE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">领域偏好（逗号分隔）</label>
            <input
              value={form.domain_focus}
              onChange={(e) => setForm({ ...form, domain_focus: e.target.value })}
              placeholder="AI, 金融, 医疗"
              className="input"
            />
          </div>
          <div>
            <label className="label">模型覆盖（留空用默认）</label>
            <input
              value={form.preferred_model}
              onChange={(e) => setForm({ ...form, preferred_model: e.target.value })}
              placeholder="如 gpt-4o-mini"
              className="input"
            />
          </div>
          <div>
            <label className="label">附加指令</label>
            <textarea
              value={form.extra_instructions}
              onChange={(e) => setForm({ ...form, extra_instructions: e.target.value })}
              rows={4}
              placeholder="注入到所有 Agent 的额外要求"
              className="input resize-y"
            />
          </div>
          <div className="flex gap-2 pt-1">
            <button
              onClick={handleSave}
              disabled={saving}
              className="btn-primary"
            >
              {saving ? '保存中...' : '保存'}
            </button>
            <button
              onClick={onClose}
              className="btn-ghost"
            >
              关闭
            </button>
          </div>
        </div>
    </ModalShell>
  )
}
