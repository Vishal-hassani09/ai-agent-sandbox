import { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const INITIAL_MESSAGE = {
  role: 'assistant',
  content: 'Hello! Type `@` to reference files, or ask me to inspect, run, and modify code.',
};

export default function App() {
  const [workspace, setWorkspace] = useState('workspace');
  const [availableWorkspaces, setAvailableWorkspaces] = useState(['workspace']);
  const [messages, setMessages] = useState([INITIAL_MESSAGE]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);

  // File picker state
  const [files, setFiles] = useState([]);
  const [fileSuggestions, setFileSuggestions] = useState([]);
  const [showPicker, setShowPicker] = useState(false);
  const [selectedPickerIdx, setSelectedPickerIdx] = useState(0);

  const inputRef = useRef(null);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    if (!loading) {
      inputRef.current?.focus();
    }
  }, [loading]);

  // Fetch workspaces on boot
  useEffect(() => {
    fetch('/api/workspaces')
      .then((res) => (res.ok ? res.json() : { workspaces: ['workspace'] }))
      .then((data) => {
        if (data.workspaces?.length > 0) {
          setAvailableWorkspaces(data.workspaces);
          setWorkspace(data.workspaces[0]);
        }
      })
      .catch(() => { });
  }, []);

  // Refresh workspace files whenever workspace changes
  useEffect(() => {
    if (!workspace) return;
    fetch(`/api/workspace/files?workspace=${encodeURIComponent(workspace)}`)
      .then((res) => (res.ok ? res.json() : { files: [] }))
      .then((data) => setFiles(data.files || []))
      .catch(() => setFiles([]));
  }, [workspace]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  // Handle typing & detect '@'
  const handleInputChange = (e) => {
    const val = e.target.value;
    setInput(val);

    const cursorPos = e.target.selectionStart;
    const textBeforeCursor = val.slice(0, cursorPos);
    const atMatch = textBeforeCursor.match(/@([a-zA-Z0-9_\-./]*)$/);

    if (atMatch) {
      const query = atMatch[1].toLowerCase();
      const filtered = files.filter((f) => f.toLowerCase().includes(query));
      setFileSuggestions(filtered);
      setShowPicker(filtered.length > 0);
      setSelectedPickerIdx(0);
    } else {
      setShowPicker(false);
    }
  };

  // Insert selected file into input text
  const selectFile = (filename) => {
    const cursorPos = inputRef.current.selectionStart;
    const textBeforeCursor = input.slice(0, cursorPos);
    const textAfterCursor = input.slice(cursorPos);
    const atIndex = textBeforeCursor.lastIndexOf('@');

    const nextText =
      textBeforeCursor.slice(0, atIndex) + `@${filename} ` + textAfterCursor;
    setInput(nextText);
    setShowPicker(false);
    inputRef.current.focus();
  };

  // Keyboard navigation for '@' popup
  const handleKeyDown = (e) => {
    if (!showPicker) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedPickerIdx((prev) => (prev + 1) % fileSuggestions.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedPickerIdx((prev) =>
        prev === 0 ? fileSuggestions.length - 1 : prev - 1
      );
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault();
      if (fileSuggestions[selectedPickerIdx]) {
        selectFile(fileSuggestions[selectedPickerIdx]);
      }
    } else if (e.key === 'Escape') {
      setShowPicker(false);
    }
  };

  // Clear conversation state
  const handleClear = () => {
    setMessages([INITIAL_MESSAGE]);
  };

  const handleSend = async (e) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userMessage = { role: 'user', content: input };
    const updatedHistory = [...messages, userMessage];

    setMessages(updatedHistory);
    setInput('');
    setShowPicker(false);
    setLoading(true);

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace: workspace.trim() || 'workspace',
          messages: updatedHistory,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Server returned ${response.status}`);
      }

      const data = await response.json();
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: data.response },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `⚠️ Error: ${err.message}` },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={styles.container}>
      {/* Top Header */}
      <header style={styles.header}>
        <div style={styles.titleSection}>
          <h2 style={styles.title}>Autonomous Coding Agent</h2>
          <span style={styles.statusBadge}>Active</span>
        </div>

        <div style={styles.controlsGroup}>
          <div style={styles.workspaceControls}>
            <label style={styles.label}>Workspace:</label>
            <input
              type="text"
              value={workspace}
              onChange={(e) => setWorkspace(e.target.value)}
              style={styles.workspaceInput}
            />
            {availableWorkspaces.length > 0 && (
              <select
                onChange={(e) => setWorkspace(e.target.value)}
                value={workspace}
                style={styles.dropdown}
              >
                {availableWorkspaces.map((ws) => (
                  <option key={ws} value={ws}>
                    {ws}
                  </option>
                ))}
              </select>
            )}
          </div>

          <button onClick={handleClear} style={styles.clearBtn} title="Clear conversation history">
            Clear
          </button>
        </div>
      </header>

      {/* Messages */}
      <div style={styles.messageList}>
        {messages.map((msg, index) => {
          const isUser = msg.role === 'user';
          return (
            <div
              key={index}
              style={{
                ...styles.messageWrapper,
                justifyContent: isUser ? 'flex-end' : 'flex-start',
              }}
            >
              <div
                style={{
                  ...styles.messageBubble,
                  backgroundColor: isUser ? '#1d4ed8' : '#111827',
                  borderColor: isUser ? '#2563eb' : '#1f2937',
                  maxWidth: isUser ? '65%' : '82%',
                  borderTopRightRadius: isUser ? '2px' : '8px',
                  borderTopLeftRadius: !isUser ? '2px' : '8px',
                }}
              >
                <div
                  style={{
                    ...styles.senderLabel,
                    textAlign: isUser ? 'right' : 'left',
                    color: isUser ? '#bfdbfe' : '#9ca3af',
                  }}
                >
                  {isUser ? 'You' : 'Agent'}
                </div>
                <div style={styles.messageContent}>
                  {isUser ? (
                    msg.content
                  ) : (
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        table: ({ children }) => (
                          <div style={styles.tableContainer}>
                            <table style={styles.table}>{children}</table>
                          </div>
                        ),
                        thead: ({ children }) => <thead style={styles.thead}>{children}</thead>,
                        tbody: ({ children }) => <tbody>{children}</tbody>,
                        tr: ({ children }) => <tr style={styles.tr}>{children}</tr>,
                        th: ({ children }) => <th style={styles.th}>{children}</th>,
                        td: ({ children }) => <td style={styles.td}>{children}</td>,
                        code({ children, ...props }) {
                          const content = String(children).replace(/\n$/, '');
                          const isMultiLine = content.includes('\n');
                          return !isMultiLine ? (
                            <code style={styles.inlineCode} {...props}>
                              {content}
                            </code>
                          ) : (
                            <pre style={styles.codeBlock}>
                              <code>{content}</code>
                            </pre>
                          );
                        },
                        p: ({ children }) => <p style={styles.mdP}>{children}</p>,
                        ul: ({ children }) => <ul style={styles.mdUl}>{children}</ul>,
                        ol: ({ children }) => <ol style={styles.mdOl}>{children}</ol>,
                        li: ({ children }) => <li style={styles.mdLi}>{children}</li>,
                      }}
                    >
                      {msg.content}
                    </ReactMarkdown>
                  )}
                </div>
              </div>
            </div>
          );
        })}

        {loading && (
          <div style={styles.loadingWrapper}>
            <span style={styles.loadingText}>Agent working in <code>/{workspace}</code>...</span>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Section & File Picker Overlay */}
      <div style={styles.inputArea}>
        {showPicker && (
          <div style={styles.pickerPopup}>
            <div style={styles.pickerHeader}>Files in /{workspace}</div>
            {fileSuggestions.map((file, idx) => (
              <div
                key={file}
                onClick={() => selectFile(file)}
                style={{
                  ...styles.pickerItem,
                  backgroundColor: idx === selectedPickerIdx ? '#334155' : 'transparent',
                }}
              >
                📄 {file}
              </div>
            ))}
          </div>
        )}

        <form onSubmit={handleSend} style={styles.inputContainer}>
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            placeholder={`Type a prompt, or '@' to reference files in /${workspace}...`}
            style={styles.input}
            disabled={loading}
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            style={{
              ...styles.button,
              opacity: loading || !input.trim() ? 0.6 : 1,
            }}
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100vh',
    width: '100vw',
    backgroundColor: '#0b0f19',
    color: '#e2e8f0',
    textAlign: 'left',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  },
  header: {
    padding: '12px 24px',
    backgroundColor: '#111827',
    borderBottom: '1px solid #1f2937',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    flexShrink: 0,
  },
  titleSection: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
  },
  title: {
    margin: 0,
    fontSize: '1rem',
    fontWeight: '700',
    letterSpacing: '-0.025em',
    color: '#f9fafb',
    fontFamily: 'monospace',
  },
  statusBadge: {
    fontSize: '0.75rem',
    color: '#10b981',
    backgroundColor: 'rgba(16, 185, 129, 0.1)',
    padding: '2px 8px',
    borderRadius: '4px',
    border: '1px solid rgba(16, 185, 129, 0.25)',
  },
  controlsGroup: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
  },
  workspaceControls: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  label: {
    color: '#9ca3af',
    fontSize: '0.8rem',
  },
  workspaceInput: {
    backgroundColor: '#1f2937',
    border: '1px solid #374151',
    borderRadius: '4px',
    color: '#f9fafb',
    padding: '4px 8px',
    fontSize: '0.8rem',
    width: '130px',
    fontFamily: 'monospace',
    outline: 'none',
  },
  dropdown: {
    backgroundColor: '#1f2937',
    border: '1px solid #374151',
    borderRadius: '4px',
    color: '#9ca3af',
    padding: '4px 8px',
    fontSize: '0.8rem',
    outline: 'none',
  },
  clearBtn: {
    backgroundColor: '#1f2937',
    color: '#9ca3af',
    border: '1px solid #374151',
    borderRadius: '4px',
    padding: '4px 10px',
    fontSize: '0.8rem',
    cursor: 'pointer',
    fontWeight: '500',
  },
  messageList: {
    flex: 1,
    overflowY: 'auto',
    padding: '24px 32px',
    display: 'flex',
    flexDirection: 'column',
    gap: '20px',
    width: '100%',
    margin: 0,
  },
  messageWrapper: {
    display: 'flex',
    width: '100%',
    padding: '0 8px',
  },
  messageBubble: {
    width: 'fit-content',
    padding: '14px 18px',
    borderRadius: '10px',
    border: '1px solid #1f2937',
    textAlign: 'left',
    boxShadow: '0 2px 8px rgba(0, 0, 0, 0.3)',
  },
  senderLabel: {
    fontSize: '0.72rem',
    fontWeight: '700',
    letterSpacing: '0.05em',
    textTransform: 'uppercase',
    marginBottom: '8px',
  },
  messageContent: {
    textAlign: 'left',
    lineHeight: '1.65',
    fontSize: '0.92rem',
    color: '#e5e7eb',
    wordBreak: 'break-word',
  },

  /* Markdown Typography & Structure */
  mdH1: {
    fontSize: '1.25rem',
    fontWeight: '700',
    color: '#f9fafb',
    margin: '16px 0 8px 0',
    borderBottom: '1px solid #374151',
    paddingBottom: '4px',
    textAlign: 'left',
  },
  mdH2: {
    fontSize: '1.1rem',
    fontWeight: '600',
    color: '#f3f4f6',
    margin: '14px 0 6px 0',
    textAlign: 'left',
  },
  mdH3: {
    fontSize: '0.98rem',
    fontWeight: '600',
    color: '#e5e7eb',
    margin: '12px 0 4px 0',
    textAlign: 'left',
  },
  mdP: {
    margin: '0 0 10px 0',
    lineHeight: '1.6',
    textAlign: 'left',
  },
  mdUl: {
    margin: '0 0 10px 0',
    paddingLeft: '22px',
    textAlign: 'left',
  },
  mdOl: {
    margin: '0 0 10px 0',
    paddingLeft: '22px',
    textAlign: 'left',
  },
  mdLi: {
    marginBottom: '6px',
    lineHeight: '1.5',
    textAlign: 'left',
  },
  blockquote: {
    borderLeft: '3px solid #3b82f6',
    paddingLeft: '12px',
    margin: '8px 0',
    color: '#9ca3af',
    textAlign: 'left',
  },

  /* Tables */
  tableContainer: {
    width: '100%',
    overflowX: 'auto',
    margin: '14px 0',
    borderRadius: '6px',
    border: '1px solid #374151',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: '0.86rem',
    textAlign: 'left',
    backgroundColor: '#0b0f19',
  },
  thead: {
    backgroundColor: '#1f2937',
  },
  th: {
    padding: '10px 14px',
    fontWeight: '600',
    color: '#93c5fd',
    borderBottom: '2px solid #374151',
    borderRight: '1px solid #1f2937',
    whiteSpace: 'nowrap',
    textAlign: 'left',
  },
  tr: {
    borderBottom: '1px solid #1e293b',
  },
  td: {
    padding: '10px 14px',
    verticalAlign: 'top',
    color: '#e2e8f0',
    borderRight: '1px solid #1e293b',
    lineHeight: '1.5',
    textAlign: 'left',
  },

  /* Code & Syntax */
  codeBlockWrapper: {
    borderRadius: '6px',
    overflow: 'hidden',
    border: '1px solid #1f2937',
    margin: '12px 0',
    backgroundColor: '#030712',
    textAlign: 'left',
  },
  codeHeader: {
    backgroundColor: '#111827',
    padding: '4px 12px',
    fontSize: '0.72rem',
    color: '#6b7280',
    fontFamily: 'monospace',
    borderBottom: '1px solid #1f2937',
  },
  codeBlock: {
    padding: '12px 16px',
    overflowX: 'auto',
    fontSize: '0.85rem',
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
    color: '#e5e7eb',
    margin: 0,
    textAlign: 'left',
  },
  inlineCode: {
    backgroundColor: '#1e293b',
    color: '#60a5fa',
    padding: '2px 6px',
    borderRadius: '4px',
    fontSize: '0.84rem',
    fontFamily: 'ui-monospace, monospace',
    display: 'inline',
  },

  /* Footer & Input */
  loadingWrapper: {
    alignSelf: 'flex-start',
    padding: '8px 16px',
  },
  loadingText: {
    fontSize: '0.82rem',
    color: '#9ca3af',
    fontFamily: 'monospace',
  },
  inputArea: {
    position: 'relative',
    backgroundColor: '#111827',
    borderTop: '1px solid #1f2937',
    width: '100%',
    padding: '0 16px',
    margin: 0,
    flexShrink: 0,
  },
  pickerPopup: {
    position: 'absolute',
    bottom: '100%',
    left: '16px',
    right: '16px',
    maxHeight: '180px',
    overflowY: 'auto',
    backgroundColor: '#111827',
    border: '1px solid #374151',
    borderRadius: '6px 6px 0 0',
    boxShadow: '0 -4px 12px rgba(0, 0, 0, 0.4)',
    zIndex: 10,
  },
  pickerHeader: {
    padding: '6px 12px',
    fontSize: '0.72rem',
    color: '#9ca3af',
    borderBottom: '1px solid #374151',
    fontFamily: 'monospace',
  },
  pickerItem: {
    padding: '6px 12px',
    fontSize: '0.82rem',
    color: '#f9fafb',
    cursor: 'pointer',
    fontFamily: 'monospace',
  },
  inputContainer: {
    display: 'flex',
    padding: '12px 16px',
    gap: '10px',
  },
  input: {
    flex: 1,
    padding: '10px 14px',
    borderRadius: '6px',
    border: '1px solid #374151',
    backgroundColor: '#030712',
    color: '#f9fafb',
    outline: 'none',
    fontSize: '0.9rem',
    fontFamily: 'inherit',
  },
  button: {
    padding: '10px 18px',
    borderRadius: '6px',
    backgroundColor: '#2563eb',
    color: '#ffffff',
    border: 'none',
    fontWeight: '600',
    cursor: 'pointer',
    fontSize: '0.85rem',
  },
};