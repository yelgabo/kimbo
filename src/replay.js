import { OP, createGame } from './game.js';

export function createReplayLogger() {
  const events = [];
  return {
    logInput(op, t) {
      events.push([Math.round(t), op]);
    },
    serialize() {
      return JSON.stringify(events);
    },
    reset() {
      events.length = 0;
    },
    size() { return events.length; },
  };
}

export function parseLog(str) {
  try {
    const arr = JSON.parse(str);
    if (!Array.isArray(arr)) return [];
    return arr.filter(
      (e) => Array.isArray(e) && e.length === 2
        && Number.isFinite(e[0]) && Number.isFinite(e[1])
    );
  } catch {
    return [];
  }
}

const OP_TO_ACTION = {
  [OP.L]: (g) => g.move(-1),
  [OP.R]: (g) => g.move(1),
  [OP.SD_ON]: (g) => g.setSoftDrop(true),
  [OP.SD_OFF]: (g) => g.setSoftDrop(false),
  [OP.HARD]: (g) => g.hardDrop(),
  [OP.CW]: (g) => g.rotate('cw'),
  [OP.CCW]: (g) => g.rotate('ccw'),
};

export function createReplay({ seed, log, speed = 4, onFrame, onDone }) {
  const events = parseLog(log);
  const game = createGame({ seed });
  let idx = 0;
  let simTime = 0;
  let lastReal = 0;
  let stopped = false;
  let rafId = null;

  function tick(now) {
    if (stopped) return;
    if (!lastReal) lastReal = now;
    const dtReal = now - lastReal;
    lastReal = now;
    let remaining = dtReal * speed;

    while (remaining > 0 && !stopped) {
      const nextEventT = idx < events.length ? events[idx][0] : Infinity;
      const advance = Math.min(remaining, Math.max(0, nextEventT - simTime));

      if (advance > 0) {
        game.step(advance);
        simTime += advance;
        remaining -= advance;
      }

      // Drain any events at or before simTime.
      while (idx < events.length && events[idx][0] <= simTime) {
        const [, op] = events[idx];
        const action = OP_TO_ACTION[op];
        if (action) action(game);
        idx++;
      }

      // If no more events and the game ended, we're done.
      if (idx >= events.length && (game.state.gameOver || nextEventT === Infinity)) {
        // Allow a final gravity flush so any falling piece settles.
        if (!game.state.gameOver && remaining > 0) {
          const flush = Math.min(remaining, 200);
          game.step(flush);
          remaining -= flush;
          simTime += flush;
        }
        if (game.state.gameOver || idx >= events.length) {
          onFrame?.(game.state);
          stopped = true;
          onDone?.(game.state);
          return;
        }
      }
    }

    onFrame?.(game.state);
    rafId = requestAnimationFrame(tick);
  }

  rafId = requestAnimationFrame(tick);

  return {
    stop() {
      stopped = true;
      if (rafId) cancelAnimationFrame(rafId);
    },
    state: game.state,
  };
}
