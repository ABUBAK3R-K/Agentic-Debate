import { Thinking } from './Thinking';

const TURN_NAMES = {
  OPENING: 'Opening',
  REBUTTAL: 'Rebuttal',
  COUNTER: 'Counter',
  CLOSING: 'Closing',
};

/**
 * One side of a transcript: a speaker's name, their assigned position, and
 * every turn they took, growing down their own column.
 *
 * Shared by the live debate and a saved one, so a past debate reads exactly
 * as it did while it was being argued. `side` is { participantId, name,
 * position }; each turn is { id, participantId, phase, text, failed,
 * streaming }.
 */
export function TranscriptSide({ side, turns, past = false }) {
  if (!side) {
    return <p className="meta">Waiting for the arena to assign sides.</p>;
  }

  const mine = turns.filter((turn) => turn.participantId === side.participantId);
  const argued = side.position === 'FOR' ? 'for' : 'against';

  return (
    <div data-position={side.position} className="side">
      <header className="side-head">
        <h2 className="side-name display">{side.name}</h2>
        <p className="side-position">
          {past ? `Argued ${argued}` : `Arguing ${argued}`}
        </p>
      </header>

      {mine.length === 0 && (
        <p className="meta">{past ? 'Never spoke.' : 'Yet to speak.'}</p>
      )}

      {mine.map((turn) => (
        <article key={turn.id} className="turn">
          <p className="turn-phase">{TURN_NAMES[turn.phase] || turn.phase}</p>
          {turn.failed ? (
            <p className="turn-failed">
              This turn could not be generated, so it is left empty rather than
              filled with something the model did not actually say.
            </p>
          ) : turn.streaming && !turn.text ? (
            // The turn has opened but no words have arrived yet.
            <Thinking />
          ) : (
            <p className="argument">
              {turn.text}
              {turn.streaming && <span className="caret" />}
            </p>
          )}
        </article>
      ))}
    </div>
  );
}
