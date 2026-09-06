import { useEffect, useReducer, useRef } from 'react';
import { debateStreamUrl } from '../services/api';

/**
 * Subscribes to a debate's SSE stream.
 *
 * The stream is the debate: sides are announced, turns open, text arrives a
 * few characters at a time, and each turn closes with an authoritative
 * `message` event. Token events are a live preview — `message` is the truth,
 * so a turn the backend had to regenerate simply replaces what was previewed.
 */

const initialState = {
  status: 'connecting', // connecting | live | complete | error
  topic: null,
  sides: [],            // [{ participantId, name, position }]
  phase: null,
  round: null,
  turns: [],            // [{ id, participantId, phase, round, text, streaming, failed }]
  verdict: null,
  error: null,
};

function reducer(state, event) {
  switch (event.event_type) {
    case 'phase_start':
      if (event.phase === 'POSITIONING') {
        return {
          ...state,
          status: 'live',
          topic: event.data?.topic ?? state.topic,
          sides: (event.data?.participants || []).map((p) => ({
            participantId: p.participant_id,
            name: p.name,
            position: p.position,
          })),
        };
      }
      return {
        ...state,
        status: 'live',
        phase: event.phase,
        round: event.round_number ?? state.round,
      };

    case 'turn_start':
      return {
        ...state,
        phase: event.phase,
        round: event.round_number ?? state.round,
        turns: [
          ...state.turns,
          {
            id: `${event.participant_id}-${event.phase}`,
            participantId: event.participant_id,
            phase: event.phase,
            round: event.round_number,
            text: '',
            streaming: true,
            failed: false,
          },
        ],
      };

    case 'token':
      return {
        ...state,
        turns: updateLastTurn(state.turns, event.participant_id, (turn) => ({
          ...turn,
          text: turn.text + (event.content || ''),
        })),
      };

    case 'message':
      return {
        ...state,
        turns: updateLastTurn(state.turns, event.participant_id, (turn) => ({
          ...turn,
          text: event.content || '',
          streaming: false,
        })),
      };

    case 'turn_failed':
      return {
        ...state,
        turns: updateLastTurn(state.turns, event.participant_id, (turn) => ({
          ...turn,
          text: '',
          streaming: false,
          failed: true,
        })),
      };

    case 'debate_complete':
      return { ...state, status: 'complete', phase: 'COMPLETED', verdict: event.data };

    case 'error':
      return { ...state, status: 'error', error: event.content };

    default:
      return state;
  }
}

/** Turns arrive one at a time, so the open turn is the last one for a speaker. */
function updateLastTurn(turns, participantId, update) {
  const index = turns.map((t) => t.participantId).lastIndexOf(participantId);
  if (index === -1) return turns;
  const next = turns.slice();
  next[index] = update(next[index]);
  return next;
}

export function useDebateStream(debateId, enabled) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const sourceRef = useRef(null);

  useEffect(() => {
    if (!debateId || !enabled) return undefined;

    const source = new EventSource(debateStreamUrl(debateId));
    sourceRef.current = source;

    source.onmessage = (message) => {
      if (message.data === '[DONE]') {
        source.close();
        return;
      }
      try {
        dispatch(JSON.parse(message.data));
      } catch {
        // A malformed frame is not worth tearing the stream down for.
      }
    };

    source.onerror = () => {
      // EventSource retries on its own; once the debate is done the server
      // closes the response, and there is nothing left to reconnect to.
      if (source.readyState === EventSource.CLOSED) source.close();
    };

    return () => source.close();
  }, [debateId, enabled]);

  useEffect(() => {
    if (state.status === 'complete' || state.status === 'error') {
      sourceRef.current?.close();
    }
  }, [state.status]);

  return state;
}
