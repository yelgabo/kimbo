import { KEY_REPEAT_DELAY_MS, KEY_REPEAT_RATE_MS } from './config.js';

export function installInput(game) {
  const timers = {};

  function startRepeat(k, fn) {
    stopRepeat(k);
    timers[k] = setTimeout(() => {
      fn();
      timers[k] = setInterval(fn, KEY_REPEAT_RATE_MS);
    }, KEY_REPEAT_DELAY_MS);
  }

  function stopRepeat(k) {
    if (timers[k] != null) {
      clearTimeout(timers[k]);
      clearInterval(timers[k]);
      timers[k] = null;
    }
  }

  function onKeyDown(e) {
    const k = e.key;
    if (k === 'p' || k === 'P') {
      if (!e.repeat) game.togglePause();
      return;
    }
    if (!game.canPlay() || e.repeat) return;
    switch (k) {
      case 'ArrowLeft':
        stopRepeat('ArrowRight');
        game.move(-1);
        startRepeat('ArrowLeft', () => game.move(-1));
        break;
      case 'ArrowRight':
        stopRepeat('ArrowLeft');
        game.move(1);
        startRepeat('ArrowRight', () => game.move(1));
        break;
      case 'ArrowDown':
        game.setSoftDrop(true);
        break;
      case 'ArrowUp':
      case 'x':
      case 'X':
        game.rotate('cw');
        break;
      case 'z':
      case 'Z':
        game.rotate('ccw');
        break;
      case ' ':
        e.preventDefault();
        game.hardDrop();
        break;
    }
  }

  function onKeyUp(e) {
    const k = e.key;
    if (k === 'ArrowLeft' || k === 'ArrowRight') stopRepeat(k);
    if (k === 'ArrowDown') game.setSoftDrop(false);
  }

  function onBlur() {
    game.setSoftDrop(false);
    stopRepeat('ArrowLeft');
    stopRepeat('ArrowRight');
  }

  window.addEventListener('keydown', onKeyDown);
  window.addEventListener('keyup', onKeyUp);
  window.addEventListener('blur', onBlur);
}
