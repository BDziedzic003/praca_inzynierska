// Ekran sterowania: obraz z kamery, stan robota, przyciski jazdy i kamery, łączność głosowa.
import { CameraView } from './CameraView';
import { HoldButton } from './HoldButton';
import { SPEED_STEP } from './protocol';

const BATTERY_STALE_MS = 3000;

const meter = (level) => {
  const n = Math.max(0, Math.min(20, Math.round(level * 20)));
  return '▮'.repeat(n) + '▯'.repeat(20 - n);
};

function Battery({ conn }) {
  const bat = conn.battery;
  if (!conn.state.robot || !bat || Date.now() - bat.at > BATTERY_STALE_MS) {
    return <div className="pill muted">Bateria: --</div>;
  }
  if (bat.state === 'brak') return <div className="pill muted">Bateria: brak pomiaru (zasilanie z USB?)</div>;
  const text = `${bat.volts.toFixed(1)} V (${bat.pct}%)`;
  if (bat.state === 'krytyczny') return <div className="pill danger">⚠ BATERIA KRYTYCZNA {text} – jazda zablokowana</div>;
  if (bat.state === 'niski') return <div className="pill warn">Bateria: {text} – niski poziom, wracaj</div>;
  return (
    <div className="pill ok">
      Bateria: {text}
      <span className="bar"><span style={{ width: `${bat.pct}%` }} /></span>
    </div>
  );
}

export function ControlPanel({ session, conn, audio, controls, speed, talkDenied, onSpeed, onTalk, onToggleListening }) {
  const st = conn.state;

  let status = { text: 'Łączenie z serwerem…', cls: 'danger' };
  if (conn.connected && st.robot) {
    status = { text: `Połączono z robotem · kamera: ${st.fps ? `${st.fps} fps, ${st.kb} KB/klatkę` : 'brak obrazu'}`, cls: 'ok' };
  } else if (conn.connected) {
    status = { text: 'Serwer połączony – brak połączenia z robotem', cls: 'warn' };
  }

  let audioLine = { text: `🔊 Słuchasz robota ${meter(audio.level)}`, cls: 'ok' };
  if (audio.talking) {
    audioLine = audio.clipping
      ? { text: `🎤 ${meter(audio.levelOut)} PRZESTEROWANIE – zmniejsz głośność robota`, cls: 'danger' }
      : { text: `🎤 Mówisz do robota ${meter(audio.levelOut)}`, cls: 'warn' };
  } else if (st.otherTalking) {
    audioLine = { text: '🗣 Inny operator mówi do robota', cls: 'warn' };
  } else if (talkDenied) {
    audioLine = { text: 'Mówienie niedostępne – telefon ma pierwszeństwo', cls: 'danger' };
  } else if (audio.micError) {
    audioLine = { text: `🎤 ${audio.micError}`, cls: 'danger' };
  } else if (!audio.listening) {
    audioLine = { text: '🔇 Słuchanie wyciszone', cls: 'muted' };
  }

  const drive = (k, label) => (
    <HoldButton label={label} className={`pad-${k}`}
                onPress={() => controls.pressDrive(k)} onRelease={() => controls.releaseDrive(k)} />
  );

  return (
    <div className="control">
      <section className="video-col">
        <CameraView token={session.token} />
      </section>

      <section className="side-col">
        <div className={`pill ${status.cls}`}>{status.text}</div>
        <Battery conn={conn} />
        {conn.connected && !st.canControl && (
          <div className="pill warn">🔒 Sterowanie przejął telefon – możliwe tylko zatrzymanie (Esc / STOP)</div>
        )}

        <div className="card">
          <h3>Jazda <span className="hint">W A S D</span></h3>
          <div className="pad">
            {drive('up', '▲')}
            {drive('left', '◀')}
            {drive('right', '▶')}
            {drive('down', '▼')}
          </div>
          <div className="row">
            <span className="label">Prędkość</span>
            <button onClick={() => onSpeed(-SPEED_STEP)}>−</button>
            <b className="value">{speed}</b>
            <button onClick={() => onSpeed(SPEED_STEP)}>+</button>
          </div>
        </div>

        <div className="card">
          <h3>Kamera <span className="hint">← →</span></h3>
          <div className="row">
            <HoldButton label="⟲" className="cam"
                        onPress={() => controls.pressCam('camLeft')} onRelease={() => controls.releaseCam('camLeft')} />
            <HoldButton label="⟳" className="cam"
                        onPress={() => controls.pressCam('camRight')} onRelease={() => controls.releaseCam('camRight')} />
          </div>
          <button className="stop" onClick={() => controls.stopAll()}>STOP <span className="hint">Esc</span></button>
        </div>

        <div className="card">
          <h3>Dźwięk <span className="hint">T – mów, M – słuchanie</span></h3>
          <div className={`audio-line ${audioLine.cls}`}>{audioLine.text}</div>
          <div className="row">
            <HoldButton label="🎤 Mów (przytrzymaj)" className="talk" onPress={() => onTalk(true)} onRelease={() => onTalk(false)} />
            <button onClick={onToggleListening}>{audio.listening ? '🔊 Wycisz' : '🔇 Słuchaj'}</button>
          </div>
          <label className="slider">
            Głośność u mnie: {Math.round(audio.listenGain * 100)}%
            <input type="range" min="0" max="300" step="10" value={Math.round(audio.listenGain * 100)}
                   onChange={(e) => { audio.listenGain = e.target.value / 100; }}
                   onPointerUp={(e) => e.currentTarget.blur()} />
          </label>
          <label className="slider">
            Głośność robota: {Math.round(audio.talkGain * 100)}%
            <input type="range" min="50" max="800" step="25" value={Math.round(audio.talkGain * 100)}
                   onChange={(e) => { audio.talkGain = e.target.value / 100; }}
                   onPointerUp={(e) => e.currentTarget.blur()} />
          </label>
        </div>
      </section>
    </div>
  );
}
