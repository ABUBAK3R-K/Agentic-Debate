import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { PersonaSheet } from '../components/PersonaSheet';
import { SimulationNotice } from '../components/SimulationNotice';
import { Thinking } from '../components/Thinking';
import { compilePersona, listPersonas, readError, savePersona } from '../services/api';
import { groupByCategory } from '../services/format';

/**
 * The personas this visitor has built, newest first, then the public figures
 * everyone can pick.
 *
 * Each of your own is the same editable sheet as on setup — an edit saves a
 * new version, so the compiler's original stays on record. Public figures are
 * shared, so they read here as they are and are only edited as your own copy
 * on the setup screen. Nothing here carries a position colour: outside a
 * debate, nobody has a side.
 */
export function Personas() {
  const [people, setPeople] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    listPersonas()
      .then(({ data }) => !cancelled && setPeople(data))
      .catch((err) => !cancelled && setError(readError(err)));
    return () => { cancelled = true; };
  }, []);

  const replace = (friendId, patch) =>
    setPeople((list) =>
      list.map((p) => (p.friend_id === friendId ? { ...p, ...patch } : p)),
    );

  const own = people?.filter((p) => !p.is_public);
  const figures = people?.filter((p) => p.is_public && p.persona);

  return (
    <main className="page">
      <header className="masthead">
        <h1 className="masthead-title display">Personas</h1>
      </header>

      <SimulationNotice>
        Each persona is a character, not a person. Yours are built from what you
        wrote about a friend; public figures from how they come across in public.
        Either way it is a simulation of that description, not a record of what
        anyone actually thinks.
      </SimulationNotice>

      {error && <p className="error">{error}</p>}
      {!people && !error && <p className="meta">Fetching the personas.</p>}

      {own && (
        <section className="persona-section">
          <h2 className="section-heading">Yours</h2>
          <p className="meta">
            Only you can see these. They belong to this browser, so clearing its
            data or opening the arena on another device starts an empty list.
          </p>

          {own.length === 0 && (
            <div className="empty">
              <p>No personas yet. Describe two friends to build the first ones.</p>
              <Link className="button" to="/new">Set up a debate</Link>
            </div>
          )}

          {own.map((person) => (
            <PersonaEntry
              key={person.friend_id}
              person={person}
              onUpdate={(patch) => replace(person.friend_id, patch)}
            />
          ))}
        </section>
      )}

      {figures?.length > 0 && <PublicFigures figures={figures} />}
    </main>
  );
}

function PersonaEntry({ person, onUpdate }) {
  const [state, setState] = useState('idle'); // idle | saving | compiling
  const [message, setMessage] = useState(null);
  const [failed, setFailed] = useState(false);

  const report = (text, isError = false) => {
    setMessage(text);
    setFailed(isError);
  };

  const edit = async (persona) => {
    onUpdate({ persona });
    setState('saving');
    try {
      const { data } = await savePersona(person.friend_id, persona);
      onUpdate({ version: data.version });
      report(`Saved as version ${data.version}.`);
    } catch (err) {
      report(readError(err, 'The edit could not be saved.'), true);
    } finally {
      setState('idle');
    }
  };

  const compile = async () => {
    setState('compiling');
    report(null);
    try {
      const { data } = await compilePersona(person.friend_id);
      onUpdate({ persona: data.persona, version: data.version });
    } catch (err) {
      report(readError(err, 'The persona could not be compiled.'), true);
    } finally {
      setState('idle');
    }
  };

  const debates = person.debate_count === 1 ? 'one debate' : `${person.debate_count} debates`;

  return (
    <section className="corner persona-entry">
      {person.persona ? (
        <PersonaSheet persona={person.persona} onChange={edit} />
      ) : (
        <h2 className="sheet-name display">{person.name}</h2>
      )}

      <div className="persona-source">
        <p className="sheet-label">What you wrote</p>
        <p className="persona-description">{person.raw_description}</p>
      </div>

      <p className="meta">
        {person.persona
          ? `Version ${person.version}, argued in ${person.debate_count ? debates : 'no debates yet'}.`
          : 'Not compiled yet.'}
      </p>

      {person.persona && (
        <Link
          className="button button-quiet persona-compile"
          to={`/new?with=${person.friend_id}`}
        >
          Use in a new debate
        </Link>
      )}

      {!person.persona && (state === 'compiling' ? (
        <Thinking label="Reading the description" />
      ) : (
        <button type="button" className="button persona-compile" onClick={compile}>
          Compile persona
        </button>
      ))}

      {state === 'saving' && <p className="meta">Saving.</p>}
      {message && state !== 'saving' && (
        <p className={failed ? 'error' : 'meta'} role="status">{message}</p>
      )}
    </section>
  );
}

/**
 * The shared public figures, one category at a time. Each opens to its full
 * sheet, so you can judge for yourself how close the persona is to the way
 * the real person comes across before putting it in a debate.
 */
function PublicFigures({ figures }) {
  const groups = groupByCategory(figures);
  const [category, setCategory] = useState(groups[0][0]);
  const shown = groups.find(([name]) => name === category) ?? groups[0];

  return (
    <section className="persona-section">
      <h2 className="section-heading">Public figures</h2>
      <p className="meta">
        Actors, cricketers and footballers, each written up from interviews,
        press conferences and how they carry themselves on screen or on the
        field. Put two in a debate and see whether the simulation argues the
        way they come across.
      </p>

      <div className="category-tabs" role="group" aria-label="Category">
        {groups.map(([name]) => (
          <button
            key={name}
            type="button"
            className="source-option"
            aria-pressed={name === shown[0]}
            onClick={() => setCategory(name)}
          >
            {name}
          </button>
        ))}
      </div>

      <ul className="figure-list" aria-label={shown[0]}>
        {shown[1].map((person) => (
          <li key={person.friend_id}>
            <details className="figure">
              <summary className="figure-summary">
                <span className="saved-name display">{person.name}</span>
                <span className="saved-traits">
                  {(person.persona.core_traits || []).slice(0, 3).join(', ')}
                </span>
              </summary>
              <div className="figure-body">
                <PersonaSheet persona={person.persona} readOnly />
                <div className="persona-source">
                  <p className="sheet-label">Drawn from their public image</p>
                  <p className="persona-description">{person.raw_description}</p>
                </div>
                <Link
                  className="button button-quiet persona-compile"
                  to={`/new?with=${person.friend_id}`}
                >
                  Use in a new debate
                </Link>
              </div>
            </details>
          </li>
        ))}
      </ul>
    </section>
  );
}
