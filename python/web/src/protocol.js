// Protokół komunikacji z serwerem i logika sterowania (zgodna z aplikacją na telefon i na komputer).

export const MIN_SPEED = 40;
export const MAX_SPEED = 255;
export const SPEED_STEP = 20;
export const DEFAULT_SPEED = 150;

export const CAMERA_ROTATION_DEG = -90;     // obrót obrazu (kamera zamontowana obrócona)
export const CAMERA_SERVO_REVERSED = true;  // serwo zamontowane odwrotnie

export const EMPTY_STATE = { robot: false, lock: false, canControl: true, otherTalking: false, fps: 0, kb: 0 };

// Interpretacja wiadomości tekstowej od serwera
export function parseLine(line, now) {
  const l = line.trim();
  if (!l) return null;
  const p = l.split(':');
  if (p[0] === 'bat' && p.length === 4) {
    const volts = parseFloat(p[1]);
    const pct = parseInt(p[2], 10);
    if (isNaN(volts) || isNaN(pct)) return null;
    return { type: 'bat', battery: { volts, pct, state: p[3], at: now } };
  }
  // stan:<robot>:<blokada>:<sterowanie>:<inny mówi>:<fps>:<kb>
  if (p[0] === 'stan' && p.length === 7) {
    return {
      type: 'stan',
      state: {
        robot: p[1] === '1',
        lock: p[2] === '1',
        canControl: p[3] === '1',
        otherTalking: p[4] === '1',
        fps: parseInt(p[5], 10) || 0,
        kb: parseInt(p[6], 10) || 0,
      },
    };
  }
  return { type: 'log', text: l };
}

const DRIVE = { up: 'forward', down: 'backward', left: 'spinleft', right: 'spinright' };
const DRIVE_ORDER = ['up', 'down', 'left', 'right'];

// Stan przycisków (klawiszy) sterowania i generowanie komend
export class Controls {
  constructor(send) {
    this.send = send;
    this.speed = DEFAULT_SPEED;
    this.drive = new Set();
    this.cam = new Set();
  }

  driveCmd(k) {
    return `${DRIVE[k]}:${this.speed}`;
  }

  camCmd(k) {
    return (k === 'camLeft') !== CAMERA_SERVO_REVERSED ? 'left' : 'right';
  }

  pressDrive(k) {
    if (this.drive.has(k)) return;
    this.drive.add(k);
    this.send(this.driveCmd(k));
  }

  releaseDrive(k) {
    if (!this.drive.delete(k)) return;
    const next = DRIVE_ORDER.find((x) => this.drive.has(x));
    this.send(next ? this.driveCmd(next) : 'drivestop');
  }

  pressCam(k) {
    if (this.cam.has(k)) return;
    this.cam.add(k);
    this.send(this.camCmd(k));
  }

  releaseCam(k) {
    if (!this.cam.delete(k)) return;
    if (this.cam.has('camLeft')) this.send(this.camCmd('camLeft'));
    else if (this.cam.has('camRight')) this.send(this.camCmd('camRight'));
    else this.send('camstop');
  }

  adjustSpeed(delta) {
    this.speed = Math.max(MIN_SPEED, Math.min(MAX_SPEED, this.speed + delta));
    const active = DRIVE_ORDER.find((x) => this.drive.has(x));
    if (active) this.send(this.driveCmd(active));
  }

  isActive() {
    return this.drive.size > 0 || this.cam.size > 0;
  }

  stopAll() {
    this.drive.clear();
    this.cam.clear();
    this.send('stop');
  }

  reset() {
    this.drive.clear();
    this.cam.clear();
  }
}
