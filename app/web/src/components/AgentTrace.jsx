import React, { useMemo } from 'react'

const AGENT_META = {
  system:   { label: '系统',      icon: '⚙️',  color: 'text-[var(--text-muted)]' },
  planner:  { label: '规划',      icon: '📋',  color: 'text-[var(--accent)]' },
  researcher: { label: '研究员',  icon: '🔍',  color: 'text-[#7fa05f]' },
  writer:   { label: '写作',      icon: '✍️',  color: 'text-[#a98fc0]' },
  reviewer: { label: '审查',      icon: '✅',  color: 'text-[#c08a3e]' },
  workflow: { label: '工作流',    icon: '🔄',  color: 'text-[var(--accent)]' },
  'harness planner': { label: 'Harness 规划', icon: '📋', color: 'text-[var(--accent)]' },
  'harness researcher': { label: 'Harness 研究', icon: '🔍', color: 'text-[#7fa05f]' },
  'harness writer': { label: 'Harness 写作', icon: '✍️', color: 'text-[#a98fc0]' },
  'harness reviewer': { label: 'Harness 审查', icon: '✅', color: 'text-[#c08a3e]' },
  'harness runtime': { label: 'Harness 运行时', icon: '🔄', color: 'text-[var(--accent)]' },
}

const STATUS_CFG = {
  running:   { label: '执行中', color: 'text-[var(--accent)]',  bg: 'bg-[var(--accent-glow)]', border: 'border-[var(--border-accent)]', pulse: true },
  completed: { label: '完成',   color: 'text-[var(--success)]', bg: 'bg-[var(--success-bg)]', border: 'border-[var(--success)]/20' },
  failed:    { label: '失败',   color: 'text-[var(--error)]',   bg: 'bg-[var(--error-bg)]',   border: 'border-[var(--error)]/20' },
  pending:   { label: '等待',   color: 'text-[var(--text-muted)]', bg: 'bg-[var(--surface)]',  border: 'border-[var(--border-subtle)]' },
}

