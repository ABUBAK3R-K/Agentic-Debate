import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { Aisle } from '../components/Aisle';
import { SimulationNotice } from '../components/SimulationNotice';
import { TranscriptSide } from '../components/TranscriptSide';
import { getDebate, readError } from '../services/api';
import { dateFormat } from '../services/format';

const ENDINGS = {
  CREATED: 'This debate was set up but never started.',
  FAILED: 'This debate stopped before the judge could rule on it.',
};

/**
 * A past debate, read back from the record.
 *
 * The same aisle and the same columns as the live screen, only still: no
 * caret, no streaming, every turn as it was finally saved. A finished debate
 * links through to its verdict rather than restaging it here.
 */
export function SavedDebate() {
  const { id } = useParams();
  const [debate, setDebate] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getDebate(id)
      .then(({ data }) => !cancelled && setDebate(data))
      .catch((err) => !cancelled && setError(readError(err, 'Debate not found.')));
    return () => { cancelled = true; };
  }, [id]);

  if (error) {
    return (
      <main className="page">
        <p className="error">{error}</p>
        <Link className="button button-quiet" to="/debates">Back to past debates</Link>
      </main>
    );
  }

  if (!debate) {
    return (
      <main className="page">
        <p className="meta">Fetching the transcript.</p>
      </main>
    );
  }

  const sides = debate.participants.map((p) => ({
    participantId: p.id,
    name: p.friend_name,
    position: p.position,
  }));
  const turns = debate.messages.map((m) => ({
    id: m.id,
    participantId: m.participant_id,
    phase: m.phase,
    text: m.content,
    failed: m.failed,
  }));
  const judged = Boolean(debate.winner_participant_id);
  const ending =
    ENDINGS[debate.status] ??
    (debate.status === 'COMPLETED' ? null : 'This debate is still being argued.');

  return (
    <main className="page page-wide">
      <div className="rail">
        <div className="rail-line">
          <Link className="site-home" to="/debates">Past debates</Link>
          <span className="rail-phase">
            {dateFormat.format(new Date(debate.created_at))}
          </span>
        </div>
      </div>

      <h1 className="motion">{debate.topic}</h1>

      {ending && <p className="meta">{ending}</p>}

      <Aisle
        className="transcript"
        left={<TranscriptSide side={sides[0]} turns={turns} past />}
        right={<TranscriptSide side={sides[1]} turns={turns} past />}
      />

      <footer className="debate-footer saved-footer">
        {judged && (
          <Link className="button" to={`/debate/${debate.id}/verdict`}>
            Read the verdict
          </Link>
        )}
        <SimulationNotice>
          A simulation of the personas, not the people themselves — a public
          figure here was played from their public image and never spoke for
          them. Both sides ran on the same model with the same settings; only
          the persona and the assigned side differed.
        </SimulationNotice>
      </footer>
    </main>
  );
}
