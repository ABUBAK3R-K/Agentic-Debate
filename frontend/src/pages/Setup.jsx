import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { PersonaSheet } from '../components/PersonaSheet';
import { SimulationNotice } from '../components/SimulationNotice';
import {
  compilePersona,
  createDebate,
  createFriend,
  listPersonas,
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
  state: 'describing', // describing | picking | compiling | review
  edited: false, // only an edited sheet is saved as a new version
  error: null,
});

/** A corner filled from a persona saved in an earlier session. */
const savedCorner = (saved) => ({
  ...emptyCorner(),
  name: saved.name,
  description: saved.raw_description,
  friendId: saved.friend_id,
  persona: saved.persona,
  state: 'review',
});

/**
 * Persona creation and review, and the topic the two of them will argue over.
 *
 * Deliberately one screen: the corners are filled in — described fresh or
 * picked from personas saved earlier — then a topic is chosen, then the bout
 * starts. Colour stays out of it — nobody has a position yet.
 */
export function Setup() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [corners, setCorners] = useState([emptyCorner(), emptyCorner()]);
  // Compiled personas from earlier debates, offered in place of a new one.
  const [saved, setSaved] = useState([]);
  const [topic, setTopic] = useState('');
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState(null);

  const update = (index, patch) =>
    setCorners((current) =>
      current.map((corner, i) => (i === index ? { ...corner, ...patch } : corner)),
    );

  // Load the saved personas once. `?with=<friend id>` (from the Personas page)
  // puts that persona straight into the first corner.
  useEffect(() => {
    let cancelled = false;
    listPersonas()
      .then(({ data }) => {
        if (cancelled) return;
        const compiled = data.filter((p) => p.persona);
        setSaved(compiled);
        const preset = compiled.find((p) => p.friend_id === params.get('with'));
        if (preset) {
          setCorners((current) => [savedCorner(preset), current[1]]);
        }
      })
      .catch(() => {}); // Saved personas are an option, never a blocker.
    return () => { cancelled = true; };
  }, [params]);

  async function compile(index) {
    const corner = corners[index];
    update(index, { state: 'compiling', error: null });
    try {
      const friend = corner.friendId
        ? { id: corner.friendId }
        : (await createFriend(corner.name.trim(), corner.description.trim())).data;
      const { data } = await compilePersona(friend.id);
      update(index, {
        friendId: friend.id,
        persona: data.persona,
        state: 'review',
        edited: false,
      });
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
      // Save any edits the user made to either sheet before the debate reads
      // them. An untouched sheet is already the latest version on record, so
      // saving it again would only pile up identical versions.
      await Promise.all(
        corners
          .filter((corner) => corner.edited)
          .map((corner) => savePersona(corner.friendId, corner.persona)),
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

  const ready =
    corners.every((c) => c.state === 'review') &&
    corners[0].friendId !== corners[1].friendId &&
    topic.trim().length >= 5;

  return (
    <main className="page">
      <header className="masthead">
        {/* The hero line lives on the landing page; this screen is the work. */}
        <h1 className="masthead-title">Tonight's card</h1>
        <p className="masthead-tagline">
          Two personas and a motion. The arena assigns the sides.
        </p>
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
            // The other corner's pick is not on offer: nobody debates themselves.
            saved={saved.filter((p) => p.friend_id !== corners[1 - index].friendId)}
            onChange={(patch) => update(index, patch)}
            onCompile={() => compile(index)}
            onPick={(persona) => update(index, savedCorner(persona))}
            onReset={() => update(index, emptyCorner())}
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
            maxLength={300}
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
            Both debaters need a persona, and the motion needs a few words.
            Sides are assigned by the arena once the debate begins.
          </p>
        )}
      </section>
    </main>
  );
}

function Corner({ index, corner, saved, onChange, onCompile, onPick, onReset }) {
  const canCompile =
    corner.name.trim().length > 0 && corner.description.trim().length >= 10;
  const choosing = corner.state === 'describing' || corner.state === 'picking';

  return (
    <section className="corner">
      <p className="corner-index">{index === 0 ? 'First debater' : 'Second debater'}</p>

      {choosing && saved.length > 0 && (
        <div className="corner-source" role="group" aria-label="Where this persona comes from">
          <button
            type="button"
            className="source-option"
            aria-pressed={corner.state === 'describing'}
            onClick={() => onChange({ state: 'describing' })}
          >
            Describe someone new
          </button>
          <button
            type="button"
            className="source-option"
            aria-pressed={corner.state === 'picking'}
            onClick={() => onChange({ state: 'picking', error: null })}
          >
            Pick a saved persona
          </button>
        </div>
      )}

      {corner.state === 'review' && (
        <>
          <PersonaSheet
            persona={corner.persona}
            onChange={(persona) => onChange({ persona, edited: true })}
          />
          <p className="meta">
            Every field can be edited. Click one to change it.
          </p>
          <div className="corner-actions">
            <button
              type="button"
              className="button button-quiet"
              onClick={onCompile}
            >
              Compile again from the description
            </button>
            <button type="button" className="button button-quiet" onClick={onReset}>
              Choose someone else
            </button>
          </div>
        </>
      )}

      {corner.state === 'picking' && (
        <ul className="saved-list" aria-label="Saved personas">
          {saved.map((person) => (
            <li key={person.friend_id}>
              <button
                type="button"
                className="saved-option"
                onClick={() => onPick(person)}
              >
                <span className="saved-name display">{person.name}</span>
                <span className="saved-traits">
                  {(person.persona.core_traits || []).slice(0, 3).join(', ')}
                </span>
                <span className="meta">
                  {person.debate_count
                    ? `Argued in ${person.debate_count === 1 ? 'one debate' : `${person.debate_count} debates`}`
                    : 'Not in a debate yet'}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {(corner.state === 'describing' || corner.state === 'compiling') && (
        <div className="corner-form">
          <label className="sheet-label" htmlFor={`name-${index}`}>Name</label>
          <input
            id={`name-${index}`}
            className="field"
            value={corner.name}
            placeholder="Rahul"
            maxLength={100}
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
            maxLength={2000}
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
