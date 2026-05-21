const MUTE_KEY = 'kimbo-tetris-muted';
const MUSIC_KEY = 'kimbo-tetris-music';

const MELODY = [
  ['E5', 4], ['B4', 2], ['C5', 2], ['D5', 4], ['C5', 2], ['B4', 2],
  ['A4', 4], ['A4', 2], ['C5', 2], ['E5', 4], ['D5', 2], ['C5', 2],
  ['B4', 6], ['C5', 2], ['D5', 4], ['E5', 4],
  ['C5', 4], ['A4', 4], ['A4', 4], [null, 4],
  ['D5', 6], ['F5', 2], ['A5', 4], ['G5', 2], ['F5', 2],
  ['E5', 6], ['C5', 2], ['E5', 4], ['D5', 2], ['C5', 2],
  ['B4', 4], ['B4', 2], ['C5', 2], ['D5', 4], ['E5', 4],
  ['C5', 4], ['A4', 4], ['A4', 4], [null, 4],
];

const BASS = [
  ['A2', 4], ['E3', 4], ['A2', 4], ['E3', 4],
  ['E2', 4], ['B2', 4], ['E2', 4], ['B2', 4],
  ['A2', 4], ['E3', 4], ['A2', 4], ['E3', 4],
  ['E2', 4], ['B2', 4], ['E2', 4], ['B2', 4],
  ['A2', 4], ['E3', 4], ['A2', 4], ['E3', 4],
  ['G2', 4], ['D3', 4], ['G2', 4], ['D3', 4],
  ['C3', 4], ['G3', 4], ['C3', 4], ['G3', 4],
  ['E2', 4], ['B2', 4], ['E2', 4], ['B2', 4],
];

const BPM = 144;
const SIXTEENTH = 60 / BPM / 4;

function noteFreq(name) {
  if (!name) return 0;
  const semis = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
  const letter = name[0];
  let i = 1;
  let semi = semis[letter];
  if (name[i] === '#') { semi++; i++; }
  else if (name[i] === 'b') { semi--; i++; }
  const oct = parseInt(name.slice(i), 10);
  const midi = 12 * (oct + 1) + semi;
  return 440 * Math.pow(2, (midi - 69) / 12);
}

