import React, { useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import ModalShell from './ModalShell'

export default function AuthModal({ isOpen, onClose, mode, onSwitchMode }) {
  const { login, register } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  if (!isOpen) return null

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!username.trim() || !password.trim()) return
    setLoading(true)
    setError(null)
    try {
      if (mode === 'login') {
        await login(username.trim(), password)
      } else {
        await register(username.trim(), password)
        // Auto-login after register
        await login(username.trim(), password)
      }
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <ModalShell
      isOpen={isOpen}
      onClose={onClose}
      title={mode === 'login' ? '登录' : '注册'}
      width="sm"
    >
      <p className="text-sm text-[var(--text-muted)] mb-6">
        {mode === 'login' ? '登录后即可管理你的研究任务' : '创建一个账号来保存你的研究历史'}
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        {error && <div className="error-box">{error}</div>}

        <div>
          <label className="label">用户名</label>
          <input
            type="text"
            className="input"
            placeholder="输入用户名"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            disabled={loading}
            autoFocus
          />
        </div>

        <div>
          <label className="label">密码</label>
          <input
            type="password"
            className="input"
            placeholder="输入密码"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={loading}
          />
        </div>

        <button
          type="submit"
          disabled={loading || !username.trim() || !password.trim()}
          className="btn-primary w-full"
        >
          {loading ? '处理中...' : mode === 'login' ? '登录' : '注册并登录'}
        </button>
      </form>

      <div className="mt-6 text-center">
        <button
          onClick={onSwitchMode}
          className="text-xs text-[var(--text-muted)] hover:text-[var(--accent)] transition-colors"
        >
          {mode === 'login' ? '没有账号？点击注册' : '已有账号？点击登录'}
        </button>
      </div>
    </ModalShell>
  )
}
