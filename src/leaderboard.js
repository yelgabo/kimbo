import { API_BASE, PLAYER_ID_KEY } from './config.js';

function newUuidV4() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  const b = new Uint8Array(16);
  crypto.getRandomValues(b);
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = Array.from(b, (x) => x.toString(16).padStart(2, '0'));
  return `${h.slice(0,4).join('')}-${h.slice(4,6).join('')}-${h.slice(6,8).join('')}-${h.slice(8,10).join('')}-${h.slice(10,16).join('')}`;
}

export function createLeaderboard() {
  let cachedId = null;

  function playerId() {
    if (cachedId) return cachedId;
    let id = localStorage.getItem(PLAYER_ID_KEY);
    if (!id || !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(id)) {
      id = newUuidV4();
      localStorage.setItem(PLAYER_ID_KEY, id);
    }
    cachedId = id;
    return id;
  }

  function displayName() {
    return 'anon-' + playerId().slice(0, 4);
  }

  async function submit({ score, lines, level, durationMs, seed, replayLog }) {
    try {
      const res = await fetch(`${API_BASE}/api/scores`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          playerId: playerId(),
          displayName: displayName(),
          score, lines, level, durationMs, seed, replayLog,
        }),
      });
      if (!res.ok) {
        console.warn('leaderboard submit failed:', res.status);
        return null;
      }
      return await res.json();
    } catch (e) {
      console.warn('leaderboard submit error:', e);
      return null;
    }
  }

  async function fetchReplay(id) {
    try {
      const res = await fetch(`${API_BASE}/api/replay/${encodeURIComponent(id)}`);
      if (!res.ok) {
        console.warn('replay fetch failed:', res.status);
        return null;
      }
      return await res.json();
    } catch (e) {
      console.warn('replay fetch error:', e);
      return null;
    }
  }

  async function fetchTop(limit = 10) {
    try {
      const res = await fetch(`${API_BASE}/api/leaderboard?limit=${encodeURIComponent(limit)}`);
      if (!res.ok) {
        console.warn('leaderboard fetch failed:', res.status);
        return [];
      }
      const data = await res.json();
      return Array.isArray(data.entries) ? data.entries : [];
    } catch (e) {
      console.warn('leaderboard fetch error:', e);
      return [];
    }
  }

  return { playerId, displayName, submit, fetchTop, fetchReplay };
}
