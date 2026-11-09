// Ekran logowania.
import { useState } from 'react';
import { login } from './api';

export function Login({ message, onLogin }) {
  const [user, setUser] = useState(() => {
    try {
      return localStorage.getItem('robot_web_last_login') || '';
    } catch {
      return '';
    }
  });
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(message);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const s = await login(user.trim(), password);
      try {
        localStorage.setItem('robot_web_last_login', user.trim());
      } catch {
        // pamięć przeglądarki niedostępna
      }
      onLogin(s);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return (
    <div className="login-page">
      <form className="card login-card" onSubmit={submit}>
        <h1>Sterowanie robotem</h1>
        <p className="muted">System zdalnego sterowania robotem ratowniczym</p>
        <label>
          Login
          <input value={user} onChange={(e) => setUser(e.target.value)} autoFocus={!user} autoComplete="username" />
        </label>
        <label>
          Hasło
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                 autoFocus={!!user} autoComplete="current-password" />
        </label>
        {error && <div className="error">{error}</div>}
        <button className="primary" disabled={busy}>{busy ? 'Logowanie…' : 'Zaloguj'}</button>
      </form>
    </div>
  );
}
