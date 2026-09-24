import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { listDebates, readError } from '../services/api';
import { dateFormat } from '../services/format';

/** What a debate's stored status means to someone reading the list. */
const STATUS_LINES = {
  CREATED: 'Never started.',
  COMPLETED: null,
  FAILED: 'Stopped before a verdict.',
};

/**
 * Every debate that has been run, newest first.
 *
 * A ruled list rather than a grid of cards: each row is the motion, who
 * argued which side, and how it ended. Names take the colour of the position
 * they argued in that debate, never a colour of their own.
 */
export function PastDebates() {
  const [debates, setDebates] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    listDebates()
      .then(({ data }) => !cancelled && setDebates(data))
      .catch((err) => !cancelled && setError(readError(err)));
    return () => { cancelled = true; };
  }, []);

  return (
    <main className="page">
      <header className="masthead">
        <h1 className="masthead-title display">Past debates</h1>
        <p className="masthead-tagline">Only this browser can see them.</p>
      </header>

      {error && <p className="error">{error}</p>}
      {!debates && !error && <p className="meta">Fetching the record.</p>}

      {debates?.length === 0 && (
        <div className="empty">
          <p>No debates yet. The first one you run will be kept here.</p>
          <Link className="button" to="/new">Set up a debate</Link>
        </div>
      )}

      {debates?.length > 0 && (
        <ol className="record">
          {debates.map((debate) => (
            <li key={debate.id}>
              <DebateRow debate={debate} />
            </li>
          ))}
        </ol>
      )}
    </main>
  );
}

function DebateRow({ debate }) {
  const statusLine =
    debate.status in STATUS_LINES
      ? STATUS_LINES[debate.status]
      : 'Still being argued.';

  return (
    <Link className="record-row" to={`/debates/${debate.id}`}>
      <h2 className="record-topic display">{debate.topic}</h2>

      <p className="record-sides">
        {debate.participants.map((p, index) => (
          <span key={p.id}>
            {index > 0 && ', '}
            <span
              className="record-name"
              data-position={p.position || undefined}
              data-defeated={debate.winner_participant_id ? p.id !== debate.winner_participant_id : undefined}
            >
              {p.friend_name}
            </span>
            {p.position && `${index === 0 ? ' argued' : ''} ${p.position === 'FOR' ? 'for' : 'against'}`}
          </span>
        ))}
        .
      </p>

      <p className="record-outcome">
        {debate.winner_name ? `${debate.winner_name} won.` : statusLine}
      </p>
      <p className="meta">{dateFormat.format(new Date(debate.created_at))}</p>
    </Link>
  );
}
