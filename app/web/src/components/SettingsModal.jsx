import React, { useState, useEffect } from 'react'
import ModalShell from './ModalShell'

const PROVIDERS = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'anthropic', label: 'Anthropic' },
]

const DEFAULT_BASE_URLS = {
  openai: 'https://api.openai.com/v1',
  anthropic: 'https://api.anthropic.com',
}

export default function SettingsModal({ isOpen, onClose, onSaved }) {
  const [provider, setProvider] = useState('openai')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('gpt-4o')
  const [baseUrl, setBaseUrl] = useState(DEFAULT_BASE_URLS.openai)
  const [embeddingModel, setEmbeddingModel] = useState('text-embedding-v3')
  const [embeddingApiKey, setEmbeddingApiKey] = useState('')
  const [embeddingBaseUrl, setEmbeddingBaseUrl] = useState('https://api.openai.com/v1')
  const [embeddingConfigured, setEmbeddingConfigured] = useState(false)
  const [rerankerEnabled, setRerankerEnabled] = useState(false)
  const [rerankerApiKey, setRerankerApiKey] = useState('')
  const [rerankerBaseUrl, setRerankerBaseUrl] = useState('https://openrouter.ai/api/v1/rerank')
  const [rerankerModel, setRerankerModel] = useState('nvidia/llama-nemotron-rerank-vl-1b-v2:free')
  const [rerankerConfigured, setRerankerConfigured] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)
  const [initialized, setInitialized] = useState(false)

  // Load current settings on open
  useEffect(() => {
    if (!isOpen || initialized) return
    fetch('/api/settings')
      .then((r) => r.json())
      .then((data) => {
        if (data.configured) {
          setProvider(data.provider)
          setApiKey('')
          setModel(data.model)
          setBaseUrl(data.base_url || DEFAULT_BASE_URLS[data.provider] || '')
          setEmbeddingModel(data.embedding_model || 'text-embedding-v3')
          setEmbeddingBaseUrl(data.embedding_base_url || 'https://api.openai.com/v1')
          setEmbeddingConfigured(data.embedding_configured || false)
          setRerankerEnabled(data.reranker_enabled || false)
          setRerankerBaseUrl(data.reranker_base_url || 'https://openrouter.ai/api/v1/rerank')
          setRerankerModel(data.reranker_model || 'nvidia/llama-nemotron-rerank-vl-1b-v2:free')
          setRerankerConfigured(Boolean(data.reranker_api_key))
        }
        setInitialized(true)
      })
      .catch(() => {})
  }, [isOpen, initialized])

  // Reset state when modal opens
  useEffect(() => {
    if (isOpen) {
      setError(null)
      setSuccess(null)
      setSaving(false)
      setInitialized(false)
    }
  }, [isOpen])

  const handleProviderChange = (newProvider) => {
    setProvider(newProvider)
    if (!baseUrl || baseUrl === DEFAULT_BASE_URLS[provider]) {
      setBaseUrl(DEFAULT_BASE_URLS[newProvider] || '')
    }
  }

  const handleSave = async () => {
    if (!apiKey.trim()) {
      setError('请输入 API Key')
      return
    }
    if (!model.trim()) {
      setError('请输入模型名称')
      return
    }

    setSaving(true)
    setError(null)
    setSuccess(null)

    try {
      const response = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider,
          api_key: apiKey.trim(),
          model: model.trim(),
          base_url: baseUrl.trim() || DEFAULT_BASE_URLS[provider],
          embedding_model: embeddingModel.trim() || 'text-embedding-v3',
          embedding_api_key: embeddingApiKey.trim() || undefined,
          embedding_base_url: embeddingBaseUrl.trim(),
          reranker_enabled: rerankerEnabled,
          reranker_api_key: rerankerApiKey.trim() || undefined,
          reranker_base_url: rerankerBaseUrl.trim() || 'https://openrouter.ai/api/v1/rerank',
          reranker_model: rerankerModel.trim() || 'nvidia/llama-nemotron-rerank-vl-1b-v2:free',
        }),
      })
      const result = await response.json()
      if (result.success) {
        setSuccess(result.message || '配置已保存')
        setTimeout(() => {
          if (onSaved) onSaved()
          onClose()
        }, 800)
      } else {
        setError(result.message || '配置测试失败')
      }
    } catch (err) {
      setError('保存失败: ' + (err.message || '网络错误'))
    } finally {
      setSaving(false)
    }
  }

  if (!isOpen) return null

  return (
    <ModalShell isOpen={isOpen} onClose={onClose} title="LLM 配置" width="md">
      <div className="space-y-4">
          {/* Provider */}
          <div>
            <label className="label">Provider</label>
            <div className="flex gap-2">
              {PROVIDERS.map((p) => (
                <button
                  key={p.value}
                  onClick={() => handleProviderChange(p.value)}
                  className={`flex-1 px-3 py-2 text-sm rounded-lg border transition-all ${
                    provider === p.value
                      ? 'border-[var(--accent)] bg-[var(--accent-glow)] text-[var(--accent)]'
                      : 'border-[var(--border-subtle)] text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-[var(--surface-hover)]'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* API Key */}
          <div>
            <label className="label">API Key</label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
              className="input"
            />
          </div>

          {/* Model */}
          <div>
            <label className="label">Model</label>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="gpt-4o"
              className="input"
            />
          </div>

          {/* Base URL */}
          <div>
            <label className="label">Base URL</label>
            <input
              type="text"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder={DEFAULT_BASE_URLS[provider]}
              className="input"
            />
          </div>

          {/* Embedding config */}
          <div className="pt-4 border-t border-[var(--border-subtle)]">
            <div className="flex items-center justify-between mb-3">
              <label className="text-sm font-medium text-[var(--text-primary)]">
                Embedding 配置
              </label>
              {embeddingConfigured && (
                <span className="text-[11px] px-2 py-0.5 rounded-full bg-[var(--success-bg)] text-[var(--success)]">
                  已配置 Key
                </span>
              )}
            </div>
            <p className="text-xs text-[var(--text-muted)] mb-3">
              用于 RAG 知识库向量化，支持 OpenAI 兼容接口（含 DashScope）。留空 Key 则保留已保存的配置。
            </p>
            <div className="space-y-4">
              <div>
                <label className="label">Embedding API Key</label>
                <input
                  type="password"
                  value={embeddingApiKey}
                  onChange={(e) => setEmbeddingApiKey(e.target.value)}
                  placeholder={embeddingConfigured ? '已配置，留空则保留' : 'sk-...'}
                  className="input"
                />
              </div>
              <div>
                <label className="label">Embedding Base URL</label>
                <input
                  type="text"
                  value={embeddingBaseUrl}
                  onChange={(e) => setEmbeddingBaseUrl(e.target.value)}
                  placeholder="https://api.openai.com/v1"
                  className="input"
                />
              </div>
              <div>
                <label className="label">Embedding 模型</label>
                <input
                  type="text"
                  value={embeddingModel}
                  onChange={(e) => setEmbeddingModel(e.target.value)}
                  placeholder="text-embedding-v3"
                  className="input"
                />
              </div>
            </div>
          </div>

          {/* Reranker config */}
          <div className="pt-4 border-t border-[var(--border-subtle)]">
            <div className="flex items-center justify-between mb-3">
              <label className="text-sm font-medium text-[var(--text-primary)]">
                Rerank 重排序配置
              </label>
              {rerankerConfigured && (
                <span className="text-[11px] px-2 py-0.5 rounded-full bg-[var(--success-bg)] text-[var(--success)]">
                  已配置 Key
                </span>
              )}
            </div>
            <p className="text-xs text-[var(--text-muted)] mb-3">
              对混合检索结果按相关性重排序，默认使用 OpenRouter 免费模型 nvidia/llama-nemotron-rerank-vl-1b-v2:free。
            </p>
            <label className="flex items-center gap-2 cursor-pointer mb-3">
              <input
                type="checkbox"
                checked={rerankerEnabled}
                onChange={(e) => setRerankerEnabled(e.target.checked)}
                className="w-4 h-4 rounded accent-[var(--accent)]"
              />
              <span className="text-xs text-[var(--text-muted)]">
                {rerankerEnabled ? '已启用' : '已停用'}
              </span>
            </label>
            <div className="space-y-4">
              <div>
                <label className="label">Rerank API Key（OpenRouter）</label>
                <input
                  type="password"
                  value={rerankerApiKey}
                  onChange={(e) => setRerankerApiKey(e.target.value)}
                  placeholder={rerankerConfigured ? '已配置，留空则保留' : 'sk-or-...'}
                  className="input"
                />
              </div>
              <div>
                <label className="label">Rerank API URL</label>
                <input
                  type="text"
                  value={rerankerBaseUrl}
                  onChange={(e) => setRerankerBaseUrl(e.target.value)}
                  placeholder="https://openrouter.ai/api/v1/rerank"
                  className="input"
                />
              </div>
              <div>
                <label className="label">Rerank 模型</label>
                <input
                  type="text"
                  value={rerankerModel}
                  onChange={(e) => setRerankerModel(e.target.value)}
                  placeholder="nvidia/llama-nemotron-rerank-vl-1b-v2:free"
                  className="input"
                />
              </div>
            </div>
          </div>

          {/* Status messages */}
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

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 pt-4 border-t border-[var(--border-subtle)]">
          <button
            onClick={onClose}
            className="btn-ghost"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="btn-primary flex items-center gap-2"
          >
            {saving && (
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            )}
            {saving ? '测试连接中...' : '保存'}
          </button>
        </div>
      </div>
    </ModalShell>
  )
}
