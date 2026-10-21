// Background music for the walkthrough, synthesised from sine waves so it is original
// and carries no third-party licence. A soft chord pad changes with each scene, and
// small bells and ticks land on the same events as the picture (walkthrough.js SOUNDS).
//   soundtrack({ duration, scenes, sounds }) -> 16-bit stereo WAV as a Buffer
const SR = 44100;
const NOTE = { D2: 73.42, G2: 98.0, A2: 110.0, B2: 123.47, D3: 146.83, E3: 164.81, Fs3: 185.0, G3: 196.0, A3: 220.0,
  B3: 246.94, Cs4: 277.18, D4: 293.66, E4: 329.63, Fs4: 369.99, A4: 440.0, B4: 493.88, D5: 587.33, E5: 659.25,
  Fs5: 739.99, A5: 880.0, B5: 987.77 };
const CHORD = {
  Dmaj7: ["D3", "A3", "Cs4", "Fs4"], Bm7: ["B2", "Fs3", "A3", "D4"], Gmaj7: ["G2", "D3", "Fs3", "B3"],
  Asus: ["A2", "E3", "A3", "D4"], Em7: ["E3", "G3", "B3", "D4"], Dadd9: ["D3", "A3", "D4", "E4", "Fs4"],
};
// One chord per scene, in order: intro, steps 1-10, the crash scene, the outro.
const PROGRESSION = ["Dmaj7", "Dmaj7", "Bm7", "Gmaj7", "Asus", "Dmaj7", "Bm7", "Gmaj7", "Asus", "Em7", "Dmaj7", "Bm7", "Dadd9"];
const BELLS = ["D5", "E5", "Fs5", "A5", "B5"];

export function soundtrack({ duration, scenes, sounds }) {
  const n = Math.ceil(duration * SR);
  const L = new Float32Array(n), R = new Float32Array(n);

  function tone(freq, start, end, amp, pan, attack, release) {
    const i0 = Math.max(0, Math.floor(start * SR)), i1 = Math.min(n, Math.floor((end + release) * SR));
    const gl = amp * Math.cos((pan + 1) * Math.PI / 4), gr = amp * Math.sin((pan + 1) * Math.PI / 4);
    const w = 2 * Math.PI * freq / SR, wd = w * 1.0015;
    for (let i = i0; i < i1; i++) {
      const t = i / SR;
      let env = Math.min(1, (t - start) / attack);
      env = Math.sin(env * Math.PI / 2) ** 2;
      if (t > end) env *= Math.cos(Math.min(1, (t - end) / release) * Math.PI / 2) ** 2;
      const v = env * (Math.sin(w * i) + 0.6 * Math.sin(wd * i) + 0.18 * Math.sin(2 * w * i)) * (0.9 + 0.1 * Math.sin(2 * Math.PI * 0.18 * t));
      L[i] += v * gl; R[i] += v * gr;
    }
  }
  function struck(freq, at, amp, pan, partials) {
    const i0 = Math.floor(at * SR), i1 = Math.min(n, i0 + Math.floor(3.5 * SR));
    const gl = amp * Math.cos((pan + 1) * Math.PI / 4), gr = amp * Math.sin((pan + 1) * Math.PI / 4);
    for (let i = i0; i < i1; i++) {
      const t = (i - i0) / SR;
      let v = 0;
      for (const [ratio, a, decay] of partials) v += a * Math.exp(-t * decay) * Math.sin(2 * Math.PI * freq * ratio * t);
      v *= Math.min(1, t / 0.004);
      L[i] += v * gl; R[i] += v * gr;
    }
  }
  function thud(at, amp) {
    const i0 = Math.floor(at * SR), i1 = Math.min(n, i0 + Math.floor(0.9 * SR));
    let phase = 0;
    for (let i = i0; i < i1; i++) {
      const t = (i - i0) / SR;
      phase += 2 * Math.PI * (48 + 50 * Math.exp(-t * 9)) / SR;
      const v = amp * Math.exp(-t * 5.5) * Math.sin(phase) * Math.min(1, t / 0.006);
      L[i] += v; R[i] += v;
    }
  }

  // The pad: one chord per scene, overlapping so the changes are smooth.
  const starts = scenes.concat([duration]);
  for (let s = 0; s < scenes.length; s++) {
    const notes = CHORD[PROGRESSION[Math.min(s, PROGRESSION.length - 1)]];
    const end = s === scenes.length - 1 ? duration - 2.5 : starts[s + 1];
    notes.forEach((name, j) => tone(NOTE[name], starts[s] - 0.6, end, 0.05 / Math.sqrt(notes.length / 4), (j / (notes.length - 1)) * 1.2 - 0.6, 1.6, 2.2));
  }
  // Events on the picture's clock.
  let bell = 0;
  for (const [at, kind] of sounds.slice().sort((a, b) => a[0] - b[0])) {
    const pan = Math.sin(at * 1.7) * 0.5;
    if (kind === "chime") struck(NOTE[BELLS[bell++ % BELLS.length]], at, 0.07, pan, [[1, 1, 2.6], [2.01, 0.3, 4.5], [3.0, 0.1, 7]]);
    else if (kind === "tick") struck(NOTE.A5 * 2, at, 0.018, pan, [[1, 1, 30]]);
    else if (kind === "bell") struck(NOTE.A4, at, 0.08, pan, [[1, 1, 1.8], [2.0, 0.4, 3], [2.76, 0.15, 5]]);
    else if (kind === "receipt") { struck(NOTE.D5, at, 0.07, -0.3, [[1, 1, 1.4], [2.0, 0.3, 2.5]]); struck(NOTE.Fs5, at + 0.12, 0.06, 0.3, [[1, 1, 1.4], [2.0, 0.3, 2.5]]); struck(NOTE.A5, at + 0.24, 0.05, 0, [[1, 1, 1.4], [2.0, 0.3, 2.5]]); }
    else if (kind === "thud") thud(at, 0.32);
  }
  // A ping-pong echo for space, then fades and a gentle master level.
  const d = Math.floor(0.375 * SR);
  for (let i = d; i < n; i++) { L[i] += 0.28 * R[i - d]; R[i] += 0.28 * L[i - d]; }
  let peak = 0;
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    const g = Math.min(1, t / 2.5) * Math.min(1, (duration - t) / 3);
    L[i] *= g; R[i] *= g;
    peak = Math.max(peak, Math.abs(L[i]), Math.abs(R[i]));
  }
  const gain = 0.45 / peak;
  const buf = Buffer.alloc(44 + n * 4);
  buf.write("RIFF", 0); buf.writeUInt32LE(36 + n * 4, 4); buf.write("WAVE", 8); buf.write("fmt ", 12);
  buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20); buf.writeUInt16LE(2, 22); buf.writeUInt32LE(SR, 24);
  buf.writeUInt32LE(SR * 4, 28); buf.writeUInt16LE(4, 32); buf.writeUInt16LE(16, 34); buf.write("data", 36); buf.writeUInt32LE(n * 4, 40);
  for (let i = 0; i < n; i++) {
    buf.writeInt16LE(Math.round(Math.max(-1, Math.min(1, L[i] * gain)) * 32767), 44 + i * 4);
    buf.writeInt16LE(Math.round(Math.max(-1, Math.min(1, R[i] * gain)) * 32767), 46 + i * 4);
  }
  return buf;
}
