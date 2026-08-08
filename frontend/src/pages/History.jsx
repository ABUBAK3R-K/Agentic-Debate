import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { History as HistoryIcon, Swords, ArrowRight } from 'lucide-react';
import { NeoCard } from '../components/ui/NeoCard';
import { NeoButton } from '../components/ui/NeoButton';
import { getDebates } from '../services/api';

export function History() {
  const [debates, setDebates] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getDebates()
      .then(res => setDebates(res.data))
      .catch(err => console.error(err))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="container mx-auto p-8 text-center">Loading history...</div>;

  return (
    <div className="container mx-auto max-w-4xl animate-in">
      <div className="flex items-center gap-3 mb-8">
        <div className="w-12 h-12 rounded-full neo-inset flex items-center justify-center text-[var(--color-accent-soft)]">
          <HistoryIcon size={24} />
        </div>
        <div>
          <h1 className="text-3xl font-bold">Debate History</h1>
          <p className="text-[var(--color-text-secondary)]">Past matches and evaluations.</p>
        </div>
      </div>

      <div className="space-y-4 stagger-children">
        {debates.length === 0 && (
          <div className="text-center py-12 text-[var(--color-text-muted)]">
            No debates run yet. Go start one!
          </div>
        )}
        
        {debates.map(debate => (
          <NeoCard key={debate.id} className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
            <div className="flex-grow">
              <div className="flex items-center gap-2 mb-2">
                <span className={`neo-badge ${debate.status === 'COMPLETED' ? 'neo-badge-success' : 'neo-badge-warm'}`}>
                  {debate.status}
                </span>
                <span className="text-xs text-[var(--color-text-muted)]">
                  {new Date(debate.created_at).toLocaleDateString()}
                </span>
              </div>
              <h3 className="font-bold text-lg mb-1">{debate.topic}</h3>
              <p className="text-sm text-[var(--color-text-secondary)] flex items-center gap-2">
                <Swords size={14} /> {debate.round_count} Rounds • {debate.model_name}
              </p>
            </div>
            
            <Link to={debate.status === 'COMPLETED' || debate.status === 'JUDGING' ? `/debate/${debate.id}/results` : `/debate/${debate.id}`}>
              <NeoButton variant={debate.status === 'COMPLETED' ? 'secondary' : 'primary'} className="whitespace-nowrap">
                {debate.status === 'COMPLETED' ? 'View Results' : 'Resume Debate'} <ArrowRight size={16} />
              </NeoButton>
            </Link>
          </NeoCard>
        ))}
      </div>
    </div>
  );
}
