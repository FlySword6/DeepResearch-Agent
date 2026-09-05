import React from 'react'

const WIDTH_CLASSES = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-2xl',
}

export default function ModalShell({ isOpen, onClose, title, width = 'md', children }) {
  if (!isOpen) return null

  const widthClass = WIDTH_CLASSES[width] || WIDTH_CLASSES.md

  return (
    <div className="modal-overlay">
      <div className="absolute inset-0" onClick={onClose} />
      <div className={`modal-card ${widthClass}`}>
        <div className="modal-header">
          <h2 className="modal-title">{title}</h2>
          <button onClick={onClose} className="modal-close" aria-label="关闭">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  )
}
