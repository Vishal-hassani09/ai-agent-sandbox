import { useState, useRef, useEffect } from 'react';
import './App.css';
import {
  apiClient,
  getStoredAuth,
  setStoredAuth,
  clearStoredAuth,
} from './api/client';
import AuthModal from './components/AuthModal';
import Sidebar from './components/Sidebar';
import FilesDrawer from './components/FilesDrawer';
import MessageStream from './components/MessageStream';

const SAFE_READ_ONLY_TOOLS = new Set([
  'readfile',
  'read',
  'viewfile',
  'cat',
  'listdirectory',
  'listdir',
  'listfiles',
  'ls',
  'dir',
  'glob',
  'globsearch',
  'globfiles',
  'find',
  'filesearch',
  'memoryprobe',
]);

const SLASH_COMMANDS = [
  { cmd: '/init', desc: 'Generate or update AGENTS.md workspace memory' },
  { cmd: '/memory', desc: 'View active AGENTS.md workspace memory' },
  { cmd: '/compact', desc: 'Summarize older turns to free context' },
  { cmd: '/clear', desc: 'Clear all messages from UI and session DB' },
  { cmd: '/new', desc: 'Start a fresh session in current workspace' },
];

function normalizeToolName(name) {
  return (name || '').toLowerCase().replace(/[_.-]/g, '');
}

