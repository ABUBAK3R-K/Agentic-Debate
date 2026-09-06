import { useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { Aisle } from '../components/Aisle';
import { SimulationNotice } from '../components/SimulationNotice';
import { useDebateStream } from '../hooks/useDebateStream';

const PHASE_NAMES = {
  OPENING: 'Opening statements',
  REBUTTAL: 'Rebuttal',
  COUNTER: 'Counter-argument',
  CLOSING: 'Closing statements',
  JUDGING: 'The judge is reading the transcript',
  COMPLETED: 'Verdict',
};

const TURN_NAMES = {
  OPENING: 'Opening',
  REBUTTAL: 'Rebuttal',
  COUNTER: 'Counter',
  CLOSING: 'Closing',
};

/**
 * The main event. Two columns, one aisle, text arriving as it is written.
 *
 * Each side's transcript grows independently down its own column — this is two
 * people talking past a divide, not one merged thread. New text is the only
 * motion on this screen; nothing animates its way in on top of the stream.
 */
export function LiveDebate() {
  const { id } = useParams();
  const navigate = useNavigate();
  const debate = useDebateStream(id, true);

  useEffect(() => {
    if (debate.status === 'complete') {
      navigate(`/debate/${id}/verdict`, { replace: true });
    }
  }, [debate.status, id, navigate]);

  const [left, right] = debate.sides;

  return (
    <main className="page page-wide">
      <div className="rail">
        <div className="rail-line">
          <span className="rail-round display">
            {debate.round ? `Round ${debate.round} of 4` : 'Taking positions'}
          </span>
          <span className="rail-phase">{PHASE_NAMES[debate.phase] || 'Getting ready'}</span>
        </div>
      </div>

      <h1 className="motion">{debate.topic || ' '}</h1>

      {debate.status === 'error' && (
        <p className="error">{debate.error}</p>
      )}

      <Aisle
        className="transcript"
        left={<Side side={left} turns={debate.turns} />}
        right={<Side side={right} turns={debate.turns} />}
      />

      <footer className="debate-footer">
        <SimulationNotice>
          A simulation of the personas you described, not the people themselves.
          Both sides run on the same model with the same settings — only the
          persona and the assigned side differ.
        </SimulationNotice>
      </footer>
    </main>
  );
}

function Side({ side, turns }) {
  if (!side) {
    return <p className="meta">Waiting for the arena to assign sides.</p>;
  }

  const mine = turns.filter((turn) => turn.participantId === side.participantId);

  return (
    <div data-position={side.position} className="side">
      <header className="side-head">
        <h2 className="side-name display">{side.name}</h2>
        <p className="side-position">
          {side.position === 'FOR' ? 'Arguing for' : 'Arguing against'}
        </p>
      </header>

      {mine.length === 0 && <p className="meta">Yet to speak.</p>}

      {mine.map((turn) => (
        <article key={turn.id} className="turn">
          <p className="turn-phase">{TURN_NAMES[turn.phase] || turn.phase}</p>
          {turn.failed ? (
            <p className="turn-failed">
              This turn could not be generated, so it is left empty rather than
              filled with something the model did not actually say.
            </p>
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
