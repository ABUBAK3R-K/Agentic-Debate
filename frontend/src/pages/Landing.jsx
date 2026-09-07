import { Link } from 'react-router-dom';

import { Aisle } from '../components/Aisle';
import { SimulationNotice } from '../components/SimulationNotice';

/**
 * The landing screen.
 *
 * It is the broadcast's cold open: what the bout is, how it is run, and the
 * one door into it. Every concrete thing on this page is something the
 * product actually does — the four rounds are the four rounds, the sample
 * exchange is shaped like a real transcript, the aisle is the same aisle.
 * Nothing is invented here for visual interest.
 *
 * No entrance motion. The motion budget is spent on the verdict reveal, and
 * a marketing page that animates on scroll would spend it twice.
 */

const CARD = [
  {
    round: '1',
    name: 'Opening',
    line: 'Each side states its case before it has heard the other.',
  },
  {
    round: '2',
    name: 'Rebuttal',
    line: 'Each answers the argument that was just made against it.',
  },
  {
    round: '3',
    name: 'Counter',
    line: 'The exchange narrows onto the point they actually disagree about.',
  },
  {
    round: '4',
    name: 'Closing',
    line: 'Last word. No new ground.',
  },
];

const RULES = [
  {
    title: 'One model, two minds',
    line: `Both debaters run on the same model at the same temperature, top-p and
      token budget. The only difference between them is the persona and the
      side they were handed, so a difference in the transcript is a difference
      in character rather than in setup.`,
  },
  {
    title: 'The arena assigns the sides',
    line: `Nobody picks a position. FOR and AGAINST are dealt by the backend,
      which is why the colours belong to the stance and not to the person —
      the same friend is amber tonight and indigo next time.`,
  },
  {
    title: 'The judge never learns who is who',
    line: `Scoring runs on a separate blind pass that sees only Participant A
      and Participant B, in an order shuffled per debate. Names are mapped
      back on afterwards, once the scores are already fixed.`,
  },
];

export function Landing() {
  return (
    <main className="landing">
      <section className="hero">
        <div className="hero-copy">
          <h1 className="hero-title">Same model. Different minds.</h1>
          <p className="hero-line">
            Describe two friends the way you would to someone who has never met
            them. PersonaArena compiles each description into a persona, sets
            them against each other over four rounds, and has an independent
            judge score the exchange.
          </p>
          <div className="hero-actions">
            <Link className="button" to="/new">Build the card</Link>
            <span className="meta hero-note">
              Takes two descriptions and a motion.
            </span>
          </div>
        </div>

        <Aisle
          className="hero-stage"
          left={<StageSide
            position="FOR"
            name="Priya"
            phase="Round 2 / Rebuttal"
            text="You are quoting a survey of four hundred people who
              volunteered to answer it. That is not the country, that is the
              kind of person who answers surveys."
          />}
          right={<StageSide
            position="AGAINST"
            name="Rahul"
            phase="Round 2 / Rebuttal"
            text="Fine, discard it. The payroll numbers say the same thing and
              nobody volunteered for those"
            writing
          />}
        />
      </section>

      <section className="strip">
        <h2 className="strip-heading">How a bout runs</h2>
        <ol className="card-list">
          {CARD.map((item) => (
            <li className="card-item" key={item.round}>
              <span className="card-round display" aria-hidden="true">{item.round}</span>
              <div>
                <h3 className="card-name">{item.name}</h3>
                <p className="card-line">{item.line}</p>
              </div>
            </li>
          ))}
        </ol>
        <p className="meta card-bookends">
          Positions are dealt before round one and the judge sits after round
          four, so the debate itself is exactly these four exchanges.
        </p>
      </section>

      <section className="strip">
        <h2 className="strip-heading">What the arena controls</h2>
        <div className="rules">
          {RULES.map((rule) => (
            <article className="rule" key={rule.title}>
              <h3 className="rule-title">{rule.title}</h3>
              <p className="rule-line">{rule.line}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="strip closing">
        <h2 className="closing-title">Two friends. One motion.</h2>
        <Link className="button" to="/new">Build the card</Link>
        <SimulationNotice>
          Everything here is a fictional simulation built only from the
          descriptions you write. It never speaks for the real person — at most
          it suggests how the persona you described might argue.
        </SimulationNotice>
      </section>
    </main>
  );
}

/**
 * One podium in the sample exchange. Shaped like a real transcript turn
 * because it is standing in for one — same position binding, same phase rail,
 * same measure. The right-hand side keeps the live caret: mid-sentence is
 * what this screen actually looks like most of the time.
 */
function StageSide({ position, name, phase, text, writing = false }) {
  return (
    <div data-position={position} className="stage-side">
      <header className="side-head">
        <h2 className="side-name display">{name}</h2>
        <p className="side-position">{position}</p>
      </header>
      <p className="turn-phase">{phase}</p>
      <p className="argument">
        {text}
        {writing && <span className="caret" aria-hidden="true" />}
      </p>
    </div>
  );
}
