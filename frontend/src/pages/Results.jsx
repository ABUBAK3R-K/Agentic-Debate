import React, { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Trophy, Scale, UserCheck, MessageSquare, AlertTriangle } from 'lucide-react';
import { NeoCard, NeoInset } from '../components/ui/NeoCard';
import { NeoButton } from '../components/ui/NeoButton';
import { getDebateResult } from '../services/api';

export function Results() {
  const { id } = useParams();
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchResult = async () => {
      try {
        const res = await getDebateResult(id);
        setResult(res.data);
      } catch (err) {
        setError(err.response?.data?.detail || 'Failed to load results');
      } finally {
        setLoading(false);
      }
    };
    fetchResult();
  }, [id]);

  if (loading) return <div className="container mx-auto p-8 text-center">Loading evaluation...</div>;

  if (error) {
    return (
      <div className="container mx-auto p-8 max-w-2xl text-center">
        <NeoCard>
          <AlertTriangle className="mx-auto text-red-400 mb-4" size={48} />
          <h2 className="text-xl font-bold mb-4">Error Loading Results</h2>
          <p className="text-[var(--color-text-secondary)] mb-6">{error}</p>
          <Link to="/history"><NeoButton>Back to History</NeoButton></Link>
        </NeoCard>
      </div>
    );
  }

  if (result.status !== 'COMPLETED' || !result.judge_scores) {
    return (
      <div className="container mx-auto p-8 max-w-2xl text-center animate-pulse">
        <h2 className="text-2xl font-bold mb-4">Evaluation in Progress</h2>
        <p className="text-[var(--color-text-secondary)]">The judge is currently analyzing the debate...</p>
      </div>
    );
  }

  const { winner_name, summary, judge_scores, persona_consistency } = result;
  
  // Parse summary text lines (we stored it as a newline separated string)
  const summaryLines = summary.split('\n');
  const reasonLine = summaryLines.find(l => l.startsWith('Reason:'))?.replace('Reason:', '').trim();
  const strongLine = summaryLines.find(l => l.startsWith('Strongest argument:'))?.replace('Strongest argument:', '').trim();
  const weakLine = summaryLines.find(l => l.startsWith('Weakest argument:'))?.replace('Weakest argument:', '').trim();

  // Helper for score bars
  const ScoreBar = ({ label, score, max = 10, color = 'accent' }) => (
    <div className="mb-2">
      <div className="flex justify-between text-xs mb-1">
        <span className="text-[var(--color-text-secondary)] uppercase tracking-wider">{label}</span>
        <span className="font-bold">{score}/{max}</span>
      </div>
      <div className="score-bar-track h-1.5">
        <div 
          className={`score-bar-fill ${color === 'warm' ? 'score-bar-fill-warm' : ''}`} 
          style={{ width: `${(score / max) * 100}%` }}
        ></div>
      </div>
    </div>
  );

  return (
    <div className="container mx-auto max-w-5xl animate-in">
      {/* Winner Banner */}
      <NeoCard className="text-center py-10 mb-8 border-[var(--color-accent-glow)] relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-b from-[rgba(124,91,245,0.1)] to-transparent pointer-events-none"></div>
        <div className="relative z-10">
          <div className="inline-flex items-center justify-center w-20 h-20 rounded-full bg-[var(--color-bg-sunken)] shadow-[var(--shadow-glow)] text-[var(--color-warm)] mb-6 border-2 border-[var(--color-warm-soft)]">
            <Trophy size={40} />
          </div>
          <h1 className="text-4xl font-black mb-2 text-gradient">Winner: {winner_name}</h1>
          <p className="text-lg text-[var(--color-text-secondary)] max-w-2xl mx-auto leading-relaxed mt-4">
            {reasonLine}
          </p>
        </div>
      </NeoCard>

      {/* Key Arguments */}
      <div className="grid md:grid-cols-2 gap-6 mb-8">
        <NeoCard className="border-l-4 border-l-[var(--color-success)]">
          <h3 className="font-bold text-sm uppercase tracking-wider mb-3 text-[var(--color-text-secondary)] flex items-center gap-2">
            <Scale size={16} /> Strongest Argument
          </h3>
          <p className="italic leading-relaxed text-[0.95rem]">"{strongLine}"</p>
        </NeoCard>
        
        <NeoCard className="border-l-4 border-l-[var(--color-danger)]">
          <h3 className="font-bold text-sm uppercase tracking-wider mb-3 text-[var(--color-text-secondary)] flex items-center gap-2">
            <AlertTriangle size={16} /> Weakest Argument
          </h3>
          <p className="italic leading-relaxed text-[0.95rem]">"{weakLine}"</p>
        </NeoCard>
      </div>

      {/* Scorecards */}
      <h2 className="text-2xl font-bold mb-6 flex items-center gap-2">
        <UserCheck className="text-[var(--color-accent-soft)]" /> Scorecards
      </h2>
      
      <div className="grid md:grid-cols-2 gap-8 stagger-children">
        {Object.entries(judge_scores).map(([name, scores]) => {
          const pc = persona_consistency[name] || {};
          const isWinner = name === winner_name;
          
          return (
            <NeoCard key={name} className={`flex flex-col ${isWinner ? 'border-[var(--color-warm-soft)]' : ''}`}>
              <div className="flex justify-between items-center mb-6">
                <h3 className="text-xl font-bold">{name}</h3>
                <div className="text-2xl font-black font-[Space_Grotesk] text-[var(--color-accent-soft)]">
                  {scores.overall.toFixed(1)}<span className="text-sm text-[var(--color-text-muted)]">/10</span>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-x-6 gap-y-4 mb-6">
                <div>
                  <ScoreBar label="Logic" score={scores.logic} />
                  <ScoreBar label="Evidence" score={scores.evidence} />
                  <ScoreBar label="Rebuttal" score={scores.rebuttal} />
                </div>
                <div>
                  <ScoreBar label="Persuasion" score={scores.persuasiveness} />
                  <ScoreBar label="Originality" score={scores.originality} />
                  <ScoreBar label="Consistency" score={scores.persona_consistency} color="warm" />
                </div>
              </div>

              <div className="mt-auto pt-4 border-t border-[rgba(255,255,255,0.05)]">
                <h4 className="text-xs font-bold uppercase tracking-wider text-[var(--color-text-muted)] mb-3">
                  Persona Consistency Detail
                </h4>
                <div className="grid grid-cols-2 gap-4">
                  <div className="text-center p-2 rounded bg-[var(--color-bg-sunken)]">
                    <div className="text-xs text-[var(--color-text-secondary)] mb-1">Reasoning</div>
                    <div className="font-bold">{pc.reasoning_consistency || 0}/10</div>
                  </div>
                  <div className="text-center p-2 rounded bg-[var(--color-bg-sunken)]">
                    <div className="text-xs text-[var(--color-text-secondary)] mb-1">Tone</div>
                    <div className="font-bold">{pc.communication_consistency || 0}/10</div>
                  </div>
                </div>
              </div>
            </NeoCard>
          );
        })}
      </div>

      <div className="mt-12 text-center">
        <Link to="/setup">
          <NeoButton variant="primary" className="px-8 py-3">Start Another Debate</NeoButton>
        </Link>
      </div>
    </div>
  );
}
