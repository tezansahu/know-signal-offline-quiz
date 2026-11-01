// Synthesised sound for the projector screen. No audio files, works offline.
const Sound = (() => {
  let ctx = null, master = null, musicTimer = null, nextNote = 0, step = 0;
  let muted = localStorage.getItem("quiz-muted") === "1";

  function ensure() {
    if (!ctx) {
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      master = ctx.createGain();
      master.gain.value = muted ? 0 : 0.6;
      master.connect(ctx.destination);
    }
    if (ctx.state === "suspended") ctx.resume();
    return ctx;
  }

  function tone(freq, t, dur, { type = "sine", vol = 0.2, attack = 0.005, slide = 0 } = {}) {
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = type;
    o.frequency.setValueAtTime(freq, t);
    if (slide) o.frequency.exponentialRampToValueAtTime(freq * slide, t + dur);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(vol, t + attack);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(master);
    o.start(t);
    o.stop(t + dur + 0.05);
  }

  function noise(t, dur, vol = 0.15, from = 400, to = 4000) {
    const len = Math.floor(ctx.sampleRate * dur);
    const buf = ctx.createBuffer(1, len, ctx.sampleRate);
    const d = buf.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
    const src = ctx.createBufferSource(), f = ctx.createBiquadFilter(), g = ctx.createGain();
    src.buffer = buf;
    f.type = "bandpass"; f.Q.value = 1.2;
    f.frequency.setValueAtTime(from, t);
    f.frequency.exponentialRampToValueAtTime(to, t + dur);
    g.gain.setValueAtTime(vol, t);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    src.connect(f).connect(g).connect(master);
    src.start(t);
  }

  const midi = (n) => 440 * Math.pow(2, (n - 69) / 12);

  // Light, driving loop in A minor: bass on beats, plucky arpeggio on 8ths.
  const BASS = [45, 45, 41, 41, 43, 43, 40, 40];
  const ARP = [[69, 72, 76, 72], [69, 72, 77, 72], [67, 71, 74, 71], [64, 68, 71, 68]];
  const BEAT = 60 / 128 / 2;

  function schedule() {
    while (nextNote < ctx.currentTime + 0.15) {
      const bar = Math.floor(step / 8) % 8;
      const chord = ARP[Math.floor(bar / 2)];
      const note = chord[step % 4];
      tone(midi(note), nextNote, BEAT * 0.9, { type: "triangle", vol: 0.07 });
      if (step % 2 === 0) tone(midi(BASS[bar]), nextNote, BEAT * 1.8, { type: "sawtooth", vol: 0.05 });
      if (step % 4 === 2) noise(nextNote, 0.05, 0.05, 6000, 9000);
      nextNote += BEAT;
      step++;
    }
  }

  return {
    unlock: ensure,
    get muted() { return muted; },
    toggleMute() {
      muted = !muted;
      localStorage.setItem("quiz-muted", muted ? "1" : "0");
      if (ctx) master.gain.setTargetAtTime(muted ? 0 : 0.6, ctx.currentTime, 0.05);
      return muted;
    },
    startMusic() {
      ensure();
      this.stopMusic();
      nextNote = ctx.currentTime + 0.05;
      step = 0;
      musicTimer = setInterval(schedule, 40);
    },
    stopMusic() { if (musicTimer) clearInterval(musicTimer); musicTimer = null; },
    tick(final = false) {
      ensure();
      tone(final ? 1320 : 990, ctx.currentTime, 0.08, { type: "square", vol: 0.06 });
    },
    pop() {
      ensure();
      tone(660 + Math.random() * 300, ctx.currentTime, 0.12, { type: "sine", vol: 0.12, slide: 1.6 });
    },
    timeUp() {
      ensure();
      const t = ctx.currentTime;
      tone(330, t, 0.5, { type: "square", vol: 0.08 });
      tone(247, t + 0.18, 0.7, { type: "square", vol: 0.08 });
    },
    reveal() {
      ensure();
      const t = ctx.currentTime;
      [72, 76, 79, 84].forEach((n, i) => tone(midi(n), t + i * 0.07, 0.6, { type: "triangle", vol: 0.12 }));
    },
    whoosh() { ensure(); noise(ctx.currentTime, 0.45, 0.18, 300, 5000); },
    drumroll(dur = 2) {
      ensure();
      const t = ctx.currentTime;
      for (let x = 0; x < dur; x += 0.05) noise(t + x, 0.05, 0.03 + 0.07 * (x / dur), 900, 1200);
    },
    fanfare() {
      ensure();
      const t = ctx.currentTime;
      const seq = [[67, 0, 0.15], [72, 0.15, 0.15], [76, 0.3, 0.15], [79, 0.45, 0.5], [76, 0.95, 0.15], [79, 1.1, 0.9]];
      seq.forEach(([n, s, d]) => {
        tone(midi(n), t + s, d, { type: "sawtooth", vol: 0.07 });
        tone(midi(n - 12), t + s, d, { type: "triangle", vol: 0.08 });
      });
      noise(t + 1.1, 1.2, 0.08, 3000, 8000);
    },
  };
})();
