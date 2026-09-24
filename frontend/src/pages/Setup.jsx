import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { PersonaSheet } from '../components/PersonaSheet';
import { SimulationNotice } from '../components/SimulationNotice';
import { Thinking } from '../components/Thinking';
import {
  compilePersona,
  createDebate,
  createFriend,
  listPersonas,
  readError,
  savePersona,
  startDebate,
} from '../services/api';
import { groupByCategory } from '../services/format';

const TOPICS = [
  'Remote work is better than working from an office.',
  'Social media has done more harm than good.',
  'Universities should drop standardised admissions tests.',
  'Cities should ban private cars from their centres.',
  'Nuclear power is the fastest route to decarbonisation.',
  'A four-day working week would make people more productive.',
  'Voting should be compulsory.',
  'Space exploration is worth its cost.',
  'Talent matters more than hard work.',
  'Fame does more harm than good to the people who have it.',
];

const emptyCorner = () => ({
  name: '',
  description: '',
  friendId: null,
  persona: null,
  isPublic: false,
  state: 'describing', // describing | picking | picking-public | compiling | review
  edited: false, // only an edited sheet is saved as a new version
  error: null,
});

/** A corner filled from a saved persona or a public figure. */
const savedCorner = (saved) => ({
  ...emptyCorner(),
  name: saved.name,
  description: saved.raw_description,
  friendId: saved.friend_id,
  persona: saved.persona,
  isPublic: saved.is_public,
  state: 'review',
});

/**
 * Persona creation and review, and the topic the two of them will argue over.
 *
 * Deliberately one screen: the corners are filled in — described fresh,
 * picked from personas saved earlier, or picked from the public figures —
 * then a topic is chosen, then the bout starts. Colour stays out of it —
 * nobody has a position yet.
 */
