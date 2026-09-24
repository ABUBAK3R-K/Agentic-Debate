import { useEffect, useState } from 'react';

/**
 * The arena is waiting on the model: a 3×3 pixel grid with a wavefront
 * running through it, a shimmering label, and how long it has been going.
 *
 * Shown wherever a wait is real — a debater before their first word, the
 * judge, the persona compiler. Those waits stretch when the provider paces
 * requests, and a still screen reads as a stuck one; the timer is what makes
 * a long wait legible rather than worrying.
 *
 * Variants:
 *   drive — a chevron front driving right. The 650ms cycle is shorter than
 *           the sweep, so two fronts are always in flight.
 *   orbit — a comet lapping the grid's edge, for the judge.
 *
 * Colour comes from the nearest [data-position], so a debater thinks in their
 * side's colour; elsewhere it is plain text colour. Reduced motion freezes
 * the grid at its dim state and stills the label; the timer keeps counting.
 */

const DRIVE = Array.from({ length: 9 }, (_, i) => {
  const row = Math.floor(i / 3);
  const col = i % 3;
  return (col + Math.abs(row - 1)) * 90;
});

const ORBIT_ORDER = [0, 1, 2, 5, 8, 7, 6, 3];
const ORBIT = Array.from({ length: 9 }, (_, i) => {
  const step = ORBIT_ORDER.indexOf(i);
  return step === -1 ? null : step * 110;
});

const PATTERNS = {
  drive: { delays: DRIVE, duration: 650 },
  orbit: { delays: ORBIT, duration: 950 },
};

/** Time since mount, measured rather than counted, so a backgrounded tab
 * (where intervals are throttled) still reads true when it comes back. */
function useElapsed() {
  const [tenths, setTenths] = useState(0);

  useEffect(() => {
    const start = performance.now();
    const timer = setInterval(
      () => setTenths(Math.floor((performance.now() - start) / 100)),
      100,
    );
    return () => clearInterval(timer);
  }, []);

  const seconds = tenths / 10;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m ${(seconds % 60).toFixed(1)}s`;
}

export function Thinking({ label = 'Thinking', variant = 'drive', className = '' }) {
  const elapsed = useElapsed();
  const { delays, duration } = PATTERNS[variant] ?? PATTERNS.drive;

  return (
    <div role="status" className={`thinking ${className}`.trim()}>
      <span className="thinking-grid" aria-hidden="true">
        {delays.map((delay, index) => (
          <span
            key={index}
            className="thinking-cell"
            data-idle={delay === null ? 'true' : undefined}
            style={
              delay === null
                ? undefined
                : { animationDuration: `${duration}ms`, animationDelay: `${delay}ms` }
            }
          />
        ))}
      </span>
      <span className="thinking-label">{label}</span>
      {/* Hidden from assistive tech: a live region that changed ten times a
          second would be read out ten times a second. */}
      <span className="thinking-time" aria-hidden="true">{elapsed}</span>
    </div>
  );
}
