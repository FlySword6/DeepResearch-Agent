import React, { createContext, useContext, useState, useCallback, useEffect } from 'react'

const AuthContext = createContext(null)

function extractErrorMessage(err) {
  if (!err) return '请求失败'
  if (typeof err.detail === 'string') return err.detail
  if (Array.isArray(err.detail)) return err.detail.map((d) => d.msg || d.message).join('; ') || '请求失败'
  if (typeof err.detail === 'object') return err.detail.message || JSON.stringify(err.detail)
  return String(err.detail || '请求失败')
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [token, setToken] = useState(() => localStorage.getItem('auth_token'))
  const [loading, setLoading] = useState(true)

  const clearAuth = useCallback(() => {
    localStorage.removeItem('auth_token')
    localStorage.removeItem('refresh_token')
    setToken(null)
    setUser(null)
  }, [])

  const saveTokens = useCallback((data) => {
    localStorage.setItem('auth_token', data.access_token)
    localStorage.setItem('refresh_token', data.refresh_token)
    setToken(data.access_token)
    return data.access_token
  }, [])

  const fetchMe = useCallback(async (accessToken) => {
    const res = await fetch('/api/auth/me', {
      headers: { Authorization: `Bearer ${accessToken}` },
    })
    if (!res.ok) throw new Error('身份校验失败')
    return res.json()
  }, [])

  const refreshAccessToken = useCallback(async () => {
    const refreshToken = localStorage.getItem('refresh_token')
    if (!refreshToken) return null

    const res = await fetch('/api/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
    if (!res.ok) return null

    const data = await res.json()
    return saveTokens(data)
  }, [saveTokens])

  useEffect(() => {
    let cancelled = false

    async function restoreAuth() {
      if (!token) {
        setLoading(false)
        return
      }

      try {
        const currentUser = await fetchMe(token)
        if (!cancelled) setUser(currentUser)
      } catch {
        try {
          const newToken = await refreshAccessToken()
          if (!newToken) throw new Error('刷新登录态失败')

          const currentUser = await fetchMe(newToken)
          if (!cancelled) setUser(currentUser)
        } catch {
          if (!cancelled) clearAuth()
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    restoreAuth()
    return () => {
      cancelled = true
    }
  }, [token, fetchMe, refreshAccessToken, clearAuth])

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
    const accessToken = saveTokens(data)
    setUser(await fetchMe(accessToken))
    return data
  }, [fetchMe, saveTokens])

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
    clearAuth()
  }, [clearAuth])

  const authFetch = useCallback(async (url, options = {}) => {
    const buildOptions = (accessToken) => {
      const headers = { ...options.headers }
      if (accessToken) {
        headers.Authorization = `Bearer ${accessToken}`
      }
      return { ...options, headers }
    }

    let response = await fetch(url, buildOptions(token))
    if (response.status !== 401) return response

    const newToken = await refreshAccessToken()
    if (!newToken) {
      clearAuth()
      return response
    }

    response = await fetch(url, buildOptions(newToken))
    return response
  }, [token, refreshAccessToken, clearAuth])

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
