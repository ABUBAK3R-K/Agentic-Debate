import { useState, useEffect, useCallback } from 'react';

export function useSSE(url, options = {}) {
  const { onMessage, onPhaseStart, onPhaseEnd, onComplete, onError } = options;
  const [status, setStatus] = useState('idle'); // idle, connecting, connected, completed, error
  const [error, setError] = useState(null);
  const [eventSource, setEventSource] = useState(null);

  const connect = useCallback(async () => {
    if (status === 'connecting' || status === 'connected') return;
    
    // For POST requests to start the stream, we actually use fetch first
    // but standard EventSource only does GET.
    // Since our /start endpoint returns a stream directly from a POST,
    // we need a custom fetch-based reader to handle it properly, 
    // or we must ensure our backend supports standard GET streaming if we want to use EventSource.
    
    // Wait, let's look at the API we built:
    // POST /api/debates/{id}/start -> returns StreamingResponse
    // GET /api/debates/{id}/stream -> reconnect safe stream
    
    // The standard way to handle POST with SSE in JS is using fetch + ReadableStream.
    setStatus('connecting');
    setError(null);
    
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
        },
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      setStatus('connected');
      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        
        buffer += decoder.decode(value, { stream: true });
        
        // Process full SSE messages
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || ''; // Keep the last incomplete chunk in buffer
        
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const dataStr = line.substring(6).trim();
            if (dataStr === '[DONE]') {
              setStatus('completed');
              if (onComplete) onComplete();
              break;
            }
            
            try {
              const data = JSON.parse(dataStr);
              handleEvent(data);
            } catch (e) {
              console.error('Failed to parse SSE JSON:', dataStr);
            }
          }
        }
      }
    } catch (err) {
      console.error('SSE Error:', err);
      setStatus('error');
      setError(err.message);
      if (onError) onError(err);
    }
  }, [url, onMessage, onPhaseStart, onPhaseEnd, onComplete, onError]);

  const handleEvent = (event) => {
    switch (event.event_type) {
      case 'phase_start':
        if (onPhaseStart) onPhaseStart(event);
        break;
      case 'message':
        if (onMessage) onMessage(event);
        break;
      case 'phase_end':
        if (onPhaseEnd) onPhaseEnd(event);
        break;
      case 'debate_complete':
        setStatus('completed');
        if (onComplete) onComplete(event);
        break;
      case 'error':
        setStatus('error');
        setError(event.content);
        if (onError) onError(new Error(event.content));
        break;
      default:
        console.warn('Unknown event type:', event.event_type);
    }
  };

  const disconnect = useCallback(() => {
    // With fetch streaming, to truly cancel, we need an AbortController.
    // For simplicity in this iteration, we just set status to idle.
    // (A more robust version would use AbortController).
    setStatus('idle');
  }, []);

  return { connect, disconnect, status, error };
}
