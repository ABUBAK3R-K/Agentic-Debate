import React from 'react';

export function NeoButton({ 
  children, 
  variant = 'secondary', 
  className = '', 
  icon: Icon,
  ...props 
}) {
  const variantClass = `neo-button-${variant}`;
  
  return (
    <button className={`neo-button ${variantClass} ${className}`} {...props}>
      {Icon && <Icon size={18} />}
      {children}
    </button>
  );
}
