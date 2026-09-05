import React, { createContext, useContext, useState, useCallback, useEffect } from 'react'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)       // { id, username } | null
  const [token, setToken] = useState(() => localStorage.getItem('auth_token'))
  const [loading, setLoading] = useState(true)

  // Restore user from token on mount
  useEffect(() => {
    if (token) {
      fetch('/api/auth/me', {
        headers: { Authorization: `Bearer ${token}` },
      })
        .then((r) => (r.ok ? r.json() : Promise.reject()))
        .then((u) => setUser(u))
        .catch(() => {
          localStorage.removeItem('auth_token')
          localStorage.removeItem('refresh_token')
          setToken(null)
          setUser(null)
        })
        .finally(() => setLoading(false))
    } else {
      setLoading(false)
    }
  }, [token])

  function extractErrorMessage(err) {
    if (!err) return '请求失败'
    if (typeof err.detail === 'string') return err.detail
    if (Array.isArray(err.detail)) return err.detail.map((d) => d.msg || d.message).join('; ') || '请求失败'
    if (typeof err.detail === 'object') return err.detail.message || JSON.stringify(err.detail)
    return String(err.detail || '请求失败')
  }

  const login = useCallback(async (username, password) => {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(extractErrorMessage(err))
    }
    const data = await res.json()
    localStorage.setItem('auth_token', data.access_token)
    localStorage.setItem('refresh_token', data.refresh_token)
    setToken(data.access_token)
    // Fetch user info
    const meRes = await fetch('/api/auth/me', {
      headers: { Authorization: `Bearer ${data.access_token}` },
    })
    if (meRes.ok) {
      setUser(await meRes.json())
    }
    return data
  }, [])

  const register = useCallback(async (username, password) => {
    const res = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(extractErrorMessage(err))
    }
    return res.json()
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem('auth_token')
    localStorage.removeItem('refresh_token')
    setToken(null)
    setUser(null)
  }, [])

  const authFetch = useCallback(
    (url, options = {}) => {
      const headers = { ...options.headers }
      if (token) {
        headers.Authorization = `Bearer ${token}`
      }
      return fetch(url, { ...options, headers })
    },
    [token]
  )

  return (
    <AuthContext.Provider value={{ user, token, loading, login, register, logout, authFetch }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
