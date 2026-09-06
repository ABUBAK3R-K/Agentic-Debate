import { useEffect, useRef, useState } from 'react';

/**
 * A compiled persona, shown as a profile sheet and edited in place.
 *
 * Nothing here is coloured by position: on this screen nobody has a side yet.
 * FOR and AGAINST are handed out when the debate starts, so introducing amber
 * or indigo before that would attach a colour to a person, which is exactly
 * what the colour system is built to avoid.
 */

function EditableValue({ value, onChange, label, display = false, multiline = false }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const inputRef = useRef(null);

  useEffect(() => setDraft(value), [value]);
  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  function commit() {
    setEditing(false);
    if (draft !== value) onChange(draft);
  }

  function onKeyDown(event) {
    if (event.key === 'Enter' && !multiline) {
      event.preventDefault();
      commit();
    }
    if (event.key === 'Escape') {
      setDraft(value);
      setEditing(false);
    }
  }

  if (editing) {
    const Tag = multiline ? 'textarea' : 'input';
    return (
      <Tag
        ref={inputRef}
        className="field"
        style={
          display
            ? {
                fontFamily: 'var(--font-display)',
                fontSize: 'clamp(2.4rem, 6vw, 3.4rem)',
                fontWeight: 700,
                lineHeight: 0.95,
                padding: '0.1em 0.2em',
              }
            : { minHeight: multiline ? '4.5rem' : undefined }
        }
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={onKeyDown}
        aria-label={`Edit ${label}`}
      />
    );
  }

  return (
    <button
      type="button"
      className="editable"
      onClick={() => setEditing(true)}
      aria-label={`${label}: ${value || 'not set'}. Click to edit.`}
    >
      {value || <span style={{ color: 'var(--text-muted)' }}>Not set</span>}
    </button>
  );
}

/** Traits read as a row of tags, and edit as one comma-separated line. */
function EditableTags({ values, onChange, label }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const inputRef = useRef(null);

  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  function open() {
    setDraft(join(values));
    setEditing(true);
  }

  function commit() {
    setEditing(false);
    onChange(split(draft));
  }

  if (editing) {
    return (
      <input
        ref={inputRef}
        className="field"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
          if (e.key === 'Escape') setEditing(false);
        }}
        aria-label={`Edit ${label}, separated by commas`}
      />
    );
  }

  return (
    <button type="button" className="tags" onClick={open} aria-label={`${label}. Click to edit.`}>
      {(values || []).length
        ? values.map((trait) => (
            <span className="tag" key={trait}>{trait}</span>
          ))
        : <span className="tag">Add traits</span>}
    </button>
  );
}


function Row({ label, children }) {
  return (
    <div className="sheet-row">
      <span className="sheet-label">{label}</span>
      <div className="sheet-value">{children}</div>
    </div>
  );
}

const join = (list) => (list || []).join(', ');
const split = (text) =>
  text.split(',').map((part) => part.trim()).filter(Boolean);

export function PersonaSheet({ persona, onChange }) {
  const set = (path, value) => {
    const next = structuredClone(persona);
    let target = next;
    for (const key of path.slice(0, -1)) target = target[key];
    target[path[path.length - 1]] = value;
    onChange(next);
  };

  const reasoning = persona.reasoning_style || {};
  const voice = persona.communication_style || {};
  const debate = persona.debate_style || {};

  return (
    <article className="sheet">
      <h2 className="sheet-name">
        <EditableValue
          display
          label="name"
          value={persona.name}
          onChange={(v) => set(['name'], v)}
        />
      </h2>

      <EditableTags
        label="core traits"
        values={persona.core_traits}
        onChange={(v) => set(['core_traits'], v)}
      />

      <dl className="sheet-rows">
        <Row label="Values">
          <EditableValue
            label="values"
            value={join(persona.values)}
            onChange={(v) => set(['values'], split(v))}
          />
        </Row>

        <Row label="Reasoning">
          <EditableValue
            label="decision making"
            value={reasoning.decision_making}
            onChange={(v) => set(['reasoning_style', 'decision_making'], v)}
          />
          <span className="sheet-sep">Risk</span>
          <EditableValue
            label="risk tolerance"
            value={reasoning.risk_tolerance}
            onChange={(v) => set(['reasoning_style', 'risk_tolerance'], v)}
          />
          <span className="sheet-sep">Evidence</span>
          <EditableValue
            label="evidence preference"
            value={reasoning.evidence_preference}
            onChange={(v) => set(['reasoning_style', 'evidence_preference'], v)}
          />
        </Row>

        <Row label="Voice">
          <EditableValue
            label="tone"
            value={voice.tone}
            onChange={(v) => set(['communication_style', 'tone'], v)}
          />
          <span className="sheet-sep">Directness</span>
          <EditableValue
            label="directness"
            value={voice.directness}
            onChange={(v) => set(['communication_style', 'directness'], v)}
          />
          <span className="sheet-sep">Humour</span>
          <EditableValue
            label="humour"
            value={voice.humor}
            onChange={(v) => set(['communication_style', 'humor'], v)}
          />
        </Row>

        <Row label="In a debate">
          <EditableValue
            label="aggressiveness"
            value={debate.aggressiveness}
            onChange={(v) => set(['debate_style', 'aggressiveness'], v)}
          />
          <span className="sheet-sep">Tactics</span>
          <EditableValue
            label="preferred tactics"
            value={join(debate.preferred_tactics)}
            onChange={(v) => set(['debate_style', 'preferred_tactics'], split(v))}
          />
        </Row>

        <Row label="Strengths">
          <EditableValue
            label="strengths"
            value={join(persona.strengths)}
            onChange={(v) => set(['strengths'], split(v))}
          />
        </Row>

        <Row label="Blind spots">
          <EditableValue
            label="weaknesses"
            value={join(persona.weaknesses)}
            onChange={(v) => set(['weaknesses'], split(v))}
          />
        </Row>
      </dl>
    </article>
  );
}