function StatusBadge({ status }) {
  const cfg = STATUS_CFG[status] || STATUS_CFG.pending
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium ${cfg.color} ${cfg.bg}`}>
      {cfg.pulse && <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent)] animate-pulse" />}
      {cfg.label}
    </span>
  )
}

function AgentIcon({ type, status }) {
  const meta = AGENT_META[type] || { label: 'Agent', icon: '🤖', color: 'text-[var(--text-muted)]' }
  const isRunning = status === 'running'
  return (
    <div className={`relative w-8 h-8 rounded-xl flex items-center justify-center text-sm ${
      isRunning
        ? 'bg-[var(--accent-glow)] shadow-[0_0_10px_var(--accent-glow)]'
        : status === 'completed'
        ? 'bg-[var(--success-bg)]'
        : status === 'failed'
        ? 'bg-[var(--error-bg)]'
        : 'bg-[var(--surface)] border border-[var(--border-subtle)]'
    }`}>
      <span className={meta.color}>{meta.icon}</span>
    </div>
  )
}

function TimelineEntry({ entry, isLast }) {
  const cfg = STATUS_CFG[entry.status] || STATUS_CFG.pending
  return (
    <div className={`timeline-connector ${isLast ? '' : ''} animate-fade-in`}>
      <div className={`flex items-start gap-3 p-3 rounded-xl transition-all ${
        entry.status === 'running' ? `${cfg.bg} ${cfg.border} border` : ''
      }`}>
        <AgentIcon type={entry.agentType} status={entry.status} />
        <div className="flex-1 min-w-0 pt-0.5">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-[var(--text-primary)]">
              {entry.agentLabel}
            </span>
            <StatusBadge status={entry.status} />
          </div>
          {entry.detail && (
            <p className="text-xs text-[var(--text-muted)] mt-1 leading-relaxed">{entry.detail}</p>
          )}
          {entry.subEvents && entry.subEvents.length > 0 && (
            <div className="mt-2 pl-2 border-l border-[var(--border-subtle)] space-y-1">
              {entry.subEvents.map((se, si) => (
                <div key={si} className="text-xs text-[var(--text-muted)] flex items-center gap-1.5">
                  {se.status === 'running' && <span className="w-1 h-1 rounded-full bg-[var(--accent)] animate-pulse" />}
                  {se.status === 'completed' && <span className="w-1 h-1 rounded-full bg-[var(--success)]" />}
                  {se.status === 'failed' && <span className="w-1 h-1 rounded-full bg-[var(--error)]" />}
                  <span>{se.text}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        {entry.timestamp && (
          <span className="text-[11px] text-[var(--text-muted)] flex-shrink-0 pt-1">
            {new Date(entry.timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
          </span>
        )}
      </div>
    </div>
  )
}

export default function AgentTrace({ events, isComplete, isConnected }) {
  const matchedSkills = useMemo(() => {
    const seen = []
    for (const e of events || []) {
      if (e.type === 'skills_matched') {
        for (const s of e.data?.skills || []) {
          if (!seen.includes(s)) seen.push(s)
        }
      }
    }
    return seen
  }, [events])

  const { timelineEntries, latestEntry } = useMemo(() => {
    if (!events || events.length === 0) {
      return { timelineEntries: [], latestEntry: null }
    }

    // Build timeline: group consecutive tool events under the last agent_status
    const entries = []
    let currentEntry = null

    events.forEach((event, idx) => {
      const { type, data, timestamp } = event

      if (type === 'agent_status') {
        const agentName = data?.agent || 'unknown'
        const agentType = agentName.toLowerCase()
        const meta = AGENT_META[agentType] || AGENT_META.system
        const status = data?.status || 'running'

        currentEntry = {
          id: idx,
          agentLabel: meta.label,
          agentType,
          status,
          detail: data?.detail || null,
          timestamp,
          subEvents: [],
        }
        entries.push(currentEntry)
      } else if (type === 'tool_call') {
        if (currentEntry && currentEntry.subEvents) {
          currentEntry.subEvents.push({
            status: 'running',
            text: `🔧 ${data?.tool || 'tool'} — ${(data?.params ? JSON.stringify(data.params).slice(0, 60) : data?.query || '')}`,
          })
        }
      } else if (type === 'tool_result') {
        if (currentEntry && currentEntry.subEvents) {
          const existing = currentEntry.subEvents[currentEntry.subEvents.length - 1]
          if (existing && existing.status === 'running') {
            existing.status = 'completed'
            existing.text = existing.text.replace(/^🔧/, '✅')
          }
        }
      } else if (type === 'report_chunk') {
        // skip in timeline
      } else if (type === 'error') {
        if (currentEntry) {
          currentEntry.status = 'failed'
          currentEntry.detail = data?.message || '发生错误'
        } else {
          entries.push({
            id: idx,
            agentLabel: '错误',
            agentType: 'system',
            status: 'failed',
            detail: data?.message || '发生错误',
            timestamp,
            subEvents: [],
          })
        }
      } else if (type === 'completed') {
        if (currentEntry) currentEntry.status = 'completed'
      }
    })

    return {
      timelineEntries: entries,
      latestEntry: entries[entries.length - 1] || null,
    }
  }, [events])

  if (!events || events.length === 0) return null

  // Show only the current status card.
  const displayEntries = latestEntry ? [latestEntry] : []

  return (
    <div className="animate-fade-in">
      <div className="glass-card p-5">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <h2 className="text-base font-semibold text-[var(--text-primary)]">
              当前执行状态
            </h2>
          </div>
          <div className="flex items-center gap-2 text-xs text-[var(--text-muted)]">
            <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-[var(--success)] shadow-[0_0_6px_var(--success)]' : 'bg-[var(--text-muted)]'}`} />
            {isConnected ? '已连接' : '未连接'}
          </div>
        </div>

        {/* Matched skills */}
        {matchedSkills.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap mb-3">
            <span className="text-[11px] text-[var(--text-muted)]">已应用技能:</span>
            {matchedSkills.map((s) => (
              <span
                key={s}
                className="text-[11px] px-2 py-0.5 rounded-full bg-[var(--accent-glow)] text-[var(--accent)]"
              >
                {s}
              </span>
            ))}
          </div>
        )}

        {/* Timeline */}
        <div className="space-y-1">
          {displayEntries.length === 0 && (
            <div className="text-center py-8 text-sm text-[var(--text-muted)]">
              <div className="shimmer w-48 h-3 rounded mx-auto mb-2" />
              <div className="shimmer w-32 h-3 rounded mx-auto" />
            </div>
          )}
          {displayEntries.map((entry, idx) => (
            <TimelineEntry
              key={entry.id}
              entry={entry}
              isLast={idx === displayEntries.length - 1}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
