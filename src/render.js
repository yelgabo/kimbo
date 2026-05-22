import {
  COLS, ROWS, CELL, NEXT_CELL,
  BOARD_BG, GRID_COLOR, NEXT_BG, GHOST_ALPHA,
} from './config.js';
import { PIECES, cellsOf } from './pieces.js';
import { collides } from './board.js';

export function createRenderer(refs) {
  const {
    boardCanvas, nextCanvas,
    overlay, overlayText, overlaySub,
    scoreEl, bestEl, levelEl, linesEl,
    leaderboardList, leaderboardYou, leaderboardData,
  } = refs;
  const ctx = boardCanvas.getContext('2d');
  const nctx = nextCanvas.getContext('2d');

  let overlayKey = null;
  let leaderboardKey = null;
  let youKey = null;

  function drawCell(c, x, y, color, alpha) {
    c.globalAlpha = alpha == null ? 1 : alpha;
    c.fillStyle = color;
    c.fillRect(x + 1, y + 1, CELL - 2, CELL - 2);
    c.globalAlpha = 1;
  }

  function drawGrid() {
    ctx.fillStyle = BOARD_BG;
    ctx.fillRect(0, 0, boardCanvas.width, boardCanvas.height);
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
  }

  function drawLocked(board) {
    for (let y = 0; y < ROWS; y++) {
      for (let x = 0; x < COLS; x++) {
        if (board[y][x]) drawCell(ctx, x * CELL, y * CELL, board[y][x]);
      }
    }
  }

  function drawPiece(state) {
    if (!state.piece) return;
    const color = PIECES[state.piece.type].color;

    const ghost = { ...state.piece };
    while (true) {
      const trial = { ...ghost, y: ghost.y + 1 };
      if (collides(trial, state.board)) break;
      ghost.y++;
    }
    if (ghost.y !== state.piece.y) {
      for (const [dx, dy] of cellsOf(ghost)) {
        const x = ghost.x + dx;
        const y = ghost.y + dy;
        if (y >= 0) drawCell(ctx, x * CELL, y * CELL, color, GHOST_ALPHA);
      }
    }
    for (const [dx, dy] of cellsOf(state.piece)) {
      const x = state.piece.x + dx;
      const y = state.piece.y + dy;
      if (y >= 0) drawCell(ctx, x * CELL, y * CELL, color);
    }
  }

  function drawNext(state) {
    nctx.fillStyle = NEXT_BG;
    nctx.fillRect(0, 0, nextCanvas.width, nextCanvas.height);
    const cells = PIECES[state.nextType].rotations[0];
    const color = PIECES[state.nextType].color;
    let minX = 4, maxX = 0, minY = 4, maxY = 0;
    for (const [dx, dy] of cells) {
      if (dx < minX) minX = dx;
      if (dx > maxX) maxX = dx;
      if (dy < minY) minY = dy;
      if (dy > maxY) maxY = dy;
    }
    const w = (maxX - minX + 1) * NEXT_CELL;
    const h = (maxY - minY + 1) * NEXT_CELL;
    const offX = (nextCanvas.width - w) / 2 - minX * NEXT_CELL;
    const offY = (nextCanvas.height - h) / 2 - minY * NEXT_CELL;
    for (const [dx, dy] of cells) {
      nctx.fillStyle = color;
      nctx.fillRect(offX + dx * NEXT_CELL + 1, offY + dy * NEXT_CELL + 1, NEXT_CELL - 2, NEXT_CELL - 2);
    }
  }

  function drawHud(state) {
    scoreEl.textContent = state.score;
    bestEl.textContent = state.best;
    levelEl.textContent = state.level;
    linesEl.textContent = state.lines;
  }

  function formatRank(rank, total) {
    if (rank == null) return null;
    if (total == null) return `rank #${rank}`;
    if (rank <= 10 || total <= 20) return `rank #${rank} of ${total}`;
    const pct = Math.max(1, Math.round((rank / total) * 100));
    return `rank #${rank} · top ${pct}%`;
  }

  function setOverlay(key, title, sub) {
    if (key === overlayKey) return;
    overlayKey = key;
    if (key == null) {
      overlay.classList.add('hidden');
      return;
    }
    overlayText.textContent = title;
    overlaySub.textContent = sub || '';
    overlay.classList.remove('hidden');
  }

  function drawOverlay(state) {
    if (state.paused) {
      setOverlay('paused', 'Paused', 'press P to resume');
      return;
    }
    if (state.gameOver) {
      let sub;
      let subKey;
      if (state.submitFailed) {
        sub = `score ${state.score} · offline — not submitted`;
        subKey = 'fail';
      } else if (state.lastRank != null) {
        sub = `score ${state.score} · ${formatRank(state.lastRank, state.lastTotal)}`;
        subKey = `r${state.lastRank}/${state.lastTotal}`;
      } else {
        sub = `restarting…  score ${state.score}`;
        subKey = 'pending';
      }
      setOverlay(`gameover:${state.score}:${subKey}`, 'Game Over', sub);
      return;
    }
    setOverlay(null);
  }

  function drawLeaderboard(state) {
    if (!leaderboardList) return;
    const entries = leaderboardData?.entries || [];
    const myName = leaderboardData?.myName || '';
    const visible = entries.slice(0, 5);
    const key = JSON.stringify({
      v: visible.map((e) => [e.rank, e.displayName, e.score, e.id, e.hasReplay ? 1 : 0]),
      m: myName,
    });
    if (key !== leaderboardKey) {
      leaderboardKey = key;
      while (leaderboardList.firstChild) leaderboardList.removeChild(leaderboardList.firstChild);
      if (visible.length === 0) {
        const li = document.createElement('li');
        li.className = 'lb-empty';
        li.textContent = 'be the first to score';
        leaderboardList.appendChild(li);
      } else {
        for (const e of visible) {
          const li = document.createElement('li');
          li.className = 'lb-row';
          if (e.displayName === myName) li.classList.add('is-you');
          const rank = document.createElement('span');
          rank.className = 'lb-rank';
          rank.textContent = `#${e.rank}`;
          const name = document.createElement('span');
          name.className = 'lb-name';
          name.textContent = e.displayName;
          const score = document.createElement('span');
          score.className = 'lb-score';
          score.textContent = e.score.toLocaleString();
          li.appendChild(rank);
          li.appendChild(name);
          li.appendChild(score);
          if (e.hasReplay && e.id != null) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'lb-replay';
            btn.dataset.id = String(e.id);
            btn.title = 'watch replay';
            btn.textContent = '▶';
            li.appendChild(btn);
          }
          leaderboardList.appendChild(li);
        }
      }
    }

    if (leaderboardYou) {
      const rankStr = state.lastRank != null
        ? formatRank(state.lastRank, state.lastTotal)
        : 'unranked';
      const youText = `YOU · ${myName} · ${rankStr}`;
      if (youText !== youKey) {
        youKey = youText;
        leaderboardYou.textContent = youText;
        leaderboardYou.classList.toggle('is-unranked', state.lastRank == null);
      }
    }
  }

  return function render(state) {
    drawGrid();
    drawLocked(state.board);
    drawPiece(state);
    drawNext(state);
    drawHud(state);
    drawLeaderboard(state);
    drawOverlay(state);
  };
}
