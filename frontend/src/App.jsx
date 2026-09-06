import { BrowserRouter, Route, Routes } from 'react-router-dom';

import { SiteHeader } from './components/SiteHeader';
import { LiveDebate } from './pages/LiveDebate';
import { Setup } from './pages/Setup';
import { Verdict } from './pages/Verdict';
import './screens.css';

/**
 * Three screens: build the personas, watch the debate, read the verdict.
 * Nothing from the v2 backlog is routed here — it does not exist yet.
 */
export default function App() {
  return (
    <BrowserRouter>
      <SiteHeader />
      <Routes>
        <Route path="/" element={<Setup />} />
        <Route path="/debate/:id" element={<LiveDebate />} />
        <Route path="/debate/:id/verdict" element={<Verdict />} />
      </Routes>
    </BrowserRouter>
  );
}
