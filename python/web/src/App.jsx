// Aplikacja webowa operatora robota: logowanie, sterowanie z podglądem kamery,
// łączność głosowa oraz panel administratora (użytkownicy, historia logowań).
import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, loadSession, logout, me, saveSession } from './api';
import { RobotConnection } from './connection';
import { WebAudioLink } from './audio';
import { Controls, DEFAULT_SPEED, SPEED_STEP } from './protocol';
import { Login } from './Login';
import { ControlPanel } from './ControlPanel';
import { UsersPanel } from './UsersPanel';
import { LoginHistory } from './LoginHistory';

export default function App() {
  const [session, setSession] = useState(loadSession);
  const [message, setMessage] = useState(null);

  const onLogin = (s) => {
    saveSession(s);
    setSession(s);
    setMessage(null);
  };

  const onLogout = useCallback((msg) => {
    saveSession(null);
    setSession(null);
    setMessage(msg ?? null);
  }, []);

  if (!session) return <Login message={message} onLogin={onLogin} />;
  return <Dashboard key={session.token} session={session} onLogout={onLogout} />;
}

const KEY_DRIVE = { KeyW: 'up', KeyS: 'down', KeyA: 'left', KeyD: 'right' };
const KEY_CAM = { ArrowLeft: 'camLeft', ArrowRight: 'camRight' };

