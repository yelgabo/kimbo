import { createGame } from './game.js';
import { createRenderer } from './render.js';
import { installInput } from './input.js';
import { createAudio } from './audio.js';
import { createLeaderboard } from './leaderboard.js';
import { createReplayLogger } from './replay.js';
import { installReplayViewer } from './replay-viewer.js';
import { LEADERBOARD_LIMIT } from './config.js';

const refs = {
  boardCanvas: document.getElementById('board'),
  nextCanvas: document.getElementById('next'),
  overlay: document.getElementById('overlay'),
  overlayText: document.getElementById('overlay-text'),
  overlaySub: document.getElementById('overlay-sub'),
  scoreEl: document.getElementById('score'),
  bestEl: document.getElementById('best'),
  levelEl: document.getElementById('level'),
  linesEl: document.getElementById('lines'),
  leaderboardList: document.getElementById('leaderboard-list'),
  leaderboardYou: document.getElementById('leaderboard-you'),
  leaderboardData: { entries: [], myName: '' },
};

const audio = createAudio();
const leaderboard = createLeaderboard();
const logger = createReplayLogger();
refs.leaderboardData.myName = leaderboard.displayName();

let gameRef = null;

async function refreshTop() {
  const entries = await leaderboard.fetchTop(LEADERBOARD_LIMIT);
  refs.leaderboardData.entries = entries;
}

const events = {
  ...audio,
  input: (op, t) => logger.logInput(op, t),
  restart: () => {
    audio.restart?.();
    logger.reset();
  },
  topOut: async (payload) => {
    audio.topOut?.();
    const fullPayload = { ...payload, replayLog: logger.serialize() };
    const r = await leaderboard.submit(fullPayload);
    if (r) {
      gameRef.state.lastRank = r.rank;
      gameRef.state.lastTotal = r.total;
      refreshTop();
    } else {
      gameRef.state.submitFailed = true;
    }
  },
};

const game = createGame({ events });
gameRef = game;
const render = createRenderer(refs);
installInput(game);
installReplayViewer({
  list: refs.leaderboardList,
  fetchReplay: leaderboard.fetchReplay,
});

refreshTop();

const muteBtn = document.getElementById('mute');
const musicBtn = document.getElementById('music');

function paintToggles() {
  const m = audio.isMuted();
  muteBtn.textContent = m ? 'SOUND · OFF' : 'SOUND · ON';
  muteBtn.classList.toggle('is-off', m);

  const me = audio.isMusicEnabled();
  musicBtn.textContent = me ? 'MUSIC · ON' : 'MUSIC · OFF';
  musicBtn.classList.toggle('is-off', !me);
}
paintToggles();

muteBtn.addEventListener('click', () => {
  audio.start();
  audio.toggleMuted();
  paintToggles();
});

musicBtn.addEventListener('click', () => {
  audio.start();
  audio.toggleMusic();
  paintToggles();
});

window.addEventListener('keydown', (e) => {
  if (e.repeat) return;
  audio.start();
  if (e.key === 'm' || e.key === 'M') {
    audio.toggleMuted();
    paintToggles();
  } else if (e.key === 'n' || e.key === 'N') {
    audio.toggleMusic();
    paintToggles();
  }
}, { capture: true });

let lastTime = 0;
function loop(now) {
  const dt = lastTime ? now - lastTime : 0;
  lastTime = now;
  game.step(dt);
  render(game.state);
  requestAnimationFrame(loop);
}
requestAnimationFrame(loop);