export function Setup() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [corners, setCorners] = useState([emptyCorner(), emptyCorner()]);
  // This visitor's compiled personas, and the public figures everyone shares.
  const [saved, setSaved] = useState([]);
  const [figures, setFigures] = useState([]);
  const [topic, setTopic] = useState('');
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState(null);

  const update = (index, patch) =>
    setCorners((current) =>
      current.map((corner, i) => (i === index ? { ...corner, ...patch } : corner)),
    );

  // Load the pickable personas once. `?with=<friend id>` (from the Personas
  // page) puts that persona straight into the first corner.
  useEffect(() => {
    let cancelled = false;
    listPersonas()
      .then(({ data }) => {
        if (cancelled) return;
        const compiled = data.filter((p) => p.persona);
        setSaved(compiled.filter((p) => !p.is_public));
        setFigures(compiled.filter((p) => p.is_public));
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

  /**
   * Save a corner's edits and return the friend who will debate.
   *
   * An untouched sheet is already the latest version on record, so saving it
   * again would only pile up identical versions. An edited public figure is
   * shared with everyone, so the edit becomes this visitor's own copy rather
   * than a change to the original.
   */
  async function commitCorner(corner, index) {
    if (!corner.edited) return corner.friendId;

    if (corner.isPublic) {
      const name = corner.persona.name?.trim() || corner.name;
      const { data: copy } = await createFriend(name, corner.description);
      await savePersona(copy.id, corner.persona);
      // Remember the copy, so a retry after a failed start reuses it.
      update(index, { friendId: copy.id, isPublic: false, edited: false });
      return copy.id;
    }

    await savePersona(corner.friendId, corner.persona);
    update(index, { edited: false });
    return corner.friendId;
  }

  async function begin() {
    setStarting(true);
    setError(null);
    try {
      const ids = await Promise.all(corners.map(commitCorner));
      const { data: debate } = await createDebate(topic.trim(), ids);
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
        Everything here is a fictional simulation. A persona you describe is built
        only from what you write; a public figure is built from how they come across
        in public. Neither speaks for the real person — at most it suggests how
        that persona might argue.
      </SimulationNotice>

      <div className="corners">
        {corners.map((corner, index) => (
          <Corner
            key={index}
            index={index}
            corner={corner}
            // The other corner's pick is not on offer: nobody debates themselves.
            saved={saved.filter((p) => p.friend_id !== corners[1 - index].friendId)}
            figures={figures.filter((p) => p.friend_id !== corners[1 - index].friendId)}
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

        {starting ? (
          <Thinking className="start-button" label="Setting up the debate" />
        ) : (
          <button
            type="button"
            className="button start-button"
            disabled={!ready}
            onClick={begin}
          >
            Start the debate
          </button>
        )}

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

function Corner({ index, corner, saved, figures, onChange, onCompile, onPick, onReset }) {
  const canCompile =
    corner.name.trim().length > 0 && corner.description.trim().length >= 10;
  const choosing = ['describing', 'picking', 'picking-public'].includes(corner.state);

  return (
    <section className="corner">
      <p className="corner-index">{index === 0 ? 'First debater' : 'Second debater'}</p>

      {choosing && (saved.length > 0 || figures.length > 0) && (
        <div className="corner-source" role="group" aria-label="Where this persona comes from">
          <button
            type="button"
            className="source-option"
            aria-pressed={corner.state === 'describing'}
            onClick={() => onChange({ state: 'describing' })}
          >
            Describe someone new
          </button>
          {saved.length > 0 && (
            <button
              type="button"
              className="source-option"
              aria-pressed={corner.state === 'picking'}
              onClick={() => onChange({ state: 'picking', error: null })}
            >
              Pick a saved persona
            </button>
          )}
          {figures.length > 0 && (
            <button
              type="button"
              className="source-option"
              aria-pressed={corner.state === 'picking-public'}
              onClick={() => onChange({ state: 'picking-public', error: null })}
            >
              Pick a public figure
            </button>
          )}
        </div>
      )}

      {corner.state === 'review' && (
        <>
          <PersonaSheet
            persona={corner.persona}
            onChange={(persona) => onChange({ persona, edited: true })}
          />
          {corner.isPublic ? (
            <>
              <div className="persona-source">
                <p className="sheet-label">Drawn from their public image</p>
                <p className="persona-description">{corner.description}</p>
              </div>
              <p className="meta">
                {corner.edited
                  ? 'Edited. The debate will use your own copy; the shared persona stays as it was.'
                  : 'Every field can be edited. An edit makes your own copy, so the shared persona stays as it is.'}
              </p>
            </>
          ) : (
            <p className="meta">
              Every field can be edited. Click one to change it.
            </p>
          )}
          <div className="corner-actions">
            {!corner.isPublic && (
              <button
                type="button"
                className="button button-quiet"
                onClick={onCompile}
              >
                Compile again from the description
              </button>
            )}
            <button type="button" className="button button-quiet" onClick={onReset}>
              Choose someone else
            </button>
          </div>
        </>
      )}

      {corner.state === 'picking' && (
        <PersonaList people={saved} onPick={onPick} label="Saved personas" />
      )}

      {corner.state === 'picking-public' && (
        <FigurePicker figures={figures} onPick={onPick} />
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

          {corner.state === 'compiling' ? (
            <Thinking className="corner-thinking" label="Reading the description" />
          ) : (
            <button
              type="button"
              className="button"
              disabled={!canCompile}
              onClick={onCompile}
            >
              Build the persona
            </button>
          )}
        </div>
      )}
    </section>
  );
}

/** Public figures, one category at a time. */
function FigurePicker({ figures, onPick }) {
  const groups = groupByCategory(figures);
  const [category, setCategory] = useState(groups[0]?.[0]);
  const shown = groups.find(([name]) => name === category) ?? groups[0];

  return (
    <>
      <div className="category-tabs" role="group" aria-label="Category">
        {groups.map(([name]) => (
          <button
            key={name}
            type="button"
            className="source-option"
            aria-pressed={name === shown?.[0]}
            onClick={() => setCategory(name)}
          >
            {name}
          </button>
        ))}
      </div>
      {shown && <PersonaList people={shown[1]} onPick={onPick} label={shown[0]} />}
    </>
  );
}

function PersonaList({ people, onPick, label }) {
  return (
    <ul className="saved-list" aria-label={label}>
      {people.map((person) => (
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
                ? `Argued in ${person.debate_count === 1 ? 'one of your debates' : `${person.debate_count} of your debates`}`
                : 'Not in one of your debates yet'}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
