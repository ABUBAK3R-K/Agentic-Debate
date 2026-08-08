import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Swords, Users, Play, Loader2 } from 'lucide-react';
import { NeoCard, NeoInset } from '../components/ui/NeoCard';
import { NeoButton } from '../components/ui/NeoButton';
import { NeoInput, NeoTextarea, NeoSelect } from '../components/ui/NeoInput';
import { getFriends, createDebate } from '../services/api';

export function DebateSetup() {
  const navigate = useNavigate();
  const [friends, setFriends] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  // Form state
  const [topic, setTopic] = useState('');
  const [selectedIds, setSelectedIds] = useState([]);
  const [roundCount, setRoundCount] = useState(4);
  const [temperature, setTemperature] = useState(0.8);

  useEffect(() => {
    loadFriends();
  }, []);

  const loadFriends = async () => {
    try {
      const res = await getFriends();
      // Only show friends that have a compiled persona
      const compiled = res.data.filter(f => f.persona != null);
      setFriends(compiled);
    } catch (err) {
      setError('Failed to load friends');
    } finally {
      setLoading(false);
    }
  };

  const toggleFriend = (id) => {
    if (selectedIds.includes(id)) {
      setSelectedIds(selectedIds.filter(fId => fId !== id));
    } else {
      if (selectedIds.length >= 3) {
        alert("Maximum 3 participants allowed");
        return;
      }
      setSelectedIds([...selectedIds, id]);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!topic || selectedIds.length < 2) {
      setError("Please provide a topic and select at least 2 participants.");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const res = await createDebate({
        topic,
        participant_ids: selectedIds,
        round_count: parseInt(roundCount),
        temperature: parseFloat(temperature),
        max_tokens: 500,
        top_p: 1.0,
      });
      // Navigate to the live debate page
      navigate(`/debate/${res.data.id}`);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to create debate');
      setSubmitting(false);
    }
  };

  if (loading) return <div className="container mx-auto p-8 text-center">Loading...</div>;

  return (
    <div className="container mx-auto max-w-4xl animate-in">
      <div className="text-center mb-10">
        <div className="inline-flex items-center justify-center w-16 h-16 rounded-full neo-inset text-[var(--color-accent-soft)] mb-6">
          <Swords size={32} />
        </div>
        <h1 className="text-4xl font-bold mb-4">Configure Match</h1>
        <p className="text-[var(--color-text-secondary)]">Set the parameters and select the combatants.</p>
      </div>

      <NeoCard>
        {error && (
          <div className="bg-[rgba(248,113,113,0.1)] border border-[rgba(248,113,113,0.2)] text-red-400 px-4 py-3 rounded-lg mb-6">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="grid md:grid-cols-3 gap-8">
            <div className="md:col-span-2 space-y-6">
              <NeoTextarea 
                label="Debate Topic" 
                placeholder="e.g. Is a hotdog a sandwich? Defend your position using logical arguments." 
                value={topic}
                onChange={e => setTopic(e.target.value)}
                required
                className="h-32"
              />
              
              <div className="grid grid-cols-2 gap-4">
                <NeoSelect 
                  label="Rounds" 
                  value={roundCount} 
                  onChange={e => setRoundCount(e.target.value)}
                >
                  <option value="2">2 Rounds (Quick)</option>
                  <option value="4">4 Rounds (Standard)</option>
                  <option value="6">6 Rounds (Extended)</option>
                </NeoSelect>

                <NeoInput 
                  label="LLM Temperature (0.2 - 1.2)" 
                  type="number" 
                  step="0.1" 
                  min="0.2" 
                  max="1.2"
                  value={temperature}
                  onChange={e => setTemperature(e.target.value)}
                />
              </div>
            </div>

            <div className="md:col-span-1">
              <label className="neo-label flex justify-between items-center">
                <span>Select Participants (2-3)</span>
                <span className="text-[var(--color-accent-soft)]">{selectedIds.length}/3</span>
              </label>
              
              <NeoInset className="h-[260px] overflow-y-auto space-y-2 p-2">
                {friends.length === 0 ? (
                  <div className="text-center p-4 text-sm text-[var(--color-text-muted)]">
                    No friends with compiled personas found. Go to Friends to compile them first.
                  </div>
                ) : (
                  friends.map(friend => {
                    const isSelected = selectedIds.includes(friend.id);
                    return (
                      <div 
                        key={friend.id}
                        onClick={() => toggleFriend(friend.id)}
                        className={`
                          p-3 rounded-lg cursor-pointer transition-all flex items-center gap-3
                          ${isSelected 
                            ? 'bg-[var(--color-bg-raised)] border border-[var(--color-accent-soft)] shadow-[var(--shadow-glow)]' 
                            : 'bg-transparent border border-transparent hover:bg-[rgba(255,255,255,0.02)]'
                          }
                        `}
                      >
                        <div className={`
                          w-8 h-8 rounded-full flex items-center justify-center text-xs
                          ${isSelected ? 'bg-[var(--color-accent)] text-white' : 'neo-inset text-[var(--color-text-muted)]'}
                        `}>
                          <Users size={14} />
                        </div>
                        <span className={`font-medium text-sm ${isSelected ? 'text-white' : 'text-[var(--color-text-secondary)]'}`}>
                          {friend.name}
                        </span>
                      </div>
                    );
                  })
                )}
              </NeoInset>
            </div>
          </div>

          <div className="pt-8 mt-8 border-t border-[rgba(255,255,255,0.05)] flex justify-end">
            <NeoButton 
              type="submit" 
              variant="primary" 
              className="px-8 py-3 text-lg"
              disabled={submitting || selectedIds.length < 2 || !topic}
              icon={submitting ? Loader2 : Play}
            >
              {submitting ? 'Initializing...' : 'Start Debate Simulation'}
            </NeoButton>
          </div>
        </form>
      </NeoCard>
    </div>
  );
}
