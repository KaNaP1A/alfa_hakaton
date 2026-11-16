import React, { useState } from 'react';

// Keep long material descriptions compact without discarding the original text.
export function CollapsibleText({ text, limit = 320, lines = 4, className = '' }) {
  const [expanded, setExpanded] = useState(false);
  const content = typeof text === 'string' ? text.trim() : '';
  const lengthy = content.length > limit;
  return <div className={`collapsible-text ${className}`}>
    <p className={expanded ? 'description-full' : 'description-clamped'}
       style={expanded ? undefined : { WebkitLineClamp: lines }}>{content || 'Описание отсутствует.'}</p>
    {lengthy && <button type="button" className="description-toggle" aria-expanded={expanded}
      onClick={() => setExpanded(value => !value)}>
      {expanded ? 'Свернуть описание' : 'Показать полностью'}
    </button>}
  </div>;
}
