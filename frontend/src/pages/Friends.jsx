import React, { useState, useEffect } from 'react';
import { Plus, BrainCircuit, User, Loader2, Edit2, Trash2, CheckCircle2 } from 'lucide-react';
import { NeoCard, NeoInset } from '../components/ui/NeoCard';
import { NeoButton } from '../components/ui/NeoButton';
import { NeoInput, NeoTextarea } from '../components/ui/NeoInput';
import { getFriends, createFriend, deleteFriend, compilePersona } from '../services/api';

export function Friends() {
  const [friends, setFriends] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  
  // Form state
  const [isAdding, setIsAdding] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [compilingIds, setCompilingIds] = useState(new Set());

  useEffect(() => {
    loadFriends();
  }, []);

  const loadFriends = async () => {
    try {
      const res = await getFriends();
      setFriends(res.data);
      setError(null);
    } catch (err) {
      setError('Failed to load friends');
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name || !description) return;
    
    setSubmitting(true);
    try {
      await createFriend({ name, raw_description: description });
      setName('');
      setDescription('');
      setIsAdding(false);
      await loadFriends();
    } catch (err) {
      setError('Failed to add friend');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm('Are you sure you want to delete this friend?')) return;
    try {
      await deleteFriend(id);
      await loadFriends();
    } catch (err) {
      setError('Failed to delete friend');
    }
  };

  const handleCompile = async (id) => {
    setCompilingIds(prev => new Set(prev).add(id));
    try {
      await compilePersona(id);
      await loadFriends();
    } catch (err) {
      setError('Failed to compile persona');
    } finally {
      setCompilingIds(prev => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  if (loading) return <div className="container mx-auto p-8 text-center">Loading...</div>;

  return (
    <div className="container mx-auto max-w-5xl animate-in">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-bold mb-2">Friends Registry</h1>
          <p className="text-[var(--color-text-secondary)]">Manage your friends and compile their AI personas.</p>
        </div>
        {!isAdding && (
          <NeoButton variant="primary" icon={Plus} onClick={() => setIsAdding(true)}>
            Add Friend
          </NeoButton>
        )}
      </div>

      {error && (
        <div className="bg-[rgba(248,113,113,0.1)] border border-[rgba(248,113,113,0.2)] text-red-400 px-4 py-3 rounded-lg mb-6">
          {error}
        </div>
      )}

      {isAdding && (
        <NeoCard className="mb-8 animate-fade border-[var(--color-accent-soft)]">
          <h2 className="text-xl font-semibold mb-4">Add New Friend</h2>
          <form onSubmit={handleSubmit}>
            <NeoInput 
              label="Name" 
              placeholder="e.g. Alex" 
              value={name} 
              onChange={e => setName(e.target.value)}
              required 
            />
            <NeoTextarea 
              label="Personality Description" 
              placeholder="Describe their personality, how they argue, their core values, quirks, etc. Be detailed!" 
              value={description} 
              onChange={e => setDescription(e.target.value)}
              required
            />
            <div className="flex gap-3 justify-end mt-6">
              <NeoButton type="button" variant="ghost" onClick={() => setIsAdding(false)}>
                Cancel
              </NeoButton>
              <NeoButton type="submit" variant="primary" disabled={submitting}>
                {submitting ? <Loader2 className="animate-spin" size={18} /> : 'Save Friend'}
              </NeoButton>
            </div>
          </form>
        </NeoCard>
      )}

      <div className="grid md:grid-cols-2 gap-6 stagger-children">
        {friends.length === 0 && !isAdding && (
          <div className="col-span-full text-center py-12 text-[var(--color-text-muted)]">
            No friends added yet. Add someone to get started!
          </div>
        )}
        
        {friends.map(friend => (
          <NeoCard key={friend.id} className="flex flex-col">
            <div className="flex justify-between items-start mb-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full neo-inset flex items-center justify-center text-[var(--color-accent-soft)]">
                  <User size={20} />
                </div>
                <div>
                  <h3 className="font-bold text-lg">{friend.name}</h3>
                  <div className="text-xs text-[var(--color-text-muted)]">
                    Added {new Date(friend.created_at).toLocaleDateString()}
                  </div>
                </div>
              </div>
              <div className="flex gap-2">
                <button onClick={() => handleDelete(friend.id)} className="text-[var(--color-text-muted)] hover:text-red-400 transition-colors p-1">
                  <Trash2 size={16} />
                </button>
              </div>
            </div>
            
            <NeoInset className="flex-grow mb-4 opacity-80 text-sm">
              <p className="line-clamp-3 leading-relaxed">{friend.raw_description}</p>
            </NeoInset>

            <div className="pt-4 border-t border-[rgba(255,255,255,0.05)] mt-auto flex justify-between items-center">
              {friend.persona ? (
                <div className="flex items-center gap-2 text-[var(--color-success)] text-sm font-medium">
                  <CheckCircle2 size={16} />
                  Persona Compiled (v{friend.persona.version || 1})
                </div>
              ) : (
                <div className="text-[var(--color-text-muted)] text-sm">
                  No persona generated
                </div>
              )}
              
              <NeoButton 
                variant={friend.persona ? 'secondary' : 'primary'} 
                className="text-xs py-1.5 px-3"
                onClick={() => handleCompile(friend.id)}
                disabled={compilingIds.has(friend.id)}
              >
                {compilingIds.has(friend.id) ? (
                  <><Loader2 size={14} className="animate-spin" /> Compiling...</>
                ) : (
                  <><BrainCircuit size={14} /> {friend.persona ? 'Recompile' : 'Compile Persona'}</>
                )}
              </NeoButton>
            </div>
          </NeoCard>
        ))}
      </div>
    </div>
  );
}
