// Połączenie WebSocket z serwerem: komendy, heartbeat, stan robota i dźwięk.
import { EMPTY_STATE, parseLine } from './protocol';

const HEARTBEAT_MS = 200;        // musi być krótszy niż WATCHDOG_KLIENTA_S w serwer.py
const RECONNECT_MS = 2000;

export class RobotConnection {
  constructor(token) {
    this.token = token;
    this.connected = false;
    this.state = EMPTY_STATE;
    this.battery = null;
    this.onAudio = () => {};
    this.onConnect = () => {};
    this.onConnectFailed = () => {};
    this.ws = null;
    this.stopped = false;
    this.retry = null;
    this.heartbeat = null;
  }

  start() {
    this.stopped = false;
    this.connect();
    this.heartbeat = setInterval(() => {
      if (this.connected) this.send('ping');
    }, HEARTBEAT_MS);
  }

  stop() {
    this.stopped = true;
    clearInterval(this.heartbeat);
    clearTimeout(this.retry);
    const ws = this.ws;
    this.ws = null;
    this.connected = false;
    ws?.close();
  }

  send(cmd) {
    if (this.connected && this.ws?.readyState === WebSocket.OPEN) this.ws.send(cmd);
  }

  sendBinary(data) {
    if (this.connected && this.ws?.readyState === WebSocket.OPEN) this.ws.send(data);
  }

  connect() {
    if (this.stopped) return;
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(this.token)}`);
    ws.binaryType = 'arraybuffer';
    this.ws = ws;

    ws.onopen = () => {
      if (this.ws !== ws) return;
      this.connected = true;
      ws.send('hello:web');
      this.onConnect();
    };

    ws.onmessage = (e) => {
      if (this.ws !== ws) return;
      if (typeof e.data !== 'string') {
        this.onAudio(e.data);
        return;
      }
      for (const line of e.data.split('\n')) {
        const p = parseLine(line, Date.now());
        if (p?.type === 'bat') this.battery = p.battery;
        else if (p?.type === 'stan') {
          this.state = p.state;
          if (!p.state.robot) this.battery = null;
        }
      }
    };

    ws.onclose = () => {
      if (this.ws !== ws) return;
      const was = this.connected;
      this.ws = null;
      this.connected = false;
      this.state = EMPTY_STATE;
      this.battery = null;
      if (!was) this.onConnectFailed();
      if (!this.stopped) this.retry = setTimeout(() => this.connect(), RECONNECT_MS);
    };
  }
}
