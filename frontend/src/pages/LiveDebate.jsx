import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { MessageSquare, Flag, Loader2, Trophy, AlertTriangle } from 'lucide-react';
import { NeoCard, NeoInset } from '../components/ui/NeoCard';
import { NeoButton } from '../components/ui/NeoButton';
import { useSSE } from '../hooks/useSSE';
import { startDebateStream, getDebate } from '../services/api';

export function LiveDebate() {
  const { id } = useParams();
  const navigate = useNavigate();
  const messagesEndRef = useRef(null);
  
  const [debate, setDebate] = useState(null);
  const [messages, setMessages] = useState([]);
  const [currentPhase, setCurrentPhase] = useState('Initializing...');
  const [currentRound, setCurrentRound] = useState(1);
  const [activeParticipant, setActiveParticipant] = useState(null);

  // Auto-scroll
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };
  useEffect(() => scrollToBottom(), [messages, activeParticipant]);

  const { connect, disconnect, status, error } = useSSE(startDebateStream(id), {
    onPhaseStart: (e) => {
      setCurrentPhase(e.phase);
      if (e.round_number) setCurrentRound(e.round_number);
      setActiveParticipant(null);
    },
    onMessage: (e) => {
      setMessages(prev => [...prev, e]);
      setActiveParticipant(null); // Clear "typing" state once message arrives
    },
    onComplete: (e) => {
      // If we got debate_complete event, it might have data
      setTimeout(() => {
        navigate(`/debate/${id}/results`);
      }, 2000);
    }
  });

  useEffect(() => {
    // Initial fetch to get debate details
    getDebate(id).then(res => {
      setDebate(res.data);
      if (res.data.status === 'COMPLETED' || res.data.status === 'JUDGING') {
        navigate(`/debate/${id}/results`);
      } else {
        connect();
      }
    }).catch(err => console.error(err));

    return () => disconnect();
  }, [id, connect, disconnect, navigate]);

  if (!debate) return <div className="container mx-auto p-8 text-center">Loading...</div>;

  return (
    <div className="container mx-auto max-w-5xl h-[calc(100vh-8rem)] flex flex-col animate-in">
      {/* Header Panel */}
      <NeoCard className="mb-6 flex-shrink-0 z-10 relative">
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="neo-badge neo-badge-accent">Round {currentRound} of {debate.round_count}</span>
              <span className="neo-badge neo-badge-warm">{currentPhase}</span>
              {status === 'connecting' && <span className="neo-badge">Connecting...</span>}
              {status === 'completed' && <span className="neo-badge neo-badge-success">Finished</span>}
            </div>
            <h2 className="text-xl font-bold leading-tight mt-2">{debate.topic}</h2>
          </div>
          
          <div className="flex gap-2">
            {debate.participants.map((p, i) => (
              <div key={p.id} className="flex flex-col items-center">
                <div className={`
                  w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm shadow-sm
                  ${i === 0 ? 'bg-[var(--color-accent)] text-white' : 
                    i === 1 ? 'bg-[var(--color-warm)] text-gray-900' : 
                    'bg-[var(--color-info)] text-gray-900'}
                `}>
                  {p.friend_name.substring(0, 2).toUpperCase()}
                </div>
                <span className="text-[10px] mt-1 text-[var(--color-text-muted)] uppercase tracking-wider">{p.position || 'Neutral'}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Progress Bar */}
        <div className="mt-6">
          <div className="score-bar-track h-1.5">
            <div 
              className="score-bar-fill" 
              style={{ width: `${(currentRound / debate.round_count) * 100}%` }}
            ></div>
          </div>
        </div>
      </NeoCard>

      {/* Main Chat Area */}
      <NeoInset className="flex-grow overflow-y-auto p-4 md:p-8 flex flex-col gap-6 relative bg-[rgba(21,21,40,0.7)] backdrop-blur-md border border-[rgba(255,255,255,0.03)]">
        
        {messages.length === 0 && status !== 'error' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-[var(--color-text-muted)] pointer-events-none">
            <Loader2 className="animate-spin mb-4 text-[var(--color-accent-soft)]" size={32} />
            <p>Initializing simulation...</p>
            <p className="text-sm">Agents are preparing their opening statements.</p>
          </div>
        )}

        {error && (
          <div className="bg-[rgba(248,113,113,0.1)] border border-[rgba(248,113,113,0.2)] text-red-400 px-4 py-3 rounded-lg flex items-center gap-3">
            <AlertTriangle size={18} />
            Stream Error: {error}
          </div>
        )}

        {messages.map((msg, i) => {
          // Alternate bubble sides based on participant index
          const pIndex = debate.participants.findIndex(p => p.friend_name === msg.participant_name);
          const isLeft = pIndex % 2 === 0;
          
          return (
            <div key={i} className={`flex flex-col max-w-[85%] animate-fade ${isLeft ? 'self-start' : 'self-end items-end'}`}>
              <div className="flex items-center gap-2 mb-1 px-1">
                <span className="font-semibold text-sm text-[var(--color-text-secondary)]">{msg.participant_name}</span>
                <span className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] bg-[rgba(255,255,255,0.05)] px-2 py-0.5 rounded-full">
                  {msg.phase} • Round {msg.round_number}
                </span>
              </div>
              <div className={`
                p-4 rounded-2xl text-[0.95rem] leading-relaxed shadow-lg border border-[rgba(255,255,255,0.05)]
                ${isLeft 
                  ? 'bg-[var(--color-bg-raised)] rounded-tl-sm' 
                  : 'bg-[rgba(124,91,245,0.15)] rounded-tr-sm'}
              `}>
                {msg.content}
              </div>
            </div>
          );
        })}

        {/* Active Typist Indicator */}
        {status === 'connected' && currentPhase !== 'COMPLETED' && currentPhase !== 'JUDGING' && (
          <div className="self-start flex items-center gap-3 mt-2 px-2 animate-fade">
            <div className="text-sm font-medium text-[var(--color-text-muted)]">
              Generating next response
            </div>
            <div className="typing-dots">
              <span></span><span></span><span></span>
            </div>
          </div>
        )}
        
        {status === 'completed' && (
          <div className="self-center mt-8 mb-4 text-center animate-in">
            <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-[rgba(74,222,128,0.15)] text-[var(--color-success)] mb-3 border border-[rgba(74,222,128,0.3)]">
              <Trophy size={24} />
            </div>
            <h3 className="text-lg font-bold">Debate Concluded</h3>
            <p className="text-[var(--color-text-muted)] text-sm mb-4">The judge is evaluating the arguments...</p>
            <NeoButton variant="primary" onClick={() => navigate(`/debate/${id}/results`)}>
              View Results
            </NeoButton>
          </div>
        )}

        <div ref={messagesEndRef} />
      </NeoInset>
    </div>
  );
}
