import { Link, useLocation } from 'react-router-dom';

/**
 * The persistent top bar.
 *
 * It stays put while a long transcript scrolls, because the way out of a
 * debate shouldn't require scrolling back to the top. Deliberately holds one
 * destination — inventing nav items for things that don't exist is how a
 * four-screen app starts looking like a dashboard.
 */
export function SiteHeader() {
  const { pathname } = useLocation();
  const atHome = pathname === '/';

  return (
    <header className="site-header">
      <Link
        to="/"
        className="site-name display"
        aria-current={atHome ? 'page' : undefined}
      >
        PersonaArena
      </Link>

      {!atHome && (
        <Link to="/new" className="site-home">New debate</Link>
      )}
    </header>
  );
}