export function createAudio() {
  let ctx = null;
  let master = null;
  let musicGain = null;
  let muted = localStorage.getItem(MUTE_KEY) === '1';
  let musicEnabled = localStorage.getItem(MUSIC_KEY) !== '0';

  let musicPlaying = false;
  let mIdx = 0, bIdx = 0;
  let mNext = 0, bNext = 0;
  let musicTimer = null;

  function ensureCtx() {
    if (!ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      ctx = new AC();
      master = ctx.createGain();
      master.gain.value = 0.4;
      master.connect(ctx.destination);
      musicGain = ctx.createGain();
      musicGain.gain.value = 0.16;
      musicGain.connect(master);
    }
    if (ctx.state === 'suspended') ctx.resume();
    return ctx;
  }

  function tone({ freq, dur = 0.08, type = 'square', gain = 0.25, when = 0, slideTo }) {
    if (muted) return;
    const c = ensureCtx();
    if (!c) return;
    const t0 = c.currentTime + when;
    const osc = c.createOscillator();
    const g = c.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, t0);
    if (slideTo != null) {
      osc.frequency.exponentialRampToValueAtTime(slideTo, t0 + dur);
    }
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(gain, t0 + 0.005);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    osc.connect(g).connect(master);
    osc.start(t0);
    osc.stop(t0 + dur + 0.02);
  }

  function noise({ dur = 0.08, gain = 0.2, when = 0, freq = 800 }) {
    if (muted) return;
    const c = ensureCtx();
    if (!c) return;
    const t0 = c.currentTime + when;
    const size = Math.max(1, Math.floor(c.sampleRate * dur));
    const buf = c.createBuffer(1, size, c.sampleRate);
    const data = buf.getChannelData(0);
    for (let i = 0; i < size; i++) data[i] = Math.random() * 2 - 1;
    const src = c.createBufferSource();
    src.buffer = buf;
    const filter = c.createBiquadFilter();
    filter.type = 'lowpass';
    filter.frequency.value = freq;
    const g = c.createGain();
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(gain, t0 + 0.005);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    src.connect(filter).connect(g).connect(master);
    src.start(t0);
    src.stop(t0 + dur + 0.02);
  }

  function playMusicNote(freq, dur, when, type) {
    if (muted || !freq) return;
    const t0 = ctx.currentTime + when;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = type;
    osc.frequency.value = freq;
    const release = Math.min(0.05, dur * 0.25);
    const sustainEnd = t0 + Math.max(0, dur - release);
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(0.9, t0 + 0.008);
    g.gain.setValueAtTime(0.9, sustainEnd);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    osc.connect(g).connect(musicGain);
    osc.start(t0);
    osc.stop(t0 + dur + 0.02);
  }

  function scheduleMusic() {
    if (!musicPlaying || !ctx) return;
    const horizon = ctx.currentTime + 0.18;
    while (mNext < horizon) {
      const [note, sixteenths] = MELODY[mIdx];
      const dur = sixteenths * SIXTEENTH;
      playMusicNote(noteFreq(note), dur, mNext - ctx.currentTime, 'square');
      mNext += dur;
      mIdx = (mIdx + 1) % MELODY.length;
    }
    while (bNext < horizon) {
      const [note, sixteenths] = BASS[bIdx];
      const dur = sixteenths * SIXTEENTH;
      playMusicNote(noteFreq(note), dur, bNext - ctx.currentTime, 'triangle');
      bNext += dur;
      bIdx = (bIdx + 1) % BASS.length;
    }
  }

  function startMusic() {
    if (musicPlaying || !musicEnabled) return;
    const c = ensureCtx();
    if (!c) return;
    musicPlaying = true;
    mIdx = 0; bIdx = 0;
    mNext = c.currentTime + 0.1;
    bNext = c.currentTime + 0.1;
    musicTimer = setInterval(scheduleMusic, 40);
  }

  function stopMusic() {
    musicPlaying = false;
    if (musicTimer) {
      clearInterval(musicTimer);
      musicTimer = null;
    }
  }

  function toggleMusic() {
    musicEnabled = !musicEnabled;
    localStorage.setItem(MUSIC_KEY, musicEnabled ? '1' : '0');
    if (musicEnabled) startMusic();
    else stopMusic();
    return musicEnabled;
  }

  function isMusicEnabled() { return musicEnabled; }

  function move() {
    tone({ freq: 180, dur: 0.03, type: 'square', gain: 0.12 });
  }

  function rotate() {
    tone({ freq: 320, dur: 0.05, type: 'triangle', gain: 0.2, slideTo: 380 });
  }

  function lock() {
    tone({ freq: 110, dur: 0.06, type: 'square', gain: 0.22 });
    noise({ dur: 0.05, gain: 0.1, freq: 700 });
  }

  function hardDrop() {
    tone({ freq: 80, dur: 0.14, type: 'square', gain: 0.3, slideTo: 40 });
    noise({ dur: 0.12, gain: 0.22, freq: 500 });
  }

  function lineClear(count) {
    const scales = {
      1: [523],
      2: [523, 659],
      3: [523, 659, 784],
      4: [523, 659, 784, 1046],
    };
    const notes = scales[count] || [523];
    notes.forEach((freq, i) => {
      tone({ freq, dur: 0.18, type: 'triangle', gain: 0.28, when: i * 0.06 });
    });
    if (count === 4) {
      tone({ freq: 1318, dur: 0.35, type: 'square', gain: 0.22, when: 0.26 });
      tone({ freq: 1568, dur: 0.4, type: 'triangle', gain: 0.18, when: 0.32 });
    }
  }

  function levelUp() {
    [523, 659, 784, 1046].forEach((freq, i) => {
      tone({ freq, dur: 0.1, type: 'triangle', gain: 0.22, when: i * 0.05 });
    });
  }

  function topOut() {
    [392, 311, 247, 196, 147].forEach((freq, i) => {
      tone({ freq, dur: 0.2, type: 'sawtooth', gain: 0.22, when: i * 0.1 });
    });
  }

  function pause() {
    tone({ freq: 440, dur: 0.06, type: 'triangle', gain: 0.18 });
  }

  function restart() {
    tone({ freq: 523, dur: 0.1, type: 'triangle', gain: 0.2 });
    tone({ freq: 784, dur: 0.14, type: 'triangle', gain: 0.2, when: 0.08 });
  }

  function setMuted(m) {
    muted = !!m;
    localStorage.setItem(MUTE_KEY, muted ? '1' : '0');
    return muted;
  }

  function toggleMuted() {
    return setMuted(!muted);
  }

  function isMuted() { return muted; }

  function start() {
    const c = ensureCtx();
    if (c && musicEnabled && !musicPlaying) startMusic();
    return c;
  }

  return {
    start,
    move, rotate, lock, hardDrop, lineClear, levelUp, topOut, pause, restart,
    setMuted, toggleMuted, isMuted,
    toggleMusic, isMusicEnabled,
  };
}
