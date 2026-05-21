import { createGame } from './game.js';
import { createRenderer } from './render.js';
import { installInput } from './input.js';
import { createAudio } from './audio.js';

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
};

const audio = createAudio();
const game = createGame({ events: audio });
const render = createRenderer(refs);
installInput(game);

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
