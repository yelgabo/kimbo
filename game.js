(() => {
  const COLS = 10;
  const ROWS = 20;
  const CELL = 30;
  const NEXT_CELL = 24;
  const BOARD_BG = '#0a0c12';
  const GRID_COLOR = '#161a24';
  const GHOST_ALPHA = 0.2;
  const BEST_KEY = 'kimbo-tetris-best';

  const PIECES = {
    I: {
      color: '#3ddbd9',
      rotations: [
        [[0,1],[1,1],[2,1],[3,1]],
        [[2,0],[2,1],[2,2],[2,3]],
        [[0,2],[1,2],[2,2],[3,2]],
        [[1,0],[1,1],[1,2],[1,3]],
      ],
    },
    O: {
      color: '#f5c518',
      rotations: [
        [[1,0],[2,0],[1,1],[2,1]],
        [[1,0],[2,0],[1,1],[2,1]],
        [[1,0],[2,0],[1,1],[2,1]],
        [[1,0],[2,0],[1,1],[2,1]],
      ],
    },
    T: {
      color: '#b66dff',
      rotations: [
        [[1,0],[0,1],[1,1],[2,1]],
        [[1,0],[1,1],[2,1],[1,2]],
        [[0,1],[1,1],[2,1],[1,2]],
        [[1,0],[0,1],[1,1],[1,2]],
      ],
    },
    S: {
      color: '#5bd16a',
      rotations: [
        [[1,0],[2,0],[0,1],[1,1]],
        [[1,0],[1,1],[2,1],[2,2]],
        [[1,1],[2,1],[0,2],[1,2]],
        [[0,0],[0,1],[1,1],[1,2]],
      ],
    },
    Z: {
      color: '#ec5b5b',
      rotations: [
        [[0,0],[1,0],[1,1],[2,1]],
        [[2,0],[1,1],[2,1],[1,2]],
        [[0,1],[1,1],[1,2],[2,2]],
        [[1,0],[0,1],[1,1],[0,2]],
      ],
    },
    J: {
      color: '#5a8cff',
      rotations: [
        [[0,0],[0,1],[1,1],[2,1]],
        [[1,0],[2,0],[1,1],[1,2]],
        [[0,1],[1,1],[2,1],[2,2]],
        [[1,0],[1,1],[0,2],[1,2]],
      ],
    },
    L: {
      color: '#ff9d3a',
      rotations: [
        [[2,0],[0,1],[1,1],[2,1]],
        [[1,0],[1,1],[1,2],[2,2]],
        [[0,1],[1,1],[2,1],[0,2]],
        [[0,0],[1,0],[1,1],[1,2]],
      ],
    },
  };
  const TYPES = ['I','O','T','S','Z','J','L'];
  const KICKS = [[0,0],[-1,0],[1,0],[0,-1],[-2,0],[2,0]];
  const LINE_POINTS = [0, 40, 100, 300, 1200];

  const canvas = document.getElementById('board');
  const ctx = canvas.getContext('2d');
  const nextCanvas = document.getElementById('next');
  const nctx = nextCanvas.getContext('2d');
  const overlay = document.getElementById('overlay');
  const overlayText = document.getElementById('overlay-text');
  const overlaySub = document.getElementById('overlay-sub');
  const scoreEl = document.getElementById('score');
  const bestEl = document.getElementById('best');
  const levelEl = document.getElementById('level');
  const linesEl = document.getElementById('lines');

  let bag = [];
  function nextType() {
    if (bag.length === 0) {
      bag = TYPES.slice();
      for (let i = bag.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [bag[i], bag[j]] = [bag[j], bag[i]];
      }
    }
    return bag.pop();
  }

  function emptyBoard() {
    return Array.from({ length: ROWS }, () => Array(COLS).fill(null));
  }

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
    lastTime: 0,
  };

  function cellsOf(piece) {
    return PIECES[piece.type].rotations[piece.rot];
  }

  function collides(piece, board) {
    for (const [dx, dy] of cellsOf(piece)) {
      const x = piece.x + dx;
      const y = piece.y + dy;
      if (x < 0 || x >= COLS || y >= ROWS) return true;
      if (y >= 0 && board[y][x]) return true;
    }
    return false;
  }

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
    clearLines();
    spawn();
  }

  function clearLines() {
    let cleared = 0;
    for (let y = ROWS - 1; y >= 0; y--) {
      if (state.board[y].every(c => c)) {
        state.board.splice(y, 1);
        state.board.unshift(Array(COLS).fill(null));
        cleared++;
        y++;
      }
    }
    if (cleared > 0) {
      state.score += LINE_POINTS[cleared] * state.level;
      state.lines += cleared;
      const newLevel = Math.floor(state.lines / 10) + 1;
      if (newLevel > state.level) state.level = newLevel;
    }
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
      const trial = { ...state.piece, rot: newRot, x: state.piece.x + kx, y: state.piece.y + ky };
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

  function topOut() {
    if (state.score > state.best) {
      state.best = state.score;
      localStorage.setItem(BEST_KEY, String(state.best));
    }
    state.gameOver = true;
    state.softDrop = false;
    state.piece = null;
    state.restartAt = performance.now() + 1400;
    showOverlay('Game Over', `restarting…  score ${state.score}`);
  }

  function restart() {
    state.board = emptyBoard();
    state.score = 0;
    state.level = 1;
    state.lines = 0;
    state.dropTimer = 0;
    state.gameOver = false;
    hideOverlay();
    spawn();
  }

  function dropInterval() {
    const base = Math.max(60, 800 - (state.level - 1) * 70);
    return state.softDrop ? Math.min(base, 50) : base;
  }

  function update(dt) {
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

  function drawCell(c, x, y, color, alpha) {
    c.globalAlpha = alpha == null ? 1 : alpha;
    c.fillStyle = color;
    c.fillRect(x + 1, y + 1, CELL - 2, CELL - 2);
    c.globalAlpha = 1;
  }

  function drawBoard() {
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
        if (state.board[y][x]) drawCell(ctx, x * CELL, y * CELL, state.board[y][x]);
      }
    }

    if (state.piece) {
      const ghost = { ...state.piece };
      while (true) {
        const trial = { ...ghost, y: ghost.y + 1 };
        if (collides(trial, state.board)) break;
        ghost.y++;
      }
      const color = PIECES[state.piece.type].color;
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
  }

  function drawNext() {
    nctx.fillStyle = '#1f2433';
    nctx.fillRect(0, 0, nextCanvas.width, nextCanvas.height);
    const type = state.nextType;
    const cells = PIECES[type].rotations[0];
    const color = PIECES[type].color;
    let minX = 4, maxX = 0, minY = 4, maxY = 0;
    for (const [dx, dy] of cells) {
      if (dx < minX) minX = dx;
      if (dx > maxX) maxX = dx;
      if (dy < minY) minY = dy;
      if (dy > maxY) maxY = dy;
    }
    const w = (maxX - minX + 1) * NEXT_CELL;
    const h = (maxY - minY + 1) * NEXT_CELL;
    const offsetX = (nextCanvas.width - w) / 2 - minX * NEXT_CELL;
    const offsetY = (nextCanvas.height - h) / 2 - minY * NEXT_CELL;
    for (const [dx, dy] of cells) {
      nctx.fillStyle = color;
      nctx.fillRect(offsetX + dx * NEXT_CELL + 1, offsetY + dy * NEXT_CELL + 1, NEXT_CELL - 2, NEXT_CELL - 2);
    }
  }

  function drawHud() {
    scoreEl.textContent = state.score;
    bestEl.textContent = state.best;
    levelEl.textContent = state.level;
    linesEl.textContent = state.lines;
  }

  function render() {
    drawBoard();
    drawNext();
    drawHud();
  }

  function showOverlay(t, sub) {
    overlayText.textContent = t;
    overlaySub.textContent = sub || '';
    overlay.classList.remove('hidden');
  }
  function hideOverlay() {
    overlay.classList.add('hidden');
  }

  const REPEAT_DELAY = 130;
  const REPEAT_RATE = 40;
  const repeatTimers = {};
  function startRepeat(k, fn) {
    stopRepeat(k);
    repeatTimers[k] = setTimeout(() => {
      fn();
      repeatTimers[k] = setInterval(fn, REPEAT_RATE);
    }, REPEAT_DELAY);
  }
  function stopRepeat(k) {
    if (repeatTimers[k] != null) {
      clearTimeout(repeatTimers[k]);
      clearInterval(repeatTimers[k]);
      repeatTimers[k] = null;
    }
  }

  function onKeyDown(e) {
    const k = e.key;
    if (k === 'p' || k === 'P') {
      if (e.repeat) return;
      state.paused = !state.paused;
      if (state.paused) showOverlay('Paused', 'press P to resume');
      else if (!state.gameOver) hideOverlay();
      return;
    }
    if (state.paused || state.gameOver) return;
    if (e.repeat) return;
    switch (k) {
      case 'ArrowLeft':
        stopRepeat('ArrowRight');
        move(-1);
        startRepeat('ArrowLeft', () => move(-1));
        break;
      case 'ArrowRight':
        stopRepeat('ArrowLeft');
        move(1);
        startRepeat('ArrowRight', () => move(1));
        break;
      case 'ArrowDown':
        state.softDrop = true;
        softDropStep();
        state.dropTimer = 0;
        break;
      case 'ArrowUp':
      case 'x':
      case 'X':
        rotate('cw');
        break;
      case 'z':
      case 'Z':
        rotate('ccw');
        break;
      case ' ':
        e.preventDefault();
        hardDrop();
        break;
    }
  }

  function onKeyUp(e) {
    const k = e.key;
    if (k === 'ArrowLeft' || k === 'ArrowRight') stopRepeat(k);
    if (k === 'ArrowDown') state.softDrop = false;
  }

  window.addEventListener('keydown', onKeyDown);
  window.addEventListener('keyup', onKeyUp);
  window.addEventListener('blur', () => {
    state.softDrop = false;
    stopRepeat('ArrowLeft');
    stopRepeat('ArrowRight');
  });

  function loop(now) {
    const dt = state.lastTime ? now - state.lastTime : 0;
    state.lastTime = now;
    update(dt);
    render();
    requestAnimationFrame(loop);
  }

  spawn();
  requestAnimationFrame(loop);
})();
