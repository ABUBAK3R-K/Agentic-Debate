import React from 'react';

export function NeoCard({ children, className = '', flat = false, ...props }) {
  const cardClass = flat ? 'neo-card-flat' : 'neo-card';
  return (
    <div className={`${cardClass} ${className}`} {...props}>
      {children}
    </div>
  );
}

export function NeoInset({ children, className = '', ...props }) {
  return (
    <div className={`neo-inset ${className}`} {...props}>
      {children}
    </div>
  );
}
