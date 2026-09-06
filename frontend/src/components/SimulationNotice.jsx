/**
 * The safety notice. Users describe real people, so the product has to keep
 * saying, where it can actually be read, that this is a simulation built from
 * what they wrote — never a claim about what anyone really thinks.
 */
export function SimulationNotice({ children }) {
  return (
    <p
      className="meta"
      style={{
        maxWidth: '58ch',
        borderLeft: '2px solid var(--rule)',
        paddingLeft: '0.85rem',
      }}
    >
      {children}
    </p>
  );
}
