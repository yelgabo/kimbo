import { COLS, ROWS, CELL, BOARD_BG, GRID_COLOR, GHOST_ALPHA } from './config.js';
import { PIECES, cellsOf } from './pieces.js';
import { collides } from './board.js';
import { createReplay } from './replay.js';

function drawBoard(ctx, state, canvas) {
  ctx.fillStyle = BOARD_BG;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = GRID_COLOR;
  ctx.lineWidth = 1;
  for (let x = 1; x < COLS; x++) {
    ctx.beginPath();
    ctx.moveTo(x * CELL + 0.5, 0);
    ctx.lineTo(x * CELL + 0.5, ROWS * CELL);
    ctx.stroke();
  }
  for (let y = 1; y < ROWS; y++) {
    ctx.beginPath();
    ctx.moveTo(0, y * CELL + 0.5);
    ctx.lineTo(COLS * CELL, y * CELL + 0.5);
    ctx.stroke();
  }

  for (let y = 0; y < ROWS; y++) {
    for (let x = 0; x < COLS; x++) {
      if (state.board[y][x]) {
        ctx.fillStyle = state.board[y][x];
        ctx.fillRect(x * CELL + 1, y * CELL + 1, CELL - 2, CELL - 2);
      }
    }
  }

  if (state.piece) {
    const color = PIECES[state.piece.type].color;
    const ghost = { ...state.piece };
    while (true) {
      const trial = { ...ghost, y: ghost.y + 1 };
      if (collides(trial, state.board)) break;
      ghost.y++;
    }
    if (ghost.y !== state.piece.y) {
      ctx.globalAlpha = GHOST_ALPHA;
      ctx.fillStyle = color;
      for (const [dx, dy] of cellsOf(ghost)) {
        const x = ghost.x + dx;
        const y = ghost.y + dy;
        if (y >= 0) ctx.fillRect(x * CELL + 1, y * CELL + 1, CELL - 2, CELL - 2);
      }
      ctx.globalAlpha = 1;
    }
    ctx.fillStyle = color;
    for (const [dx, dy] of cellsOf(state.piece)) {
      const x = state.piece.x + dx;
      const y = state.piece.y + dy;
      if (y >= 0) ctx.fillRect(x * CELL + 1, y * CELL + 1, CELL - 2, CELL - 2);
    }
  }
}

export function installReplayViewer({ list, fetchReplay }) {
  const modal = document.getElementById('replay-modal');
  const canvas = document.getElementById('replay-canvas');
  const titleEl = document.getElementById('replay-title');
  const scoreEl = document.getElementById('replay-score');
  const closeBtn = document.getElementById('replay-close');
  if (!modal || !canvas || !list) return;

  const ctx = canvas.getContext('2d');
  let active = null;

  function close() {
    if (active) {
      active.stop();
      active = null;
    }
    modal.classList.add('hidden');
    titleEl.textContent = '';
    scoreEl.textContent = '';
    ctx.fillStyle = BOARD_BG;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  }

  async function open(id) {
    modal.classList.remove('hidden');
    titleEl.textContent = 'loading…';
    scoreEl.textContent = '';
    const data = await fetchReplay(id);
    if (!data) {
      titleEl.textContent = 'replay unavailable';
      return;
    }
    titleEl.textContent = `${data.displayName} · final score ${data.score.toLocaleString()}`;
    active = createReplay({
      seed: data.seed,
      log: data.log,
      speed: 4,
      onFrame: (state) => {
        drawBoard(ctx, state, canvas);
        scoreEl.textContent = `live: ${state.score.toLocaleString()} · ${state.lines} lines · L${state.level}`;
      },
      onDone: (state) => {
        scoreEl.textContent = `done · ${state.score.toLocaleString()} · ${state.lines} lines · L${state.level}`;
      },
    });
  }

  list.addEventListener('click', (e) => {
    const btn = e.target.closest('.lb-replay');
    if (!btn) return;
    const id = Number(btn.dataset.id);
    if (Number.isFinite(id) && id > 0) open(id);
  });

  closeBtn?.addEventListener('click', close);
  modal.addEventListener('click', (e) => {
    if (e.target === modal) close();
  });
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !modal.classList.contains('hidden')) close();
  });
}
