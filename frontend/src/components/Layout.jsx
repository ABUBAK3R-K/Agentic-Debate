import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Users, Swords, History, Zap } from 'lucide-react';
import { NeoCard } from './ui/NeoCard';

export function Layout({ children }) {
  const location = useLocation();
  
  const navItems = [
    { path: '/friends', label: 'Friends', icon: Users },
    { path: '/setup', label: 'New Debate', icon: Swords },
    { path: '/history', label: 'History', icon: History },
  ];

  return (
    <>
      <nav className="fixed top-0 left-0 right-0 z-50 p-4 animate-in">
        <div className="container mx-auto">
          <NeoCard className="flex items-center justify-between py-3 px-6 glass" flat>
            <Link 
              to="/" 
              className="text-xl font-bold font-[Space_Grotesk] flex items-center gap-2 text-white no-underline hover:opacity-80 transition-opacity"
            >
              <Zap className="text-[var(--color-warm)]" fill="currentColor" />
              <span>Persona<span className="text-[var(--color-accent-soft)]">Arena</span></span>
            </Link>
            
            <div className="flex gap-2">
              {navItems.map(item => {
                const isActive = location.pathname.startsWith(item.path);
                const Icon = item.icon;
                
                return (
                  <Link 
                    key={item.path} 
                    to={item.path}
                    className={`
                      flex items-center gap-2 px-4 py-2 rounded-full font-medium text-sm transition-all
                      ${isActive 
                        ? 'bg-[var(--color-bg-sunken)] text-[var(--color-accent-soft)] shadow-[var(--shadow-neo-in)]' 
                        : 'text-[var(--color-text-secondary)] hover:text-white hover:bg-[var(--color-neo-light)]'
                      }
                    `}
                  >
                    <Icon size={16} />
                    <span className="hidden sm:inline">{item.label}</span>
                  </Link>
                );
              })}
            </div>
          </NeoCard>
        </div>
      </nav>

      <main className="page">
        {children}
      </main>
    </>
  );
}
