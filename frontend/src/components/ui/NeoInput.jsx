import React from 'react';

export const NeoInput = React.forwardRef(({ label, className = '', error, ...props }, ref) => {
  return (
    <div className={`mb-4 ${className}`}>
      {label && <label className="neo-label">{label}</label>}
      <input 
        ref={ref}
        className="neo-input" 
        {...props} 
      />
      {error && <p className="text-red-400 text-sm mt-1 ml-1">{error}</p>}
    </div>
  );
});

NeoInput.displayName = 'NeoInput';

export const NeoTextarea = React.forwardRef(({ label, className = '', error, ...props }, ref) => {
  return (
    <div className={`mb-4 ${className}`}>
      {label && <label className="neo-label">{label}</label>}
      <textarea 
        ref={ref}
        className="neo-input neo-textarea" 
        {...props} 
      />
      {error && <p className="text-red-400 text-sm mt-1 ml-1">{error}</p>}
    </div>
  );
});

NeoTextarea.displayName = 'NeoTextarea';

export const NeoSelect = React.forwardRef(({ label, className = '', children, error, ...props }, ref) => {
  return (
    <div className={`mb-4 ${className}`}>
      {label && <label className="neo-label">{label}</label>}
      <select 
        ref={ref}
        className="neo-input neo-select" 
        {...props}
      >
        {children}
      </select>
      {error && <p className="text-red-400 text-sm mt-1 ml-1">{error}</p>}
    </div>
  );
});

NeoSelect.displayName = 'NeoSelect';
