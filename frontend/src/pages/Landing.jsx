import React from 'react';
import { Link } from 'react-router-dom';
import { Swords, Users, Sparkles, BrainCircuit } from 'lucide-react';
import { NeoCard, NeoInset } from '../components/ui/NeoCard';
import { NeoButton } from '../components/ui/NeoButton';

export function Landing() {
  return (
    <div className="container mx-auto">
      {/* Hero Section */}
      <section className="min-h-[70vh] flex flex-col items-center justify-center text-center px-4 animate-in">
        <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full neo-inset text-[var(--color-accent-soft)] mb-8 font-medium text-sm border-none">
          <Sparkles size={16} />
          <span>v1.0 is live</span>
        </div>
        
        <h1 className="text-5xl md:text-7xl font-black mb-6 leading-tight max-w-4xl mx-auto">
          AI Debates, starring <br/>
          <span className="text-gradient">Your Friends</span>
        </h1>
        
        <p className="text-xl text-[var(--color-text-secondary)] max-w-2xl mx-auto mb-12">
          PersonaArena uses large language models to simulate debates between AI avatars of your friends based on their real personalities, values, and quirks.
        </p>
        
        <div className="flex flex-col sm:flex-row gap-4 justify-center">
          <Link to="/setup">
            <NeoButton variant="primary" className="w-full sm:w-auto text-lg px-8 py-4" icon={Swords}>
              Start a Debate
            </NeoButton>
          </Link>
          <Link to="/friends">
            <NeoButton className="w-full sm:w-auto text-lg px-8 py-4" icon={Users}>
              Manage Friends
            </NeoButton>
          </Link>
        </div>
      </section>

      {/* Features Section */}
      <section className="py-20 animate-in" style={{ animationDelay: '0.2s' }}>
        <div className="grid md:grid-cols-3 gap-8">
          <NeoCard className="flex flex-col items-center text-center p-8">
            <div className="w-16 h-16 rounded-full neo-inset flex items-center justify-center text-[var(--color-accent-soft)] mb-6">
              <BrainCircuit size={32} />
            </div>
            <h3 className="text-xl mb-3">AI Persona Compiler</h3>
            <p className="text-[var(--color-text-secondary)]">
              Describe your friend in natural language. Our compiler extracts core traits, reasoning style, and debate tactics into a structured JSON profile.
            </p>
          </NeoCard>
          
          <NeoCard className="flex flex-col items-center text-center p-8">
            <div className="w-16 h-16 rounded-full neo-inset flex items-center justify-center text-[var(--color-warm)] mb-6">
              <Swords size={32} />
            </div>
            <h3 className="text-xl mb-3">Deterministic Engine</h3>
            <p className="text-[var(--color-text-secondary)]">
              A 4-round state machine (Opening, Rebuttal, Counter, Closing) ensures structured, logical progression without agent drift.
            </p>
          </NeoCard>

          <NeoCard className="flex flex-col items-center text-center p-8">
            <div className="w-16 h-16 rounded-full neo-inset flex items-center justify-center text-[var(--color-success)] mb-6">
              <Users size={32} />
            </div>
            <h3 className="text-xl mb-3">Independent Judge</h3>
            <p className="text-[var(--color-text-secondary)]">
              Debates are judged blindly. Anonymized transcripts are evaluated on logic, evidence, and persona consistency to determine a winner.
            </p>
          </NeoCard>
        </div>
      </section>
    </div>
  );
}
