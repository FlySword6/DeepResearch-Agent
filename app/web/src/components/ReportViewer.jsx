import React, { useState, useMemo } from 'react'

function renderInline(text) {
  if (!text) return null
  let processed = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  const parts = processed.split(/(\*\*.+?\*\*)/)
  return parts.map((part, idx) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={idx} className="font-semibold text-[var(--text-primary)]">{part.slice(2, -2)}</strong>
    }
    // Italic
    const italicParts = part.split(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/)
    if (italicParts.length > 1) {
      return italicParts.map((ip, ij) => {
        if (ip.startsWith('*') && ip.endsWith('*')) {
          return <em key={`${idx}-${ij}`} className="italic">{ip.slice(1, -1)}</em>
        }
        return renderCodeAndLinks(ip, `${idx}-${ij}`)
      })
    }
    return renderCodeAndLinks(part, `${idx}`)
  })
}

function renderCodeAndLinks(text, key) {
  const codeParts = text.split(/(`[^`]+`)/)
  return codeParts.map((cp, cj) => {
    if (cp.startsWith('`') && cp.endsWith('`')) {
      return <code key={`${key}-${cj}`} className="px-1 py-0.5 rounded text-sm font-mono text-[var(--accent)] bg-black/20">{cp.slice(1, -1)}</code>
    }
    const linkParts = cp.split(/(\[[^\]]+\]\([^)]+\))/)
    return linkParts.map((lp, lj) => {
      const linkMatch = lp.match(/\[([^\]]+)\]\(([^)]+)\)/)
      if (linkMatch) {
        return <a key={`${key}-${cj}-${lj}`} href={linkMatch[2]} target="_blank" rel="noopener noreferrer" className="text-[var(--accent)] hover:underline">{linkMatch[1]}</a>
      }
      return lp
    })
  })
}

function ReportRenderer({ content }) {
  const elements = useMemo(() => {
    if (!content) return null
    const lines = content.split('\n')
    const els = []
    let inCodeBlock = false
    let codeBuffer = []
    let codeBlockLang = ''
    let codeKey = 0
    let inList = false
    let listType = null

    function flushList() {
      if (listType === 'ul') {
        els.push(<ul key={`ul-${codeKey++}`} className="list-disc pl-5 my-3 space-y-1">{listItems}</ul>)
      } else if (listType === 'ol') {
        els.push(<ol key={`ol-${codeKey++}`} className="list-decimal pl-5 my-3 space-y-1">{listItems}</ol>)
      }
      listItems = []
      listType = null
    }

    let listItems = []

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i]

      if (line.trim().startsWith('```')) {
        flushList()
        if (inCodeBlock) {
          const lang = codeBlockLang || ''
          els.push(
            <div key={`code-${codeKey++}`} className="my-4 rounded-xl overflow-hidden border border-[var(--border-subtle)]">
              {lang && <div className="px-4 py-1.5 text-[11px] text-[var(--text-muted)] bg-black/20 border-b border-[var(--border-subtle)] font-mono">{lang}</div>}
              <pre className="p-4 overflow-x-auto text-sm leading-relaxed bg-black/30"><code>{codeBuffer.join('\n')}</code></pre>
            </div>
          )
          codeBuffer = []
          codeBlockLang = ''
          inCodeBlock = false
        } else {
          inCodeBlock = true
          codeBlockLang = line.trim().slice(3).trim()
        }
        continue
      }
      if (inCodeBlock) { codeBuffer.push(line); continue }

      if (line.trim() === '') {
        // Only flush list if next non-empty line isn't the same list type
        if (listType) {
          const nextNonEmpty = lines.slice(i + 1).find((l) => l.trim() !== '')
          const nextIsOl = nextNonEmpty && /^\d+\.\s/.test(nextNonEmpty)
          const nextIsUl = nextNonEmpty && /^[-*]\s/.test(nextNonEmpty)
          if ((listType === 'ol' && nextIsOl) || (listType === 'ul' && nextIsUl)) {
            continue
          }
        }
        flushList()
        continue
      }
      if (line.trim() === '---') { flushList(); els.push(<hr key={`hr-${i}`} className="my-8 border-[var(--border-subtle)]" />); continue }

      const hMatch = line.match(/^(#{1,6})\s+(.+)$/)
      if (hMatch) {
        flushList()
        const level = hMatch[1].length
        const text = renderInline(hMatch[2])
        const styles = {
          1: 'text-xl font-bold mt-8 mb-4 text-[var(--text-primary)] border-b border-[var(--border-subtle)] pb-2',
          2: 'text-lg font-semibold mt-6 mb-3 text-[var(--text-primary)]',
          3: 'text-base font-medium mt-5 mb-2 text-[var(--text-secondary)]',
        }
        els.push(
          React.createElement(`h${level}`, { key: `h-${i}`, className: styles[level] || 'text-sm font-medium mt-4 mb-2 text-[var(--text-secondary)]' }, text)
        )
        continue
      }

      if (line.startsWith('> ')) {
        flushList()
        const text = renderInline(line.slice(2))
        els.push(<blockquote key={`bq-${i}`} className="border-l-2 border-[var(--accent)] pl-4 my-4 text-[var(--text-muted)] italic">{text}</blockquote>)
        continue
      }

      const ulMatch = line.match(/^[-*]\s+(.+)$/)
      if (ulMatch) {
        if (listType !== 'ul') flushList()
        listType = 'ul'
        listItems.push(<li key={`li-${i}`} className="text-[var(--text-secondary)] leading-relaxed">{renderInline(ulMatch[1])}</li>)
        continue
      }

      const olMatch = line.match(/^(\d+)\.\s+(.+)$/)
      if (olMatch) {
        if (listType !== 'ol') flushList()
        listType = 'ol'
        listItems.push(<li key={`oli-${i}`} className="text-[var(--text-secondary)] leading-relaxed">{renderInline(olMatch[2])}</li>)
        continue
      }

      flushList()
      els.push(<p key={`p-${i}`} className="my-2 leading-relaxed text-[var(--text-secondary)]">{renderInline(line)}</p>)
    }

    flushList()
    if (inCodeBlock) {
      els.push(
        <pre key={`code-${codeKey}`} className="my-4 p-4 rounded-xl overflow-x-auto text-sm bg-black/30 border border-[var(--border-subtle)]"><code>{codeBuffer.join('\n')}</code></pre>
      )
    }

    return els
  }, [content])

  if (!content) return null
  return <div className="report-body">{elements}</div>
}

