import { BrowserRouter, Route, Routes } from 'react-router-dom';

import { SiteHeader } from './components/SiteHeader';
import { Landing } from './pages/Landing';
import { LiveDebate } from './pages/LiveDebate';
import { PastDebates } from './pages/PastDebates';
import { Personas } from './pages/Personas';
import { SavedDebate } from './pages/SavedDebate';
import { Setup } from './pages/Setup';
import { Verdict } from './pages/Verdict';
import './screens.css';

/**
 * The landing page, three working screens — build the personas, watch the
 * debate, read the verdict — and the record of what has been run: past
 * debates and the personas behind them.
 */
export default function App() {
  return (
    <BrowserRouter>
      <SiteHeader />
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/new" element={<Setup />} />
        <Route path="/debate/:id" element={<LiveDebate />} />
        <Route path="/debate/:id/verdict" element={<Verdict />} />
        <Route path="/debates" element={<PastDebates />} />
        <Route path="/debates/:id" element={<SavedDebate />} />
        <Route path="/personas" element={<Personas />} />
      </Routes>
    </BrowserRouter>
  );
}
