// Panel administratora: lista użytkowników, dodawanie, usuwanie, uprawnienia i zmiana hasła.
import { useCallback, useEffect, useState } from 'react';
import { addUser, deleteUser, listUsers, setAdmin, setPassword } from './api';

export function UsersPanel({ session }) {
  const [users, setUsers] = useState([]);
  const [error, setError] = useState(null);
  const [info, setInfo] = useState(null);
  const [form, setForm] = useState({ login: '', haslo: '', admin: false });
  const [editing, setEditing] = useState(null);
  const [newPassword, setNewPassword] = useState('');

  // wykonanie operacji API z obsługą błędu i odświeżeniem listy
  const run = useCallback(async (op, msg) => {
    setError(null);
    setInfo(null);
    try {
      await op();
      setUsers(await listUsers(session));
      if (msg) setInfo(msg);
      return true;
    } catch (e) {
      setError(e.message);
      return false;
    }
  }, [session]);

  useEffect(() => {
    run(async () => {});
  }, [run]);

  const add = async (e) => {
    e.preventDefault();
    if (await run(() => addUser(session, form.login.trim(), form.haslo, form.admin), `Dodano użytkownika ${form.login.trim()}.`)) {
      setForm({ login: '', haslo: '', admin: false });
    }
  };

  const remove = (u) => {
    if (window.confirm(`Usunąć użytkownika ${u.login}?`)) run(() => deleteUser(session, u.login), `Usunięto użytkownika ${u.login}.`);
  };

  const savePassword = async (u) => {
    if (await run(() => setPassword(session, u.login, newPassword), `Zmieniono hasło użytkownika ${u.login}.`)) {
      setEditing(null);
      setNewPassword('');
    }
  };

  return (
    <div className="admin">
      <div className="card">
        <h2>Użytkownicy</h2>
        {error && <div className="error">{error}</div>}
        {info && <div className="info">{info}</div>}
        <table>
          <thead>
            <tr><th>Login</th><th>Rola</th><th className="actions">Akcje</th></tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.login}>
                <td>{u.login}{u.login === session.login && <span className="muted"> (ty)</span>}</td>
                <td><span className={`badge ${u.admin ? 'admin' : ''}`}>{u.admin ? 'administrator' : 'użytkownik'}</span></td>
                <td className="actions">
                  {editing === u.login ? (
                    <span className="inline">
                      <input type="password" placeholder="nowe hasło" value={newPassword} autoFocus
                             onChange={(e) => setNewPassword(e.target.value)}
                             onKeyDown={(e) => e.key === 'Enter' && savePassword(u)} />
                      <button onClick={() => savePassword(u)}>Zapisz</button>
                      <button onClick={() => setEditing(null)}>Anuluj</button>
                    </span>
                  ) : (
                    <>
                      <button onClick={() => run(() => setAdmin(session, u.login, !u.admin))}>
                        {u.admin ? 'Odbierz admina' : 'Nadaj admina'}
                      </button>
                      <button onClick={() => { setEditing(u.login); setNewPassword(''); }}>Zmień hasło</button>
                      <button className="danger" onClick={() => remove(u)}>Usuń</button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <form className="card add-user" onSubmit={add}>
        <h2>Nowy użytkownik</h2>
        <label>Login<input value={form.login} onChange={(e) => setForm({ ...form, login: e.target.value })} /></label>
        <label>Hasło<input type="password" value={form.haslo} onChange={(e) => setForm({ ...form, haslo: e.target.value })} /></label>
        <label className="check">
          <input type="checkbox" checked={form.admin} onChange={(e) => setForm({ ...form, admin: e.target.checked })} />
          administrator
        </label>
        <button className="primary">Dodaj</button>
      </form>
    </div>
  );
}
