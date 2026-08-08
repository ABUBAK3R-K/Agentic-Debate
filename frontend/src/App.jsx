import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Layout } from './components/Layout';
import { Landing } from './pages/Landing';
import { Friends } from './pages/Friends';
import { DebateSetup } from './pages/DebateSetup';
import { LiveDebate } from './pages/LiveDebate';
import { Results } from './pages/Results';
import { History } from './pages/History';
import './App.css';

function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/friends" element={<Friends />} />
          <Route path="/setup" element={<DebateSetup />} />
          <Route path="/debate/:id" element={<LiveDebate />} />
          <Route path="/debate/:id/results" element={<Results />} />
          <Route path="/history" element={<History />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}

export default App;
