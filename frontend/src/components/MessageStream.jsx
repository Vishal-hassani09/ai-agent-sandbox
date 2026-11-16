import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import InteractiveCard from './InteractiveCard';

export default function MessageStream({
  messages,
  onToggleExpand,
  activeCard,
  onSelectCardOption,
  onCancelCard,
  onCancelTurn,
  messagesEndRef,
}) {
  return (
    <div className="claude-chat-scroll">
      <div className="claude-chat-container">
        {messages.map((item, idx) => {
          if (item.kind === 'user') {
            return (
              <div key={idx} className="chat-row-user">
                <div className="user-dialogue-bubble">
                  <div className="user-bubble-text">{item.content}</div>
                  {item.attachment && (
                    <div className="user-bubble-attachment">
                      <button
                        type="button"
                        onClick={() => onToggleExpand(idx)}
                        className="attachment-toggle-pill mono"
                      >
                        {item.isExpanded ? '▼' : '▶'} Attached context
                      </button>
                      {item.isExpanded && (
                        <pre className="attachment-pre mono">
                          {item.attachment.trim()}
                        </pre>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          }

          if (item.kind === 'agent') {
            return (
              <div key={idx} className="chat-row-assistant">
                <div className="assistant-avatar-badge" title="AI Coder">
                  ✦
                </div>
                <div className="assistant-dialogue-card">
                  <div className="claude-markdown">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {item.content || ''}
                    </ReactMarkdown>
                  </div>
                </div>
              </div>
            );
          }

          if (item.kind === 'compacted_summary') {
            return (
              <div key={idx} className="chat-row-system">
                <div className="compacted-dialogue-box">
                  <div className="compacted-label mono">
                    🗜 Context Summary
                  </div>
                  <div className="claude-markdown">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {item.content || ''}
                    </ReactMarkdown>
                  </div>
                </div>
              </div>
            );
          }

          if (item.kind === 'tool_action') {
            return (
              <div key={idx} className="chat-row-tool">
                <button
                  type="button"
                  onClick={() => onToggleExpand(idx)}
                  className="tool-execution-pill mono"
                >
                  <span className="tool-chevron">
                    {item.isExpanded ? '▼' : '▶'}
                  </span>
                  <span>⚙ {item.summary}</span>
                </button>
                {item.isExpanded && item.details && (
                  <pre className="tool-output-drawer mono">
                    {item.details.trim()}
                  </pre>
                )}
              </div>
            );
          }

          if (item.kind === 'thinking') {
            return (
              <div key={idx} className="chat-row-assistant">
                <div className="assistant-avatar-badge thinking-pulse">✦</div>
                <div className="thinking-dialogue-pill mono">
                  <span>Thinking &amp; running tools...</span>
                  <button
                    type="button"
                    onClick={onCancelTurn}
                    className="stop-turn-btn"
                  >
                    Stop
                  </button>
                </div>
              </div>
            );
          }

          if (item.kind === 'cancelled') {
            return (
              <div key={idx} className="chat-row-system">
                <span className="cancelled-pill mono">⊘ Turn stopped</span>
              </div>
            );
          }

          if (item.kind === 'error') {
            return (
              <div key={idx} className="chat-row-system">
                <div className="error-dialogue-box mono">
                  ✖ {item.content}
                </div>
              </div>
            );
          }

          return null;
        })}

        {activeCard && (
          <InteractiveCard
            card={activeCard}
            onSelectOption={onSelectCardOption}
            onCancel={onCancelCard}
          />
        )}

        <div ref={messagesEndRef} />
      </div>
    </div>
  );
}