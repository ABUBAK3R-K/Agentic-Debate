import { useEffect } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { Aisle } from '../components/Aisle';
import { SimulationNotice } from '../components/SimulationNotice';
import { Thinking } from '../components/Thinking';
import { TranscriptSide } from '../components/TranscriptSide';
import { useDebateStream } from '../hooks/useDebateStream';

const PHASE_NAMES = {
  OPENING: 'Opening statements',
  REBUTTAL: 'Rebuttal',
  COUNTER: 'Counter-argument',
  CLOSING: 'Closing statements',
  JUDGING: 'The judge is reading the transcript',
  COMPLETED: 'Verdict',
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
        <div className="debate-error">
          <p className="error">{debate.error}</p>
          <Link className="button button-quiet" to="/new">Start another debate</Link>
        </div>
      )}

      <Aisle
        className="transcript"
        left={<TranscriptSide side={left} turns={debate.turns} />}
        right={<TranscriptSide side={right} turns={debate.turns} />}
      />

      {/* Under the last closing statement, where the reader already is. */}
      {debate.phase === 'JUDGING' && debate.status === 'live' && (
        <Thinking
          className="judging"
          variant="orbit"
          label="The judge is weighing both sides"
        />
      )}

      <footer className="debate-footer">
        <SimulationNotice>
          A simulation of the personas, not the people themselves — a public
          figure here is played from their public image and never speaks for
          them. Both sides run on the same model with the same settings; only
          the persona and the assigned side differ.
        </SimulationNotice>
      </footer>
    </main>
  );
}