export default function App() {
  const [auth, setAuth] = useState(() => getStoredAuth());

  const [workspace, setWorkspace] = useState(
    () => localStorage.getItem('ai_coder_workspace') || ''
  );
  const [availableWorkspaces, setAvailableWorkspaces] = useState([]);
  const [daemonStatus, setDaemonStatus] = useState({ connected: false, cwd: '' });
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [files, setFiles] = useState([]);

  // Panel visibility states (both sidebars independently collapsible like Claude)
  const [leftSidebarOpen, setLeftSidebarOpen] = useState(true);
  const [rightFilesOpen, setRightFilesOpen] = useState(false);

  // Bottom workspace switcher & folder browser state
  const [wsMenuOpen, setWsMenuOpen] = useState(false);
  const [browserOpen, setBrowserOpen] = useState(false);
  const [browsePath, setBrowsePath] = useState('');
  const [parentPath, setParentPath] = useState(null);
  const [subFolders, setSubFolders] = useState([]);
  const [browseLoading, setBrowseLoading] = useState(false);

  const [input, setInput] = useState('');
  const [isTurnRunning, setIsTurnRunning] = useState(false);
  const [activeCard, setActiveCard] = useState(null);
  const [sessionApprovedTools, setSessionApprovedTools] = useState(new Set());
  const [popupItems, setPopupItems] = useState([]);
  const [popupType, setPopupType] = useState(null);
  const [selectedPopupIdx, setSelectedPopupIdx] = useState(0);

  const wsRef = useRef(null);
  const inputRef = useRef(null);
  const messagesEndRef = useRef(null);
  const approvedToolsRef = useRef(sessionApprovedTools);

  useEffect(() => {
    approvedToolsRef.current = sessionApprovedTools;
  }, [sessionApprovedTools]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, activeCard, isTurnRunning]);

  // Capture ?bridge_id= immediately on page load before auth redirects or URL changes
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const bridgeIdFromUrl = params.get('bridge_id');
    if (bridgeIdFromUrl) {
      sessionStorage.setItem('ai_coder_bridge_id', bridgeIdFromUrl);
      params.delete('bridge_id');
      const cleanQuery = params.toString();
      window.history.replaceState(
        {},
        '',
        window.location.pathname + (cleanQuery ? `?${cleanQuery}` : '')
      );
    }
  }, []);

  // Poll local device bridge status & claim pending bridge_id once authenticated
  useEffect(() => {
    if (!auth.token) return;
    let cancelled = false;

    async function checkDaemon() {
      const pendingBridgeId = sessionStorage.getItem('ai_coder_bridge_id');
      let status;

      if (pendingBridgeId) {
        sessionStorage.removeItem('ai_coder_bridge_id');
        status = await apiClient.claimDaemonBridge(pendingBridgeId);
      } else {
        status = await apiClient.getDaemonStatus();
      }

      if (cancelled) return;
      setDaemonStatus(status || { connected: false, cwd: '' });
      if (status?.connected && status?.cwd && !workspace) {
        setWorkspace(status.cwd);
      }
    }

    checkDaemon();
    const timer = setInterval(checkDaemon, 5000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [auth.token]);

  // Load workspaces, files, and sessions whenever workspace or daemon changes
  useEffect(() => {
    if (!auth.token) return;
    loadWorkspacesAndSessions();
  }, [auth.token, workspace, daemonStatus.connected]);

  useEffect(() => {
    if (!auth.token || !activeSessionId) return;
    setSessionApprovedTools(new Set());
    loadSessionMessages(activeSessionId);
  }, [auth.token, activeSessionId]);

  async function loadWorkspacesAndSessions() {
    try {
      const srvWs = await apiClient.listServerWorkspaces();
      const activeWs = workspace || srvWs[0] || 'workspace';
      if (!workspace && activeWs) {
        setWorkspace(activeWs);
        return;
      }

      localStorage.setItem('ai_coder_workspace', activeWs);
      const [wsFiles, sessList] = await Promise.all([
        apiClient.listWorkspaceFiles(activeWs),
        apiClient.listSessions(activeWs),
      ]);

      const mergedWs = Array.from(new Set([activeWs, ...srvWs].filter(Boolean)));
      setAvailableWorkspaces(mergedWs);
      setFiles(wsFiles || []);
      setSessions(sessList || []);

      if (sessList && sessList.length > 0) {
        if (!activeSessionId || !sessList.some((s) => s.id === activeSessionId)) {
          setActiveSessionId(sessList[0].id);
        }
      } else {
        await handleCreateNewSession(activeWs);
      }
    } catch (err) {
      if (err.status === 401) {
        handleLogout();
      }
    }
  }

  async function loadSessionMessages(sessionId) {
    try {
      const detail = await apiClient.getSessionDetail(sessionId);
      const blocks = [];
      for (const msg of detail.messages || []) {
        const role = msg.role;
        const raw = msg.content || '';

        if (role === 'user') {
          let clean = raw;
          let attachment = '';
          if (raw.includes('\n--- Attached File:')) {
            const splitIdx = raw.indexOf('\n--- Attached File:');
            clean = raw.slice(0, splitIdx).trim();
            attachment = raw.slice(splitIdx + 1);
          }
          blocks.push({
            kind: 'user',
            content: clean,
            attachment,
            isExpanded: false,
          });
        } else if (role === 'assistant' || role === 'agent') {
          blocks.push({ kind: 'agent', content: raw });
        } else if (
          role === 'system' &&
          raw.startsWith('[Compacted Conversation Summary]:')
        ) {
          blocks.push({
            kind: 'compacted_summary',
            content: raw.replace('[Compacted Conversation Summary]:', '').trim(),
          });
        } else if (role === 'tool') {
          const lineCount = raw.split('\n').length;
          blocks.push({
            kind: 'tool_action',
            summary: `Tool Output (${lineCount} lines)`,
            details: raw,
            isExpanded: false,
          });
        }
      }
      setMessages(blocks);
    } catch (err) {
      setMessages([
        {
          kind: 'error',
          content: `Could not load session history: ${err.message}`,
        },
      ]);
    }
  }

  async function handleCreateNewSession(targetWs = null) {
    const wsToUse = targetWs || workspace || 'workspace';
    try {
      setSessionApprovedTools(new Set());
      const created = await apiClient.createSession(wsToUse, 'New session');
      const sessList = await apiClient.listSessions(wsToUse);
      setSessions(sessList || [created]);
      setActiveSessionId(created.id);
      setMessages([]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { kind: 'error', content: `Failed to create session: ${err.message}` },
      ]);
    }
  }

  async function openFolderBrowser(startPath = '') {
    setWsMenuOpen(false);
    setBrowserOpen(true);
    setBrowseLoading(true);
    try {
      const data = await apiClient.browseFolders(startPath || workspace || '');
      setBrowsePath(data.current_path || '');
      setParentPath(data.parent_path || null);
      setSubFolders(data.folders || []);
    } catch {
      setSubFolders([]);
    } finally {
      setBrowseLoading(false);
    }
  }

  function handleAuthSuccess(tokenData) {
    setStoredAuth(tokenData);
    setAuth({
      token: tokenData.access_token,
      email: tokenData.email,
      userId: tokenData.user_id,
    });
  }

  function handleLogout() {
    clearStoredAuth();
    setAuth({ token: '', email: '', userId: '' });
    setSessions([]);
    setActiveSessionId(null);
    setMessages([]);
  }

  function presentInteractiveCard(title, questions) {
    return new Promise((resolve) => {
      setActiveCard({
        title,
        questions,
        currentQIdx: 0,
        answers: {},
        resolve,
      });
    });
  }

  async function requestToolApproval(toolName, toolArgs) {
    const norm = normalizeToolName(toolName);
    if (SAFE_READ_ONLY_TOOLS.has(norm) || approvedToolsRef.current.has(norm)) {
      return { approved: true, customReply: '' };
    }

    const preview = JSON.stringify(toolArgs);
    const questions = [
      {
        header: 'Permission',
        question: `Allow execution of ${toolName} on your local machine?`,
        subtitle: `Args: ${
          preview.length > 100 ? preview.slice(0, 97) + '...' : preview
        }`,
        options: [
          'Allow once',
          `Always allow '${toolName}' during this session`,
          'Deny',
        ],
      },
    ];

    const answers = await presentInteractiveCard(
      `⚠ Tool Permission: ${toolName}`,
      questions
    );
    if (!answers) {
      return {
        approved: false,
        customReply: `User cancelled or denied execution of '${toolName}'.`,
      };
    }

    const choice = answers[0] || 'Deny';
    if (choice === 'Allow once') return { approved: true, customReply: '' };
    if (choice.startsWith('Always allow')) {
      const next = new Set(approvedToolsRef.current);
      next.add(norm);
      setSessionApprovedTools(next);
      return { approved: true, customReply: '' };
    }
    if (choice === 'Deny') {
      return {
        approved: false,
        customReply: `User denied permission to execute '${toolName}'.`,
      };
    }
    return {
      approved: false,
      customReply: `User declined '${toolName}' with custom instructions: ${choice}`,
    };
  }

  async function handleAskUserTool(toolArgs) {
    let rawQuestions = toolArgs.questions || [];
    if (!rawQuestions.length) {
      rawQuestions = [
        {
          header: 'Question',
          question: toolArgs.question || 'Please provide your input:',
          options: toolArgs.options || ['Yes', 'No'],
        },
      ];
    }
    const answers = await presentInteractiveCard(
      'Clarifying Questions',
      rawQuestions
    );
    if (!answers) return 'User cancelled the question prompt.';
    const lines = ['User responses:'];
    rawQuestions.forEach((q, idx) => {
      lines.push(
        `- ${q.header || q.question || `Question ${idx + 1}`}: ${
          answers[idx] || '(no response)'
        }`
      );
    });
    return lines.join('\n');
  }

  function handleSelectCardOption(chosenValue) {
    if (!activeCard) return;
    const { questions, currentQIdx, answers, resolve } = activeCard;
    const nextAnswers = { ...answers, [currentQIdx]: chosenValue };

    if (
      questions.length > 1 &&
      Object.keys(nextAnswers).length < questions.length
    ) {
      let nextIdx = currentQIdx;
      for (let i = 0; i < questions.length; i++) {
        if (!(i in nextAnswers)) {
          nextIdx = i;
          break;
        }
      }
      setActiveCard({
        ...activeCard,
        answers: nextAnswers,
        currentQIdx: nextIdx,
      });
      return;
    }

    setActiveCard(null);
    resolve(nextAnswers);
  }

  function handleCancelCard() {
    if (activeCard?.resolve) {
      activeCard.resolve(null);
    }
    setActiveCard(null);
  }

  function handleCancelTurn() {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'cancel_turn' }));
    }
    handleCancelCard();
  }

  function sendWsSessionCommand(type) {
    if (!activeSessionId) return;
    const ws = new WebSocket(apiClient.getWebSocketUrl(activeSessionId));
    ws.onopen = () => {
      ws.send(JSON.stringify({ type }));
    };
    ws.onmessage = (ev) => {
      const data = JSON.parse(ev.data);
      if (data.type === 'session_cleared') {
        setMessages([]);
      } else if (data.type === 'session_compacted') {
        if (data.compacted_count > 0) {
          loadSessionMessages(activeSessionId);
        } else if (data.summary) {
          setMessages((prev) => [
            ...prev,
            { kind: 'compacted_summary', content: data.summary },
          ]);
        }
      }
      ws.close();
    };
  }

  async function runTurnOverWebSocket(rawPrompt, displayPrompt = null) {
    if (!activeSessionId || isTurnRunning) return;

    setMessages((prev) => [
      ...prev,
      {
        kind: 'user',
        content: displayPrompt || rawPrompt,
        attachment: '',
        isExpanded: false,
      },
      { kind: 'thinking', content: '' },
    ]);
    setIsTurnRunning(true);

    const wsUrl = apiClient.getWebSocketUrl(activeSessionId);
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;
    let streamingStarted = false;

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: 'user_message', content: rawPrompt }));
    };

    ws.onmessage = async (event) => {
      const data = JSON.parse(event.data);
      const msgType = data.type;

      if (msgType === 'tool_approval_request') {
        const callId = data.call_id || '';
        const toolName = data.tool || '';
        const toolArgs = data.args || {};

        const { approved, customReply } = await requestToolApproval(
          toolName,
          toolArgs
        );
        ws.send(
          JSON.stringify({
            type: 'tool_approval_response',
            call_id: callId,
            approved,
            message: customReply,
          })
        );
        return;
      }

      if (msgType === 'tool_executed') {
        streamingStarted = false;
        const toolName = data.tool || '';
        const argPreview = JSON.stringify(data.args || {});
        const shortArgs =
          argPreview.length > 55 ? argPreview.slice(0, 52) + '...' : argPreview;

        setMessages((prev) => [
          ...prev.filter((m) => m.kind !== 'thinking'),
          {
            kind: 'tool_action',
            summary: `${toolName}(${shortArgs})`,
            details: data.output || '',
            isExpanded: false,
          },
          { kind: 'thinking', content: '' },
        ]);
        apiClient.listWorkspaceFiles(workspace).then(setFiles).catch(() => {});
        return;
      }

      if (msgType === 'tool_call') {
        const callId = data.call_id || '';
        const toolName = data.tool || '';
        const toolArgs = data.args || {};
        streamingStarted = false;

        if (normalizeToolName(toolName) === 'askuser') {
          setMessages((prev) => prev.filter((m) => m.kind !== 'thinking'));
          const answerStr = await handleAskUserTool(toolArgs);
          setMessages((prev) => [
            ...prev,
            {
              kind: 'tool_action',
              summary: 'Answered clarifying questions',
              details: answerStr,
              isExpanded: false,
            },
            { kind: 'thinking', content: '' },
          ]);
          ws.send(
            JSON.stringify({
              type: 'tool_result',
              call_id: callId,
              output: answerStr,
            })
          );
          return;
        }

        const isInternalProbe =
          String(callId).endsWith('_probe') || toolName === 'memory_probe';
        if (isInternalProbe) {
          ws.send(
            JSON.stringify({
              type: 'tool_result',
              call_id: callId,
              output: 'Error: Local device bridge not connected.',
            })
          );
          return;
        }

        ws.send(
          JSON.stringify({
            type: 'tool_result',
            call_id: callId,
            output:
              'Error: Local device is not connected. Ask the user to run `ai-coder ui` in their terminal.',
          })
        );
        return;
      }

      if (msgType === 'token') {
        const delta = data.delta || '';
        if (!delta) return;
        setMessages((prev) => {
          const clean = prev.filter((m) => m.kind !== 'thinking');
          if (!streamingStarted) {
            streamingStarted = true;
            return [...clean, { kind: 'agent', content: delta }];
          }
          const copy = [...clean];
          const lastIdx = copy.length - 1;
          if (lastIdx >= 0 && copy[lastIdx].kind === 'agent') {
            copy[lastIdx] = {
              ...copy[lastIdx],
              content: copy[lastIdx].content + delta,
            };
          } else {
            copy.push({ kind: 'agent', content: delta });
          }
          return copy;
        });
      } else if (msgType === 'turn_complete' || msgType === 'agent_message') {
        const finalContent = data.content || '';
        setMessages((prev) => {
          const clean = prev.filter((m) => m.kind !== 'thinking');
          if (streamingStarted && clean.length > 0) {
            const copy = [...clean];
            const lastIdx = copy.length - 1;
            if (
              copy[lastIdx].kind === 'agent' &&
              finalContent.length > copy[lastIdx].content.length
            ) {
              copy[lastIdx] = { ...copy[lastIdx], content: finalContent };
            }
            return copy;
          }
          if (finalContent) {
            return [...clean, { kind: 'agent', content: finalContent }];
          }
          return clean;
        });
        setIsTurnRunning(false);
        ws.close();
      } else if (msgType === 'turn_cancelled') {
        setMessages((prev) => [
          ...prev.filter((m) => m.kind !== 'thinking'),
          { kind: 'cancelled', content: '' },
        ]);
        setIsTurnRunning(false);
        ws.close();
      } else if (msgType === 'session_renamed') {
        const cleanTitle = (data.title || '').replace(/[*`]/g, '').trim();
        if (cleanTitle) {
          setSessions((prev) =>
            prev.map((s) =>
              String(s.id) === String(data.session_id)
                ? { ...s, title: cleanTitle }
                : s
            )
          );
        }
      } else if (msgType === 'session_compacted') {
        if (data.summary) {
          setMessages((prev) => [
            ...prev.filter((m) => m.kind !== 'thinking'),
            { kind: 'compacted_summary', content: data.summary },
          ]);
        }
      } else if (msgType === 'error') {
        setMessages((prev) => [
          ...prev.filter((m) => m.kind !== 'thinking'),
          { kind: 'error', content: data.message || 'Agent error' },
        ]);
        setIsTurnRunning(false);
        ws.close();
      }
    };

    ws.onerror = () => {
      setMessages((prev) => [
        ...prev.filter((m) => m.kind !== 'thinking'),
        {
          kind: 'error',
          content: 'WebSocket connection failed. Verify your backend server is running.',
        },
      ]);
      setIsTurnRunning(false);
    };

    ws.onclose = () => {
      setIsTurnRunning(false);
    };
  }

  function executeSlashOrSend(rawText) {
    const trimmed = (rawText ?? input).trim();
    if (!trimmed || isTurnRunning) return;
    setInput('');
    setPopupType(null);

    const lower = trimmed.toLowerCase();
    if (lower === '/clear' || lower === 'clear') {
      sendWsSessionCommand('clear_session');
      return;
    }
    if (lower === '/compact') {
      sendWsSessionCommand('compact_session');
      return;
    }
    if (lower === '/new') {
      handleCreateNewSession();
      return;
    }
    if (lower === '/memory') {
      runTurnOverWebSocket(
        'Read `AGENTS.md` in the workspace root using read_file and display its contents verbatim.',
        '/memory'
      );
      return;
    }
    if (lower === '/init') {
      const initPrompt =
        'Inspect the files and structure of this workspace using list_files and read_file, ' +
        'then create or update `AGENTS.md` in the workspace root with concise, high-signal project memory: ' +
        'tech stack, key files/directories, run/test commands, and coding conventions.';
      runTurnOverWebSocket(initPrompt, '/init');
      return;
    }

    runTurnOverWebSocket(trimmed);
  }

  function handleInputChange(e) {
    const val = e.target.value;
    setInput(val);

    const cursorPos = e.target.selectionStart ?? val.length;
    const before = val.slice(0, cursorPos);
    const stripped = before.trimStart();

    if (stripped.startsWith('/') && !stripped.includes(' ')) {
      const q = stripped.toLowerCase();
      const matches = SLASH_COMMANDS.filter((s) => s.cmd.startsWith(q));
      setPopupItems(matches);
      setPopupType(matches.length > 0 ? 'slash' : null);
      setSelectedPopupIdx(0);
      return;
    }

    const atMatch = before.match(/@([a-zA-Z0-9_\-./]*)$/);
    if (atMatch) {
      const q = atMatch[1].toLowerCase();
      const matches = files.filter((f) => f.toLowerCase().includes(q));
      setPopupItems(matches);
      setPopupType(matches.length > 0 ? 'file' : null);
      setSelectedPopupIdx(0);
      return;
    }

    setPopupType(null);
  }

  function applyPopupSelection(item) {
    if (popupType === 'slash') {
      setPopupType(null);
      executeSlashOrSend(item.cmd);
      return;
    }
    if (popupType === 'file') {
      const cursorPos = inputRef.current?.selectionStart ?? input.length;
      const before = input.slice(0, cursorPos);
      const after = input.slice(cursorPos);
      const atIdx = before.lastIndexOf('@');
      const next = before.slice(0, atIdx) + `@${item} ` + after;
      setInput(next);
      setPopupType(null);
      inputRef.current?.focus();
    }
  }

  function handleKeyDown(e) {
    if (popupType && popupItems.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedPopupIdx((prev) => (prev + 1) % popupItems.length);
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedPopupIdx((prev) =>
          prev === 0 ? popupItems.length - 1 : prev - 1
        );
        return;
      }
      if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey)) {
        e.preventDefault();
        applyPopupSelection(popupItems[selectedPopupIdx]);
        return;
      }
      if (e.key === 'Escape') {
        setPopupType(null);
        return;
      }
    }

    if (e.ctrlKey && e.key.toLowerCase() === 'u') {
      e.preventDefault();
      const pos = e.target.selectionStart ?? input.length;
      const before = input.slice(0, pos);
      const after = input.slice(pos);
      if (!before) return;
      const lastNl = before.lastIndexOf('\n');
      let nextBefore = '';
      if (lastNl === pos - 1) {
        const prevNl = before.slice(0, -1).lastIndexOf('\n');
        nextBefore = prevNl === -1 ? '' : before.slice(0, prevNl + 1);
      } else {
        nextBefore = lastNl === -1 ? '' : before.slice(0, lastNl + 1);
      }
      setInput(nextBefore + after);
      return;
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      const pos = e.target.selectionStart ?? input.length;
      const before = input.slice(0, pos);
      const after = input.slice(pos);
      if (before.endsWith('\\')) {
        e.preventDefault();
        setInput(before.slice(0, -1) + '\n' + after);
        return;
      }
      e.preventDefault();
      executeSlashOrSend();
    }
  }

  if (!auth.token) {
    return <AuthModal onSuccess={handleAuthSuccess} />;
  }

  const activeSession =
    sessions.find((s) => s.id === activeSessionId) || sessions[0] || {};
  const cleanSessionTitle = (
    activeSession.title || 'New session'
  ).replace(/[*`]/g, '');

  const workspaceShortName = workspace
    ? workspace.split('/').filter(Boolean).pop() || workspace
    : 'Select workspace';

  return (
    <div className="claude-app-shell">
      {/* Collapsible Left Sessions Sidebar */}
      <Sidebar
        isOpen={leftSidebarOpen}
        onToggle={() => setLeftSidebarOpen((prev) => !prev)}
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelectSession={setActiveSessionId}
        onNewSession={() => handleCreateNewSession()}
        onRefreshSessions={loadWorkspacesAndSessions}
        userEmail={auth.email}
        onLogout={handleLogout}
      />

      {/* Center Main Chat Column */}
      <main className="claude-center-column">
        {/* Clean Minimal Top Bar */}
        <header className="claude-top-bar">
          <div className="top-bar-left">
            {!leftSidebarOpen && (
              <button
                type="button"
                onClick={() => setLeftSidebarOpen(true)}
                className="top-icon-btn"
                title="Open sessions sidebar"
                aria-label="Open sessions sidebar"
              >
                ☰
              </button>
            )}
            <span className="top-session-title">{cleanSessionTitle}</span>
            {isTurnRunning && (
              <span className="top-working-dot" title="Agent is generating" />
            )}
          </div>

          <div className="top-bar-right">
            <span
              className={`device-dot-indicator ${
                daemonStatus.connected ? 'dot-connected' : 'dot-disconnected'
              }`}
              title={
                daemonStatus.connected
                  ? 'Local device bridge connected'
                  : 'Local device offline (run `ai-coder ui`)'
              }
            />

            {/* Files Icon Toggle with Hover Toast */}
            <div className="tooltip-anchor">
              <button
                type="button"
                onClick={() => setRightFilesOpen((prev) => !prev)}
                className={`top-icon-btn ${
                  rightFilesOpen ? 'top-icon-btn-active' : ''
                }`}
                aria-label="Files"
              >
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                </svg>
              </button>
              <span className="hover-toast">Files</span>
            </div>
          </div>
        </header>

        {/* Empty State or Chat Dialogue Stream */}
        {messages.length === 0 && !activeCard ? (
          <div className="claude-empty-hero">
            <div className="hero-card">
              <div className="hero-mascot">▛▞▜</div>
              <h2 className="hero-heading">What would you like to build?</h2>
              <p className="hero-sub">
                Type <code>/</code> for commands or <code>@</code> to reference files in{' '}
                <span className="mono">{workspaceShortName}</span>
              </p>
            </div>
          </div>
        ) : (
          <MessageStream
            messages={messages}
            onToggleExpand={(idx) =>
              setMessages((prev) =>
                prev.map((m, i) =>
                  i === idx ? { ...m, isExpanded: !m.isExpanded } : m
                )
              )
            }
            activeCard={activeCard}
            onSelectCardOption={handleSelectCardOption}
            onCancelCard={handleCancelCard}
            onCancelTurn={handleCancelTurn}
            messagesEndRef={messagesEndRef}
          />
        )}

        {/* Bottom Chat Composer + Active Workspace Selector Below It */}
        <footer className="claude-composer-region">
          <div className="claude-composer-inner">
            {popupType && popupItems.length > 0 && (
              <div className="claude-autocomplete-menu mono">
                <div className="popup-section-label">
                  {popupType === 'slash' ? 'Commands' : 'Workspace files'}
                </div>
                {popupItems.map((item, idx) => {
                  const isSel = idx === selectedPopupIdx;
                  const key = popupType === 'slash' ? item.cmd : item;
                  return (
                    <div
                      key={key}
                      onClick={() => applyPopupSelection(item)}
                      className={`claude-popup-row ${
                        isSel ? 'claude-popup-row-active' : ''
                      }`}
                    >
                      {popupType === 'slash' ? (
                        <>
                          <span className="popup-cmd-name">{item.cmd}</span>
                          <span className="popup-cmd-desc">{item.desc}</span>
                        </>
                      ) : (
                        <span>📄 {item}</span>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            {/* Rounded Chat Input Box */}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                executeSlashOrSend();
              }}
              className="claude-input-box"
            >
              <textarea
                ref={inputRef}
                rows={2}
                value={input}
                onChange={handleInputChange}
                onKeyDown={handleKeyDown}
                disabled={isTurnRunning}
                placeholder="Describe a task or ask a question..."
                className="claude-textarea"
              />
              <div className="claude-input-actions">
                {isTurnRunning ? (
                  <button
                    type="button"
                    onClick={handleCancelTurn}
                    className="claude-stop-btn"
                    title="Stop generation"
                  >
                    ■
                  </button>
                ) : (
                  <button
                    type="submit"
                    disabled={!input.trim()}
                    className="claude-send-btn"
                    title="Send message"
                  >
                    ↑
                  </button>
                )}
              </div>
            </form>

            {/* Active Workspace Selector Below the Chatbox (Claude Style) */}
            <div className="below-chat-workspace-bar">
              <div className="ws-selector-anchor">
                <button
                  type="button"
                  onClick={() => setWsMenuOpen((prev) => !prev)}
                  className="ws-pill-btn"
                  title={workspace}
                >
                  <span className="ws-icon">❐</span>
                  <span className="ws-name">{workspaceShortName}</span>
                  <span className="ws-caret">▾</span>
                </button>

                {wsMenuOpen && (
                  <div className="ws-popover-menu">
                    <div className="ws-popover-header">Switch workspace</div>
                    {availableWorkspaces.map((ws) => {
                      const label = ws.split('/').filter(Boolean).pop() || ws;
                      const isCurr = ws === workspace;
                      return (
                        <button
                          key={ws}
                          type="button"
                          onClick={() => {
                            setWorkspace(ws);
                            setWsMenuOpen(false);
                          }}
                          className={`ws-popover-item ${
                            isCurr ? 'ws-popover-item-active' : ''
                          }`}
                          title={ws}
                        >
                          <div className="ws-item-main">
                            <span>❐ {label}</span>
                            {isCurr && <span>✓</span>}
                          </div>
                          <div className="ws-item-path mono">{ws}</div>
                        </button>
                      );
                    })}
                    <div className="ws-popover-divider" />
                    <button
                      type="button"
                      onClick={() => openFolderBrowser(workspace)}
                      className="ws-browse-device-btn"
                    >
                      📂 Browse folder on device...
                    </button>
                  </div>
                )}
              </div>

              <span className="ws-full-path-hint mono">{workspace}</span>
            </div>
          </div>
        </footer>
      </main>

      {/* Collapsible Right-Side Files Tree & Content Preview Split Panel */}
      <FilesDrawer
        isOpen={rightFilesOpen}
        onClose={() => setRightFilesOpen(false)}
        workspace={workspace}
        files={files}
        onAttachFile={(fname) => {
          setInput((prev) => (prev ? `${prev} @${fname} ` : `@${fname} `));
          inputRef.current?.focus();
        }}
      />

      {/* Device Folder Browser Modal */}
      {browserOpen && (
        <div
          className="folder-modal-backdrop"
          onClick={() => setBrowserOpen(false)}
        >
          <div className="folder-modal" onClick={(e) => e.stopPropagation()}>
            <div className="folder-modal-header">
              <span className="mono">📂 Select Folder on Device</span>
              <button
                type="button"
                onClick={() => setBrowserOpen(false)}
                className="sidebar-mini-btn"
              >
                ✕
              </button>
            </div>

            <div className="folder-current-bar mono">
              <span className="truncate">{browsePath || '/'}</span>
              {parentPath && (
                <button
                  type="button"
                  onClick={() => openFolderBrowser(parentPath)}
                  className="up-dir-btn mono"
                >
                  ↑ Up
                </button>
              )}
            </div>

            <div className="folder-list-box">
              {browseLoading ? (
                <div className="sidebar-empty-note mono">
                  Scanning directories...
                </div>
              ) : subFolders.length === 0 ? (
                <div className="sidebar-empty-note mono">
                  No subdirectories found.
                </div>
              ) : (
                subFolders.map((folder) => (
                  <button
                    key={folder.path}
                    type="button"
                    onClick={() => openFolderBrowser(folder.path)}
                    className="folder-row-btn mono"
                  >
                    <span>📁 {folder.name}</span>
                    <span className="folder-enter-hint">Open →</span>
                  </button>
                ))
              )}
            </div>

            <div className="folder-modal-footer">
              <button
                type="button"
                onClick={() => setBrowserOpen(false)}
                className="card-cancel-btn"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  if (browsePath) {
                    setWorkspace(browsePath);
                  }
                  setBrowserOpen(false);
                }}
                className="primary-btn"
              >
                Select Folder
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}