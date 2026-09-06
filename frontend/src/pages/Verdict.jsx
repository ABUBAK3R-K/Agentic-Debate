import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { Aisle } from '../components/Aisle';
import { getResult, readError } from '../services/api';

const CRITERIA = [
  ['logic', 'Logic'],
  ['evidence', 'Evidence'],
  ['rebuttal', 'Rebuttal'],
  ['persuasiveness', 'Persuasion'],
  ['overall', 'Overall'],
];

/**
 * The verdict. The one loud moment in the product.
 *
 * The winner's own position colour fills the screen behind their name, and the
 * losing side fades out of the colour system entirely — there is no separate
 * "success" colour, because the two-colour system already carries the meaning.
 * Scores are numbers, not bars: the numbers are the content.
 */
export function Verdict() {
  const { id } = useParams();
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    getResult(id)
      .then(({ data }) => !cancelled && setResult(data))
      .catch((err) => !cancelled && setError(readError(err, 'No verdict yet.')));

    return () => { cancelled = true; };
  }, [id]);

  if (error) {
    return (
      <main className="page">
        <p className="error">{error}</p>
        <Link className="button button-quiet" to="/">Start another debate</Link>
      </main>
    );
  }

  if (!result) {
    return (
      <main className="page">
        <p className="meta">Reading the judge's decision.</p>
      </main>
    );
  }

  const winner = result.participants.find((p) => p.is_winner);
  const [left, right] = result.participants;

  return (
    <main className="verdict">
      <section
        className="wash"
        data-position={winner?.position}
        aria-label={`Winner: ${result.winner_name}`}
      >
        <div className="wash-fill" />
        <div className="wash-content">
          <p className="wash-label">Winner</p>
          <h1 className="wash-name display">{result.winner_name}</h1>
        </div>
      </section>

      <div className="page page-wide verdict-body">
        <p className="motion-recap">{result.topic}</p>

        <Aisle
          left={<Scores participant={left} />}
          right={<Scores participant={right} />}
        />

        <section className="judgement">
          <Note label="Why they won" text={result.winner_reason} />
          <Note label="Strongest argument" text={result.strongest_argument} />
          <Note label="Weakest argument" text={result.weakest_argument} />
        </section>

        <Link className="button button-quiet" to="/">Start another debate</Link>
      </div>
    </main>
  );
}

function Scores({ participant }) {
  if (!participant) return null;

  return (
    <div
      className="scores"
      data-position={participant.position}
      data-defeated={!participant.is_winner}
    >
      <h2 className="scores-name display">{participant.name}</h2>
      <p className="scores-position">
        {participant.position === 'FOR' ? 'Argued for' : 'Argued against'}
      </p>

      <dl className="score-list">
        {CRITERIA.map(([key, label], index) => (
          <div className="score" key={key} style={{ '--stagger': `${index * 60}ms` }}>
            <dt className="score-label">{label}</dt>
            <dd className="score-value display">
              {formatScore(participant.scores?.[key])}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function Note({ label, text }) {
  if (!text) return null;
  return (
    <div className="note">
      <p className="sheet-label">{label}</p>
      <p className="note-text">{text}</p>
    </div>
  );
}

/** Overall arrives as a float, the rest as integers. Show them as given. */
function formatScore(value) {
  if (value === undefined || value === null) return '—';
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}
