import {
  COLS, ROWS,
  BEST_KEY, RESTART_DELAY_MS, LINE_POINTS,
  GRAVITY_BASE_MS, GRAVITY_PER_LEVEL_MS, GRAVITY_MIN_MS, SOFT_DROP_MS,
} from './config.js';
import { PIECES, KICKS, cellsOf, createBag } from './pieces.js';
import { emptyBoard, collides, clearLines } from './board.js';

export function createGame() {
  const nextType = createBag();

  const state = {
    board: emptyBoard(),
    piece: null,
    nextType: nextType(),
    score: 0,
    level: 1,
    lines: 0,
    best: Number(localStorage.getItem(BEST_KEY) || 0),
    paused: false,
    gameOver: false,
    restartAt: 0,
    dropTimer: 0,
    softDrop: false,
  };

  function spawn() {
    const type = state.nextType;
    state.nextType = nextType();
    const piece = { type, rot: 0, x: 3, y: 0 };
    if (collides(piece, state.board)) {
      topOut();
      return;
    }
    state.piece = piece;
  }

  function lock() {
    for (const [dx, dy] of cellsOf(state.piece)) {
      const x = state.piece.x + dx;
      const y = state.piece.y + dy;
      if (y >= 0 && y < ROWS && x >= 0 && x < COLS) {
        state.board[y][x] = PIECES[state.piece.type].color;
      }
    }
    const cleared = clearLines(state.board);
    if (cleared > 0) {
      state.score += LINE_POINTS[cleared] * state.level;
      state.lines += cleared;
      const newLevel = Math.floor(state.lines / 10) + 1;
      if (newLevel > state.level) state.level = newLevel;
    }
    spawn();
  }

  function move(dx) {
    if (!state.piece) return;
    const trial = { ...state.piece, x: state.piece.x + dx };
    if (!collides(trial, state.board)) state.piece = trial;
  }

  function rotate(dir) {
    if (!state.piece) return;
    const newRot = (state.piece.rot + (dir === 'cw' ? 1 : 3)) % 4;
    for (const [kx, ky] of KICKS) {
      const trial = {
        ...state.piece,
        rot: newRot,
        x: state.piece.x + kx,
        y: state.piece.y + ky,
      };
      if (!collides(trial, state.board)) {
        state.piece = trial;
        return;
      }
    }
  }

  function softDropStep() {
    if (!state.piece) return;
    const trial = { ...state.piece, y: state.piece.y + 1 };
    if (collides(trial, state.board)) {
      lock();
    } else {
      state.piece = trial;
      state.score += 1;
    }
  }

  function gravityStep() {
    if (!state.piece) return;
    const trial = { ...state.piece, y: state.piece.y + 1 };
    if (collides(trial, state.board)) lock();
    else state.piece = trial;
  }

  function hardDrop() {
    if (!state.piece) return;
    let dist = 0;
    while (true) {
      const trial = { ...state.piece, y: state.piece.y + 1 };
      if (collides(trial, state.board)) break;
      state.piece = trial;
      dist++;
    }
    state.score += dist * 2;
    lock();
  }

  function setSoftDrop(on) {
    if (on) {
      state.softDrop = true;
      softDropStep();
      state.dropTimer = 0;
    } else {
      state.softDrop = false;
    }
  }

  function togglePause() {
    state.paused = !state.paused;
  }

  function topOut() {
    if (state.score > state.best) {
      state.best = state.score;
      localStorage.setItem(BEST_KEY, String(state.best));
    }
    state.gameOver = true;
    state.softDrop = false;
    state.piece = null;
    state.restartAt = performance.now() + RESTART_DELAY_MS;
  }

  function restart() {
    state.board = emptyBoard();
    state.score = 0;
    state.level = 1;
    state.lines = 0;
    state.dropTimer = 0;
    state.gameOver = false;
    spawn();
  }

  function dropInterval() {
    const base = Math.max(GRAVITY_MIN_MS, GRAVITY_BASE_MS - (state.level - 1) * GRAVITY_PER_LEVEL_MS);
    return state.softDrop ? Math.min(base, SOFT_DROP_MS) : base;
  }

  function step(dt) {
    if (state.paused) return;
    if (state.gameOver) {
      if (performance.now() >= state.restartAt) restart();
      return;
    }
    state.dropTimer += dt;
    const interval = dropInterval();
    while (state.dropTimer >= interval) {
      state.dropTimer -= interval;
      if (state.softDrop) softDropStep();
      else gravityStep();
    }
  }

  function canPlay() {
    return !state.paused && !state.gameOver;
  }

  spawn();

  return {
    state,
    step,
    move,
    rotate,
    hardDrop,
    setSoftDrop,
    togglePause,
    canPlay,
  };
}
