// Klient API serwera (logowanie, użytkownicy, historia logowań).
// Aplikacja jest udostępniana przez serwer.py, dlatego adresy są względne.

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(method, path, token, body) {
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError('brak połączenia z serwerem', 0);
  }
  let data = null;
  try {
    data = await res.json();
  } catch {
    // odpowiedź bez treści JSON
  }
  if (!res.ok) throw new ApiError(data?.blad ?? `błąd HTTP ${res.status}`, res.status);
  return data;
}

export const login = (user, password) =>
  request('POST', '/api/login', null, { login: user, haslo: password, klient: 'web' });

export const logout = (s) => request('POST', '/api/logout', s.token, { klient: 'web' });

export const me = (s) => request('GET', '/api/ja', s.token);

export const listUsers = (s) => request('GET', '/api/uzytkownicy', s.token);

export const addUser = (s, user, password, admin) =>
  request('POST', '/api/uzytkownicy', s.token, { login: user, haslo: password, admin });

export const deleteUser = (s, user) =>
  request('DELETE', `/api/uzytkownicy/${encodeURIComponent(user)}`, s.token);

export const setAdmin = (s, user, admin) =>
  request('PATCH', `/api/uzytkownicy/${encodeURIComponent(user)}`, s.token, { admin });

export const setPassword = (s, user, password) =>
  request('PATCH', `/api/uzytkownicy/${encodeURIComponent(user)}`, s.token, { haslo: password });

export const loginHistory = (s, limit = 200, user = '') =>
  request('GET', `/api/logowania?limit=${limit}${user ? `&login=${encodeURIComponent(user)}` : ''}`, s.token);

// Zapamiętanie sesji w przeglądarce (wygoda użytkownika; sesję i tak weryfikuje serwer)
const KEY = 'robot_web_session';

export function loadSession() {
  try {
    return JSON.parse(localStorage.getItem(KEY) || 'null');
  } catch {
    return null;
  }
}

export function saveSession(s) {
  try {
    if (s) localStorage.setItem(KEY, JSON.stringify(s));
    else localStorage.removeItem(KEY);
  } catch {
    // pamięć przeglądarki niedostępna
  }
}
