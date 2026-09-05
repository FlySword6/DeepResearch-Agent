import { useState, useEffect, useCallback, useRef } from 'react'

/**
 * Custom hook for SSE (Server-Sent Events) connection.
 *
 * Connects to GET /api/research/{taskId}/stream and returns
 * an array of events with type and data fields.
 *
 * Handles: agent_status, agent_result, tool_call, tool_result,
 * report_chunk, error, completed.
 * Auto-closes on 'completed' event.
 * Cleans up on unmount.
 *
 * @param {string|null} taskId - The task ID to subscribe to.
 * @returns {{ events: Array, isConnected: boolean, isComplete: boolean, error: string|null }}
 */
export function useSSE(taskId) {
  const [events, setEvents] = useState([])
  const [isConnected, setIsConnected] = useState(false)
  const [isComplete, setIsComplete] = useState(false)
  const [error, setError] = useState(null)
  const eventSourceRef = useRef(null)
  const isCompleteRef = useRef(false)

  useEffect(() => {
    if (!taskId) {
      return
    }

    setEvents([])
    setIsConnected(false)
    setIsComplete(false)
    isCompleteRef.current = false
    setError(null)

    const url = `/api/research/${taskId}/stream`
    const eventSource = new EventSource(url)
    eventSourceRef.current = eventSource

    eventSource.onopen = () => {
      setIsConnected(true)
    }

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        const newEvent = {
          type: data.type || 'message',
          data: data,
          timestamp: new Date().toISOString(),
        }

        setEvents((prev) => [...prev, newEvent])

        if (data.type === 'completed') {
          setIsComplete(true)
          eventSource.close()
        }
      } catch {
        // If not JSON, treat as raw data event
        setEvents((prev) => [
          ...prev,
          {
            type: 'raw',
            data: { content: event.data },
            timestamp: new Date().toISOString(),
          },
        ])
      }
    }

    eventSource.addEventListener('agent_status', (event) => {
      try {
        const data = JSON.parse(event.data)
        setEvents((prev) => [
          ...prev,
          {
            type: 'agent_status',
            data,
            timestamp: new Date().toISOString(),
          },
        ])
      } catch {
        // ignore parse errors
      }
    })

    eventSource.addEventListener('agent_result', (event) => {
      try {
        const data = JSON.parse(event.data)
        setEvents((prev) => [
          ...prev,
          {
            type: 'agent_result',
            data,
            timestamp: new Date().toISOString(),
          },
        ])
      } catch {
        // ignore parse errors
      }
    })

    eventSource.addEventListener('skills_matched', (event) => {
      try {
        const data = JSON.parse(event.data)
        setEvents((prev) => [
          ...prev,
          {
            type: 'skills_matched',
            data,
            timestamp: new Date().toISOString(),
          },
        ])
      } catch {
        // ignore parse errors
      }
    })

    eventSource.addEventListener('tool_call', (event) => {
      try {
        const data = JSON.parse(event.data)
        setEvents((prev) => [
          ...prev,
          {
            type: 'tool_call',
            data,
            timestamp: new Date().toISOString(),
          },
        ])
      } catch {
        // ignore parse errors
      }
    })

    eventSource.addEventListener('tool_result', (event) => {
      try {
        const data = JSON.parse(event.data)
        setEvents((prev) => [
          ...prev,
          {
            type: 'tool_result',
            data,
            timestamp: new Date().toISOString(),
          },
        ])
      } catch {
        // ignore parse errors
      }
    })

    eventSource.addEventListener('report_chunk', (event) => {
      try {
        const data = JSON.parse(event.data)
        setEvents((prev) => [
          ...prev,
          {
            type: 'report_chunk',
            data,
            timestamp: new Date().toISOString(),
          },
        ])
      } catch {
        // ignore parse errors
      }
    })

    eventSource.addEventListener('error', (event) => {
      try {
        const data = JSON.parse(event.data)
        setError(data.message || 'An error occurred')
        setEvents((prev) => [
          ...prev,
          {
            type: 'error',
            data,
            timestamp: new Date().toISOString(),
          },
        ])
      } catch {
        setError('An error occurred')
      }
    })

    eventSource.addEventListener('completed', (event) => {
      try {
        const data = JSON.parse(event.data)
        setEvents((prev) => [
          ...prev,
          {
            type: 'completed',
            data,
            timestamp: new Date().toISOString(),
          },
        ])
      } catch {
        // ignore parse errors
      }
      isCompleteRef.current = true
      setIsComplete(true)
      eventSource.close()
    })

    eventSource.onerror = () => {
      setIsConnected(false)
      if (!isCompleteRef.current) {
        setError('Connection lost. The server may be unavailable.')
      }
    }

    return () => {
      eventSource.close()
      eventSourceRef.current = null
    }
  }, [taskId])

  return { events, isConnected, isComplete, error }
}
