import { Link, useLocation } from 'react-router-dom';

const DESTINATIONS = [
  ['/debates', 'Past debates'],
  ['/personas', 'Personas'],
  ['/new', 'New debate'],
];

/**
 * The persistent top bar.
 *
 * It stays put while a long transcript scrolls, because the way out of a
 * debate shouldn't require scrolling back to the top. It holds only places
 * that exist: the record of past debates, the personas, and a new debate.
 */
export function SiteHeader() {
  const { pathname } = useLocation();

  const current = (path) =>
    pathname === path || pathname.startsWith(`${path}/`) ? 'page' : undefined;

  return (
    <header className="site-header">
      <Link
        to="/"
        className="site-name display"
        aria-current={pathname === '/' ? 'page' : undefined}
      >
        PersonaArena
      </Link>

      <nav className="site-nav" aria-label="Main">
        {DESTINATIONS.map(([path, label]) => (
          <Link key={path} to={path} className="site-home" aria-current={current(path)}>
            {label}
          </Link>
        ))}
      </nav>
    </header>
  );
}
