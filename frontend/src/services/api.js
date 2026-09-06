import axios from 'axios';

/**
 * The API surface, matching the backend exactly. Nothing here reaches for a
 * provider or a key — every LLM call happens server-side.
 */

export const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
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
  return error?.message || fallback;
}

export default api;
