// Łączność głosowa w przeglądarce (Web Audio API).
//   odtwarzanie: próbki PCM 16 kHz z robota, planowane z buforem wstępnym (jitter buffer)
//   nadawanie:   mikrofon przeglądarki przepróbkowany do 16 kHz, pakiety po 512 próbek
// Dostęp do mikrofonu przeglądarka udostępnia tylko w bezpiecznym kontekście
// (https lub http://localhost).

const RATE = 16000;
const FRAME = 512;              // próbek w pakiecie (32 ms), jak w pakietach robota
const JITTER_START_S = 0.10;    // bufor wstępny odtwarzania
const MAX_BUFFER_S = 0.40;      // górna granica opóźnienia odtwarzania

const rms = (arr) => {
  let s = 0;
  for (let i = 0; i < arr.length; i++) s += arr[i] * arr[i];
  return arr.length ? Math.sqrt(s / arr.length) : 0;
};

export class WebAudioLink {
  constructor(sendBinary) {
    this.sendBinary = sendBinary;
    this.listening = true;
    this.talking = false;
    this.level = 0;            // poziom sygnału z robota 0..1
    this.levelOut = 0;         // poziom sygnału wysyłanego 0..1
    this.clipping = false;
    this.listenGain = 0.5;
    this.talkGain = 2.0;
    this.micError = null;

    this.ctx = null;           // kontekst odtwarzania 16 kHz
    this.nextTime = 0;
    this.lastPacket = 0;
    this.clipUntil = 0;

    this.mic = null;           // { ctx, stream, proc }
    this.micBuf = new Float32Array(FRAME);
    this.micPos = 0;
    this.micPhase = 0;
  }

  // Przeglądarka pozwala uruchomić dźwięk dopiero po interakcji użytkownika
  resume() {
    try {
      if (!this.ctx) this.ctx = new AudioContext({ sampleRate: RATE });
      if (this.ctx.state === 'suspended') this.ctx.resume();
    } catch {
      // Web Audio niedostępne
    }
  }

  close() {
    this.talking = false;
    if (this.mic) {
      this.mic.stream.getTracks().forEach((t) => t.stop());
      this.mic.ctx.close();
      this.mic = null;
    }
    this.ctx?.close();
    this.ctx = null;
  }

  setListening(on) {
    this.listening = on;
  }

  decay() {
    if (Date.now() - this.lastPacket > 500) this.level *= 0.5;
  }

  // ---------- robot -> przeglądarka ----------
  onAudio(buffer) {
    if (!buffer || buffer.byteLength < 2) return;
    const samples = new Int16Array(buffer.byteLength >> 1);
    const view = new DataView(buffer);
    for (let i = 0; i < samples.length; i++) samples[i] = view.getInt16(2 * i, true);
    this.lastPacket = Date.now();
    this.level = Math.min(1, rms(samples) / 8000);

    const ctx = this.ctx;
    if (!ctx || ctx.state !== 'running' || this.talking || !this.listening) return;

    const now = ctx.currentTime;
    if (this.nextTime < now + 0.01) this.nextTime = now + JITTER_START_S;   // ponowne buforowanie
    if (this.nextTime - now > MAX_BUFFER_S) return;                           // zbyt duże opóźnienie

    const buf = ctx.createBuffer(1, samples.length, RATE);
    const ch = buf.getChannelData(0);
    for (let i = 0; i < samples.length; i++) {
      ch[i] = Math.max(-1, Math.min(1, (samples[i] / 32768) * this.listenGain));
    }
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);
    src.start(this.nextTime);
    this.nextTime += buf.duration;
  }

  // ---------- przeglądarka -> robot ----------
  async setTalking(on) {
    if (!on) {
      this.talking = false;
      this.levelOut = 0;
      return true;
    }
    if (!(await this.ensureMic())) return false;
    this.micPos = 0;
    this.talking = true;
    return true;
  }

  async ensureMic() {
    if (this.mic) return true;
    if (!navigator.mediaDevices?.getUserMedia) {
      this.micError = 'mówienie wymaga połączenia https lub http://localhost';
      return false;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      // Osobny kontekst w natywnej częstotliwości mikrofonu; przepróbkowanie do 16 kHz poniżej
      const ctx = new AudioContext();
      const source = ctx.createMediaStreamSource(stream);
      const proc = ctx.createScriptProcessor(2048, 1, 1);
      proc.onaudioprocess = (e) => this.onMicFrame(e.inputBuffer.getChannelData(0), ctx.sampleRate);
      source.connect(proc);
      proc.connect(ctx.destination);   // wymagane do uruchomienia przetwarzania (wyjście jest ciche)
      this.mic = { ctx, stream, proc };
      this.micError = null;
      return true;
    } catch (e) {
      this.micError = `brak dostępu do mikrofonu (${e.message || e})`;
      return false;
    }
  }

  onMicFrame(input, inRate) {
    if (!this.talking) return;
    const step = inRate / RATE;
    // przepróbkowanie z interpolacją liniową
    for (; this.micPhase < input.length - 1; this.micPhase += step) {
      const i = Math.floor(this.micPhase);
      const f = this.micPhase - i;
      this.micBuf[this.micPos++] = input[i] * (1 - f) + input[i + 1] * f;
      if (this.micPos === FRAME) {
        this.sendFrame();
        this.micPos = 0;
      }
    }
    this.micPhase -= input.length;
  }

  sendFrame() {
    const out = new Int16Array(FRAME);
    let peak = 0;
    let sum = 0;
    for (let i = 0; i < FRAME; i++) {
      const v = this.micBuf[i] * 32768 * this.talkGain;
      const a = Math.abs(v);
      if (a > peak) peak = a;
      sum += v * v;
      out[i] = v > 32767 ? 32767 : v < -32768 ? -32768 : Math.round(v);
    }
    if (peak > 32000) this.clipUntil = Date.now() + 1000;   // sygnalizacja przesterowania przez 1 s
    this.clipping = Date.now() < this.clipUntil;
    this.levelOut = Math.min(1, Math.sqrt(sum / FRAME) / 8000);
    this.sendBinary(out.buffer);
  }
}
