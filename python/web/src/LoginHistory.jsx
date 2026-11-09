// Historia logowań zapisywana w bazie MongoDB (widok administratora).
import { useCallback, useEffect, useState } from 'react';
import { loginHistory } from './api';

const KLIENT = { pc: 'aplikacja na komputer', telefon: 'telefon', web: 'przeglądarka' };

export function LoginHistory({ session }) {
  const [entries, setEntries] = useState([]);
  const [filter, setFilter] = useState('');
  const [limit, setLimit] = useState(100);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setEntries(await loginHistory(session, limit, filter.trim()));
    } catch (e) {
      setError(e.message);
    }
  }, [session, limit, filter]);

  useEffect(() => {
    load();
  }, [load]);

  const failed = entries.filter((e) => e.zdarzenie === 'nieudane logowanie').length;

  return (
    <div className="card history">
      <div className="history-head">
        <h2>Historia logowań</h2>
        <input placeholder="filtr: login" value={filter} onChange={(e) => setFilter(e.target.value)} />
        <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
          {[50, 100, 500].map((n) => <option key={n} value={n}>ostatnie {n}</option>)}
        </select>
        <button onClick={load}>Odśwież</button>
      </div>
      {error && <div className="error">{error}</div>}
      <p className="muted">Wpisów: {entries.length}{failed ? `, w tym nieudanych logowań: ${failed}` : ''}</p>
      <table>
        <thead>
          <tr><th>Czas</th><th>Użytkownik</th><th>Zdarzenie</th><th>Aplikacja</th><th>Adres IP</th></tr>
        </thead>
        <tbody>
          {entries.map((e, i) => (
            <tr key={i} className={e.zdarzenie === 'nieudane logowanie' ? 'failed' : ''}>
              <td>{new Date(e.czas).toLocaleString('pl-PL')}</td>
              <td>{e.login || <span className="muted">(pusty)</span>}</td>
              <td>{e.zdarzenie}</td>
              <td>{KLIENT[e.klient] ?? e.klient}</td>
              <td>{e.adres}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
