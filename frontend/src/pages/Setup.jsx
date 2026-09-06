import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { PersonaSheet } from '../components/PersonaSheet';
import { SimulationNotice } from '../components/SimulationNotice';
import {
  compilePersona,
  createDebate,
  createFriend,
  readError,
  savePersona,
  startDebate,
} from '../services/api';

const TOPICS = [
  'Remote work is better than working from an office.',
  'Social media has done more harm than good.',
  'Universities should drop standardised admissions tests.',
  'Cities should ban private cars from their centres.',
  'Nuclear power is the fastest route to decarbonisation.',
  'A four-day working week would make people more productive.',
  'Voting should be compulsory.',
  'Space exploration is worth its cost.',
];

const emptyCorner = () => ({
  name: '',
  description: '',
  friendId: null,
  persona: null,
  state: 'describing', // describing | compiling | review
  error: null,
});

/**
 * Persona creation and review, and the topic the two of them will argue over.
 *
 * Deliberately one screen: the corners are filled in, then a topic is chosen,
 * then the bout starts. Colour stays out of it — nobody has a position yet.
 */
export function Setup() {
  const navigate = useNavigate();
  const [corners, setCorners] = useState([emptyCorner(), emptyCorner()]);
  const [topic, setTopic] = useState('');
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState(null);

  const update = (index, patch) =>
    setCorners((current) =>
      current.map((corner, i) => (i === index ? { ...corner, ...patch } : corner)),
    );

  async function compile(index) {
    const corner = corners[index];
    update(index, { state: 'compiling', error: null });
    try {
      const friend = corner.friendId
        ? { id: corner.friendId }
        : (await createFriend(corner.name.trim(), corner.description.trim())).data;
      const { data } = await compilePersona(friend.id);
      update(index, { friendId: friend.id, persona: data.persona, state: 'review' });
    } catch (err) {
      update(index, {
        state: 'describing',
        error: readError(err, 'The persona compiler could not read that description.'),
      });
    }
  }

  async function begin() {
    setStarting(true);
    setError(null);
    try {
      // Save any edits the user made to either sheet before the debate reads them.
      await Promise.all(
        corners.map((corner) => savePersona(corner.friendId, corner.persona)),
      );
      const { data: debate } = await createDebate(
        topic.trim(),
        corners.map((corner) => corner.friendId),
      );
      await startDebate(debate.id);
      navigate(`/debate/${debate.id}`);
    } catch (err) {
      setError(readError(err, 'The debate could not be started.'));
      setStarting(false);
    }
  }

  const ready = corners.every((c) => c.state === 'review') && topic.trim().length >= 5;

  return (
    <main className="page">
      <header className="masthead">
        <h1 className="masthead-title">PersonaArena</h1>
        <p className="masthead-tagline">Same model. Different minds.</p>
      </header>

      <SimulationNotice>
        Everything here is a fictional simulation built only from the descriptions
        you write. It never speaks for the real person — at most it suggests how the
        persona you described might argue.
      </SimulationNotice>

      <div className="corners">
        {corners.map((corner, index) => (
          <Corner
            key={index}
            index={index}
            corner={corner}
            onChange={(patch) => update(index, patch)}
            onCompile={() => compile(index)}
          />
        ))}
      </div>

      <section className="topic">
        <h2 className="section-heading">The motion</h2>
        <div className="topic-controls">
          <input
            className="field"
            value={topic}
            placeholder="What should they argue about?"
            onChange={(event) => setTopic(event.target.value)}
            aria-label="Debate topic"
          />
          <button
            type="button"
            className="button button-quiet"
            onClick={() => setTopic(TOPICS[Math.floor(Math.random() * TOPICS.length)])}
          >
            Surprise me
          </button>
        </div>

        {error && <p className="error">{error}</p>}

        <button
          type="button"
          className="button start-button"
          disabled={!ready || starting}
          onClick={begin}
        >
          {starting ? 'Starting' : 'Start the debate'}
        </button>

        {!ready && (
          <p className="meta">
            Both personas need to be compiled, and the motion needs a few words.
            Sides are assigned by the arena once the debate begins.
          </p>
        )}
      </section>
    </main>
  );
}

function Corner({ index, corner, onChange, onCompile }) {
  const canCompile =
    corner.name.trim().length > 0 && corner.description.trim().length >= 10;

  return (
    <section className="corner">
      <p className="corner-index">{index === 0 ? 'First debater' : 'Second debater'}</p>

      {corner.state === 'review' ? (
        <>
          <PersonaSheet
            persona={corner.persona}
            onChange={(persona) => onChange({ persona })}
          />
          <p className="meta">
            Every field can be edited. Click one to change it.
          </p>
          <button
            type="button"
            className="button button-quiet"
            onClick={onCompile}
          >
            Compile again from the description
          </button>
        </>
      ) : (
        <div className="corner-form">
          <label className="sheet-label" htmlFor={`name-${index}`}>Name</label>
          <input
            id={`name-${index}`}
            className="field"
            value={corner.name}
            placeholder="Rahul"
            onChange={(event) => onChange({ name: event.target.value })}
          />

          <label className="sheet-label" htmlFor={`description-${index}`}>
            How do they think and argue?
          </label>
          <textarea
            id={`description-${index}`}
            className="field"
            value={corner.description}
            placeholder="Skeptical, wants numbers before he'll agree to anything, dry sense of humour, never concedes a point he hasn't tested."
            onChange={(event) => onChange({ description: event.target.value })}
          />

          {corner.error && <p className="error">{corner.error}</p>}

          <button
            type="button"
            className="button"
            disabled={!canCompile || corner.state === 'compiling'}
            onClick={onCompile}
          >
            {corner.state === 'compiling' ? 'Reading the description' : 'Build the persona'}
          </button>
        </div>
      )}
    </section>
  );
}
