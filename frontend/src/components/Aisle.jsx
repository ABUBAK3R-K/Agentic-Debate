/**
 * The center aisle: two sides with a real rule between them.
 *
 * The rule is the product's spine — it is present on every screen that shows
 * two opposed sides, and it is the thing that makes this read as two people
 * talking across a divide rather than one merged thread. On a narrow screen
 * the columns stack and the rule turns horizontal.
 */
export function Aisle({ left, right, className = '' }) {
  return (
    <div className={`aisle ${className}`}>
      <div className="aisle-side">{left}</div>
      <div className="aisle-rule" aria-hidden="true" />
      <div className="aisle-side">{right}</div>
    </div>
  );
}
