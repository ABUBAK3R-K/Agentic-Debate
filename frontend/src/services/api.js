import axios from 'axios';

/**
 * The API surface, matching the backend exactly. Nothing here reaches for a
 * provider or a key — every LLM call happens server-side.
 */

// Empty means same-origin: dev and preview both proxy /api to the backend
// (see vite.config.js), so nothing here is a cross-origin request. Set
// VITE_API_URL to aim a deployed build at a backend on another host.
export const API_BASE = import.meta.env.VITE_API_URL || '';

const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
  // Compiling a persona is a live model call, and the backend paces and
  // retries around a provider's rate limit before it gives up. Generous
  // enough not to cut a slow-but-working call short; finite so a dead socket
  // ends as an error rather than a spinner that never stops.
  timeout: 300000,
});

export const createFriend = (name, rawDescription) =>
  api.post('/api/friends', { name, raw_description: rawDescription });

export const listFriends = () => api.get('/api/friends');

export const compilePersona = (friendId) =>
  api.post('/api/personas/compile', { friend_id: friendId });

export const savePersona = (friendId, persona) =>
  api.put(`/api/personas/${friendId}`, { persona });

export const createDebate = (topic, participantIds) =>
  api.post('/api/debates', { topic, participant_ids: participantIds });

export const startDebate = (debateId) =>
  api.post(`/api/debates/${debateId}/start`);

export const debateStreamUrl = (debateId) =>
  `${API_BASE}/api/debates/${debateId}/stream`;

export const getResult = (debateId) =>
  api.get(`/api/debates/${debateId}/result`);

/** Turn an axios failure into something worth showing a person. */
export function readError(error, fallback = 'Something went wrong.') {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;

  // No response at all. Axios calls this "Network Error", which tells a
  // person nothing about what to do next — name the thing that is missing.
  if (error?.code === 'ERR_NETWORK' || (error?.request && !error?.response)) {
    return `Could not reach the PersonaArena API at ${API_BASE || window.location.origin}. Check that the backend is running.`;
  }
  if (error?.code === 'ECONNABORTED') {
    return 'The API took too long to answer. The model provider may be rate limiting this key.';
  }

  return error?.message || fallback;
}

export default api;
