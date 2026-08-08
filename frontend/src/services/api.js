import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
});

// ─── Friends ───────────────────────────────────────────────
export const createFriend = (data) => api.post('/api/friends', data);
export const getFriends = () => api.get('/api/friends');
export const getFriend = (id) => api.get(`/api/friends/${id}`);
export const updateFriend = (id, data) => api.put(`/api/friends/${id}`, data);
export const deleteFriend = (id) => api.delete(`/api/friends/${id}`);

// ─── Personas ──────────────────────────────────────────────
export const compilePersona = (friendId) =>
  api.post('/api/personas/compile', { friend_id: friendId });
export const updatePersona = (friendId, persona) =>
  api.put(`/api/personas/${friendId}`, { persona });

// ─── Debates ───────────────────────────────────────────────
export const createDebate = (data) => api.post('/api/debates', data);
export const getDebates = () => api.get('/api/debates');
export const getDebate = (id) => api.get(`/api/debates/${id}`);
export const getDebateResult = (id) => api.get(`/api/debates/${id}/result`);

// ─── SSE Stream ────────────────────────────────────────────
export const startDebateStream = (debateId) => {
  return `${API_BASE}/api/debates/${debateId}/start`;
};

export default api;