function Dashboard({ session, onLogout }) {
  const [tab, setTab] = useState('control');
  const [, setTick] = useState(0);
  const [speed, setSpeed] = useState(DEFAULT_SPEED);
  const [talkDeniedUntil, setTalkDeniedUntil] = useState(0);

  const conn = useRef(null);
  const audio = useRef(null);
  const controls = useRef(null);
  const talkWanted = useRef(false);

  // Połączenie z serwerem na czas trwania sesji
  useEffect(() => {
    const c = new RobotConnection(session.token);
    const a = new WebAudioLink((data) => c.sendBinary(data));
    const ctl = new Controls((cmd) => c.send(cmd));
    c.onAudio = (data) => a.onAudio(data);
    c.onConnect = () => {
      ctl.reset();
      c.send(`sluchaj:${a.listening ? 1 : 0}`);
      c.send(`mow:${a.talking ? 1 : 0}`);
    };
    // Nieudane połączenie: sprawdzenie, czy sesja jest nadal ważna
    c.onConnectFailed = () => {
      me(session).catch((e) => {
        if (e instanceof ApiError && e.status === 401) {
          onLogout('Sesja wygasła lub konto zostało usunięte – zaloguj się ponownie.');
        }
      });
    };
    conn.current = c;
    audio.current = a;
    controls.current = ctl;
    c.start();
    return () => {
      if (ctl.isActive()) ctl.stopAll();
      c.send('sluchaj:0');
      c.stop();
      a.close();
    };
  }, [session, onLogout]);

  // ---------- mówienie ----------
  const setTalking = useCallback(async (on) => {
    const c = conn.current;
    const a = audio.current;
    if (!c || !a) return;
    talkWanted.current = on;
    if (!on) {
      if (a.talking) {
        a.setTalking(false);
        c.send('mow:0');
      }
      return;
    }
    if (a.talking || !c.connected) return;
    if (c.state.otherTalking || !c.state.canControl) {
      setTalkDeniedUntil(Date.now() + 2000);
      return;
    }
    a.resume();
    const ok = await a.ensureMic();
    if (!ok || !talkWanted.current) return;     // klawisz puszczony przed uzyskaniem dostępu do mikrofonu
    await a.setTalking(true);
    c.send('mow:1');
  }, []);

  // Odświeżanie wskaźników co 200 ms; serwer może przerwać mówienie (pierwszeństwo telefonu)
  useEffect(() => {
    const t = setInterval(() => {
      const c = conn.current;
      const a = audio.current;
      if (a) {
        a.decay();
        if (a.talking && (!c.connected || c.state.otherTalking || !c.state.canControl)) {
          a.setTalking(false);
          talkWanted.current = false;
          setTalkDeniedUntil(Date.now() + 2000);
        }
      }
      setTick((x) => x + 1);
    }, 200);
    return () => clearInterval(t);
  }, []);

  const stopEverything = useCallback(() => {
    setTalking(false);
    if (controls.current?.isActive()) controls.current.stopAll();
  }, [setTalking]);

  // Zmiana zakładki lub utrata fokusu okna: zatrzymanie robota i nadawania
  useEffect(() => {
    if (tab !== 'control') stopEverything();
  }, [tab, stopEverything]);

  useEffect(() => {
    const onHide = () => stopEverything();
    const onVis = () => document.hidden && stopEverything();
    window.addEventListener('blur', onHide);
    document.addEventListener('visibilitychange', onVis);
    return () => {
      window.removeEventListener('blur', onHide);
      document.removeEventListener('visibilitychange', onVis);
    };
  }, [stopEverything]);

  const changeSpeed = useCallback((delta) => {
    controls.current?.adjustSpeed(delta);
    setSpeed(controls.current?.speed ?? DEFAULT_SPEED);
  }, []);

  const toggleListening = useCallback(() => {
    const a = audio.current;
    if (!a) return;
    a.resume();
    a.setListening(!a.listening);
    conn.current?.send(`sluchaj:${a.listening ? 1 : 0}`);
  }, []);

  // ---------- klawiatura (jak w aplikacji na komputer) ----------
  useEffect(() => {
    if (tab !== 'control') return undefined;
    const typing = (e) => ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName);

    const down = (e) => {
      if (typing(e)) return;
      audio.current?.resume();
      const ctl = controls.current;
      if (KEY_DRIVE[e.code] || KEY_CAM[e.code]) e.preventDefault();
      if (e.repeat) return;
      if (KEY_DRIVE[e.code]) ctl.pressDrive(KEY_DRIVE[e.code]);
      else if (KEY_CAM[e.code]) ctl.pressCam(KEY_CAM[e.code]);
      else if (e.code === 'KeyT') setTalking(true);
      else if (e.code === 'KeyM') toggleListening();
      else if (['Equal', 'NumpadAdd'].includes(e.code)) changeSpeed(SPEED_STEP);
      else if (['Minus', 'NumpadSubtract'].includes(e.code)) changeSpeed(-SPEED_STEP);
      else if (e.code === 'Escape') ctl.stopAll();
    };
    const up = (e) => {
      const ctl = controls.current;
      if (KEY_DRIVE[e.code]) ctl.releaseDrive(KEY_DRIVE[e.code]);
      else if (KEY_CAM[e.code]) ctl.releaseCam(KEY_CAM[e.code]);
      else if (e.code === 'KeyT') setTalking(false);
    };
    window.addEventListener('keydown', down);
    window.addEventListener('keyup', up);
    return () => {
      window.removeEventListener('keydown', down);
      window.removeEventListener('keyup', up);
    };
  }, [tab, setTalking, toggleListening, changeSpeed]);

  const doLogout = () => {
    stopEverything();
    logout(session).catch(() => {});
    onLogout();
  };

  return (
    <div className="app" onPointerDown={() => audio.current?.resume()}>
      <header className="topbar">
        <div className="brand">Robot ratowniczy</div>
        <nav className="tabs">
          <button className={tab === 'control' ? 'active' : ''} onClick={() => setTab('control')}>Sterowanie</button>
          {session.admin && (
            <>
              <button className={tab === 'users' ? 'active' : ''} onClick={() => setTab('users')}>Użytkownicy</button>
              <button className={tab === 'logins' ? 'active' : ''} onClick={() => setTab('logins')}>Historia logowań</button>
            </>
          )}
        </nav>
        <div className="user">
          <span>{session.login}{session.admin ? ' · administrator' : ''}</span>
          <button onClick={doLogout}>Wyloguj</button>
        </div>
      </header>

      <main>
        {tab === 'control' && conn.current && (
          <ControlPanel
            session={session}
            conn={conn.current}
            audio={audio.current}
            controls={controls.current}
            speed={speed}
            talkDenied={Date.now() < talkDeniedUntil}
            onSpeed={changeSpeed}
            onTalk={setTalking}
            onToggleListening={toggleListening}
          />
        )}
        {tab === 'users' && <UsersPanel session={session} />}
        {tab === 'logins' && <LoginHistory session={session} />}
      </main>
    </div>
  );
}
