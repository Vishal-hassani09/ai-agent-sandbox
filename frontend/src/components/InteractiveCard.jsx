import { useState } from 'react';

export default function InteractiveCard({ card, onSelectOption, onCancel }) {
  const [customText, setCustomText] = useState('');

  if (!card || !card.questions || card.questions.length === 0) {
    return null;
  }

  const { title, questions, currentQIdx = 0, answers = {} } = card;
  const activeQ = questions[currentQIdx] || questions[0];
  const options = activeQ.options || [];

  const handleCustomSubmit = (e) => {
    e.preventDefault();
    if (!customText.trim()) return;
    onSelectOption(customText.trim());
    setCustomText('');
  };

  return (
    <div className="interactive-card" data-testid="interactive-card">
      <div className="card-header">
        <span className="card-title mono">{title}</span>
        <button type="button" onClick={onCancel} className="card-cancel-btn mono">
          Esc / Cancel
        </button>
      </div>

      {questions.length > 1 && (
        <div className="card-tabs">
          {questions.map((q, idx) => {
            const isCurrent = idx === currentQIdx;
            const isAnswered = idx in answers;
            return (
              <span
                key={idx}
                className={`card-tab mono ${isCurrent ? 'card-tab-active' : ''}`}
              >
                {isAnswered ? '✓ ' : ''}
                {q.header || `Q${idx + 1}`}
              </span>
            );
          })}
        </div>
      )}

      <div className="card-body">
        <div className="card-question">{activeQ.question}</div>
        {activeQ.subtitle && (
          <div className="card-subtitle mono">{activeQ.subtitle}</div>
        )}

        <div className="card-options">
          {options.map((opt, idx) => (
            <button
              key={idx}
              type="button"
              onClick={() => onSelectOption(opt)}
              className="card-option-btn mono"
            >
              <span className="opt-number">{idx + 1}.</span> {opt}
            </button>
          ))}
        </div>

        <form onSubmit={handleCustomSubmit} className="card-custom-form">
          <input
            type="text"
            value={customText}
            onChange={(e) => setCustomText(e.target.value)}
            placeholder="✎ Or type custom response / instructions and press Enter..."
            className="card-custom-input mono"
          />
          <button
            type="submit"
            disabled={!customText.trim()}
            className="card-custom-submit mono"
          >
            Submit
          </button>
        </form>
      </div>
    </div>
  );
}