import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { PersonaSheet } from '../components/PersonaSheet';
import { SimulationNotice } from '../components/SimulationNotice';
import { compilePersona, listPersonas, readError, savePersona } from '../services/api';

/**
 * Every persona built so far, newest first.
 *
 * Each one is the same editable sheet as on setup — an edit saves a new
 * version, so the compiler's original stays on record. Nothing here carries
 * a position colour: outside a debate, nobody has a side.
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

  return (
    <main className="page">
      <header className="masthead">
        <h1 className="masthead-title display">Personas</h1>
      </header>

      <SimulationNotice>
        Each persona is a character built from what you wrote about a friend.
        It is a simulation of that description, not a record of what they
        actually think.
      </SimulationNotice>

      {error && <p className="error">{error}</p>}
      {!people && !error && <p className="meta">Fetching the personas.</p>}

      {people?.length === 0 && (
        <div className="empty">
          <p>No personas yet. Describe two friends to build the first ones.</p>
          <Link className="button" to="/new">Set up a debate</Link>
        </div>
      )}

      {people?.map((person) => (
        <PersonaEntry
          key={person.friend_id}
          person={person}
          onUpdate={(patch) => replace(person.friend_id, patch)}
        />
      ))}
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

      {!person.persona && (
        <button
          type="button"
          className="button persona-compile"
          disabled={state === 'compiling'}
          onClick={compile}
        >
          {state === 'compiling' ? 'Compiling' : 'Compile persona'}
        </button>
      )}

      {state === 'saving' && <p className="meta">Saving.</p>}
      {message && state !== 'saving' && (
        <p className={failed ? 'error' : 'meta'} role="status">{message}</p>
      )}
    </section>
  );
}
