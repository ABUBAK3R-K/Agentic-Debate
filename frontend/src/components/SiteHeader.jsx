import { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';

const DESTINATIONS = [
  ['/debates', 'Past debates'],
  ['/personas', 'Personas'],
];

const NEW_DEBATE = ['/new', 'New debate'];

/**
 * The persistent top bar.
 *
 * It stays put while a long transcript scrolls, because the way out of a
 * debate shouldn't require scrolling back to the top. It holds only places
 * that exist: the record of past debates, the personas, and a new debate —
 * the one action, so it is the one thing shaped like a button.
 *
 * On a phone the links fold into a menu behind a toggle, leaving one row:
 * the name, the new-debate button, the toggle. The menu opens instantly; the
 * product's motion is spent on the verdict, not on navigation.
 */
export function SiteHeader() {
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const headerRef = useRef(null);
  const toggleRef = useRef(null);

  // Arriving anywhere closes the menu, whichever way you arrived.
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  // While open: Escape closes it and returns focus to the toggle; a tap
  // anywhere outside the header closes it.
  useEffect(() => {
    if (!open) return undefined;

    const onKey = (event) => {
      if (event.key === 'Escape') {
        setOpen(false);
        toggleRef.current?.focus();
      }
    };
    const onPointer = (event) => {
      if (!headerRef.current?.contains(event.target)) setOpen(false);
    };

    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointer);
    };
  }, [open]);

  const current = (path) =>
    pathname === path || pathname.startsWith(`${path}/`) ? 'page' : undefined;

  return (
    <header className="site-header" ref={headerRef}>
      <div className="site-header-inner">
        <Link
          to="/"
          className="site-name display"
          aria-current={pathname === '/' ? 'page' : undefined}
        >
          PersonaArena
        </Link>

        <nav className="site-nav" aria-label="Main">
          {DESTINATIONS.map(([path, label]) => (
            <Link key={path} to={path} className="site-link" aria-current={current(path)}>
              {label}
            </Link>
          ))}
        </nav>

        <Link
          to={NEW_DEBATE[0]}
          className="button site-cta"
          aria-current={current(NEW_DEBATE[0])}
        >
          {NEW_DEBATE[1]}
        </Link>

        <button
          ref={toggleRef}
          type="button"
          className="site-menu-toggle"
          aria-expanded={open}
          aria-controls="site-menu"
          aria-label={open ? 'Close menu' : 'Open menu'}
          onClick={() => setOpen((value) => !value)}
        >
          <span className="menu-icon" data-open={open ? 'true' : undefined} aria-hidden="true" />
        </button>
      </div>

      {open && (
        <nav id="site-menu" className="site-menu" aria-label="Main">
          {[...DESTINATIONS, NEW_DEBATE].map(([path, label]) => (
            <Link
              key={path}
              to={path}
              // New debate is listed only where the bar has no room for it.
              className={path === NEW_DEBATE[0] ? 'site-menu-link site-menu-new' : 'site-menu-link'}
              aria-current={current(path)}
              onClick={() => setOpen(false)}
            >
              {label}
            </Link>
          ))}
        </nav>
      )}
    </header>
  );
}