export default function ReportViewer({ taskId, content, events }) {
  const [showCitations, setShowCitations] = useState(false)

  const reportContent = useMemo(() => {
    if (!content) return ''
    const completedEvent = events?.find((e) => e.type === 'completed')
    return completedEvent?.data?.report || content
  }, [content, events])

  const citations = useMemo(() => {
    const result = []
    const urlRegex = /\[([^\]]+)\]\(([^)]+)\)/g
    let match
    while ((match = urlRegex.exec(reportContent)) !== null) {
      result.push({ title: match[1], url: match[2] })
    }
    return result
  }, [reportContent])

  const handleDownloadMarkdown = () => {
    const blob = new Blob([reportContent], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `research-report-${taskId || 'download'}.md`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  const handleDownloadPDF = async () => {
    try {
      const response = await fetch(`/api/reports/${taskId}?format=pdf`)
      if (!response.ok) {
        const err = await response.json().catch(() => ({}))
        throw new Error(err.detail || 'PDF 生成失败')
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `research-report-${taskId || 'download'}.pdf`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (err) {
      alert(err.message || 'PDF 下载失败，请使用 MD 格式下载')
    }
  }

  if (!content) return null

  return (
    <div className="animate-fade-in h-full">
      <div className="glass-card overflow-hidden h-full flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border-subtle)] bg-[var(--surface)]/50">
          <div className="flex items-center gap-3">
            <h2 className="text-base font-semibold text-[var(--text-primary)]">
              研究报告
            </h2>
            {citations.length > 0 && (
              <button
                onClick={() => setShowCitations(!showCitations)}
                className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all ${
                  showCitations
                    ? 'bg-[var(--accent-glow)] text-[var(--accent)] border border-[var(--border-accent)]'
                    : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)] border border-[var(--border-subtle)] hover:border-[var(--border-default)]'
                }`}
              >
                引用 {citations.length}
              </button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleDownloadMarkdown}
              className="px-4 py-1.5 rounded-lg text-xs font-semibold text-white bg-[var(--accent)] hover:shadow-[0_0_16px_var(--accent-glow)] active:scale-[0.97] transition-all"
            >
              下载 MD
            </button>
            <button
              onClick={handleDownloadPDF}
              className="px-4 py-1.5 rounded-lg text-xs font-semibold text-white bg-[var(--accent)] hover:shadow-[0_0_16px_var(--accent-glow)] active:scale-[0.97] transition-all"
            >
              下载 PDF
            </button>
          </div>
        </div>

        {/* Content area */}
        <div className="flex flex-col lg:flex-row flex-1 min-h-0 overflow-y-auto">
          <div className="flex-1 p-5 lg:p-8 min-w-0">
            <ReportRenderer content={reportContent} />
          </div>

          {showCitations && citations.length > 0 && (
            <div className="w-full lg:w-72 border-t lg:border-t-0 lg:border-l border-[var(--border-subtle)] bg-[var(--surface)]/30 p-5">
              <h3 className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider mb-4">引用来源</h3>
              <div className="space-y-3">
                {citations.map((cit, idx) => (
                  <div key={idx}>
                    {cit.url ? (
                      <a
                        href={cit.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-[var(--accent)] hover:underline block leading-relaxed"
                      >
                        {cit.title || cit.url}
                      </a>
                    ) : (
                      <span className="text-xs text-[var(--text-secondary)]">{cit.title || `来源 ${idx + 1}`}</span>
                    )}
                    {cit.url && (
                      <span className="text-[11px] text-[var(--text-muted)] block truncate mt-0.5">{cit.url}</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
