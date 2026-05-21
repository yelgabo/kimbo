import { createGame } from './game.js';
import { createRenderer } from './render.js';
import { installInput } from './input.js';

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

const game = createGame();
const render = createRenderer(refs);
installInput(game);

let lastTime = 0;
function loop(now) {
  const dt = lastTime ? now - lastTime : 0;
  lastTime = now;
  game.step(dt);
  render(game.state);
  requestAnimationFrame(loop);
}
requestAnimationFrame(loop);
