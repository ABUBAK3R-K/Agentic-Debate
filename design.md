# PersonaArena — Design System (v1)

## Direction

One sentence: **a live debate broadcast — two podiums, one aisle between them, a verdict at the end.**

Ground every screen in that: PersonaArena isn't a chat app and it isn't a SaaS dashboard. It's closer to watching a televised debate or a boxing weigh-in — two clearly-opposed sides, a scoreboard, a moment where a decision is announced. Build toward that feeling specifically; don't default to a generic dark-mode chat UI.

## Anti-patterns — actively avoid these

v1 likely fell into some of these by default. Check against this list before considering a screen done:

- Uniform rounded white/gray cards with the same soft drop-shadow on everything, regardless of what the card contains.
- ALL-CAPS eyebrow labels above headings ("PERSONA", "ROUND 2").
- A monospace font used for small data labels just because it looks "technical."
- Meta text strings joined with middle dots (`Rahul · Skeptical · Round 2`).
- Buttons or links with a trailing arrow (`Start debate →`).
- Gradient washes used as pure decoration.
- Generic progress bars or percentage stats invented for visual interest rather than showing a real number.
- A single fade-and-slide-up entrance animation repeated on every section/card.

## Color

| Token | Hex | Use |
|---|---|---|
| `--stage` | `#12151C` | Page background — a deep ink-charcoal, not pure black |
| `--panel` | `#1B1F29` | Cards, panels, the debate transcript surface |
| `--for` | `#E8A33D` | Everything tied to the FOR / affirmative position — warm amber |
| `--against` | `#6C6FE0` | Everything tied to the AGAINST position — cool indigo |
| `--text` | `#EDEAE2` | Primary text — warm off-white, not pure white |
| `--text-muted` | `#8B8F9C` | Secondary text, timestamps, meta |

**The rule that matters most: `--for` and `--against` are bound to a debate *position*, never to a specific friend.** The same friend argues FOR in one debate and AGAINST in another — the color always tracks the stance, not the identity, so a viewer can tell who's arguing which side at a glance regardless of who's debating.

There's no separate "success green" for winners. A verdict is shown by *filling* the winner's own position color solidly and letting the loser's fade to `--text-muted` — the two-color system carries the win/loss meaning on its own.

## Type

- **Display** — Big Shoulders Display (tall, condensed, broadcast/signage feel). Used for: persona names, round numbers, the verdict announcement. Nowhere else.
- **Body** — IBM Plex Sans. Used for: arguments, descriptions, all UI copy. Keep argument text under ~70 characters per line — that's the actual product, it needs to be comfortable to read even with dramatic chrome around it.
- Two families, clearly distinct in weight and width. No third face, no monospace.

## Layout

### Live debate screen (the main event — get this right first)

```
+------------------- ROUND 2 / 4 - REBUTTAL --------------------+
|                                                                |
|   RAHUL (FOR)           | aisle |        AMAN (AGAINST)       |
|   --------------        |       |        --------------       |
|   "Your argument         |       |        "But you're           |
|   assumes ..."           |       |        ignoring ..."          |
|                          |       |                               |
+----------------------------------------------------------------+
```

The center aisle is a real vertical rule, always present, on every debate screen. Each side's transcript grows independently downward in its own column — this is two people talking past a divide, not one merged chat thread. New text streams in as it's generated (SSE gives you this for free — don't add extra entrance animation on top of it).

### Persona creation / review

Single column, centered, styled like a fighter profile sheet rather than a form: name in display type at the top, traits shown as a short row of tags (not a bulleted list), reasoning style and debate tendencies each as one line. Edit happens inline on the same sheet, not in a separate modal.

### Verdict screen

```
                    +-------------+
                    |   WINNER    |
                    |   RAHUL     |   <- full-bleed --for wash behind this
                    +-------------+

     RAHUL                              AMAN
     Logic       8.7                    7.1
     Rebuttal    9.1                    6.4
     Overall     8.6                    6.9

     "Strongest argument: ..."
```

The winner's name gets the full-bleed color moment — this is the one place in the product that's allowed to be loud. Scores sit in the same two-column, aisle-echoing layout as the debate itself. No bar charts, no radial gauges — the numbers are the content.

## Motion

Spend the entire motion budget on one moment: the transition from "debate in progress" to "verdict revealed." Everything else is a direct response to something the user did (opening a persona for edit, submitting a form) — no scroll-triggered reveals, no hover animations on cards that don't do anything when clicked.

## Quality floor

Responsive down to a single-column mobile layout (the aisle becomes a horizontal divider between stacked sides, not two side-by-side columns). Visible keyboard focus states on every interactive element. Respect `prefers-reduced-motion` for the verdict transition. Contrast-check `--text-muted` against `--stage` and `--panel` before shipping — muted text is often the first thing that fails accessibility contrast on a dark background.
