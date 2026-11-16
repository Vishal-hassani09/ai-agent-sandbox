import { useState } from 'react';

export default function Sidebar({
  isOpen,
  onToggle,
  sessions,
  activeSessionId,
  onSelectSession,
  onNewSession,
  onRefreshSessions,
  userEmail,
  onLogout,
}) {
  const [searchQuery, setSearchQuery] = useState('');

  if (!isOpen) {
    return null;
  }

  const cleanEmail = (userEmail || 'user@example.com').trim();
  const initialLetter = cleanEmail.charAt(0).toUpperCase() || 'U';
  const displayName = cleanEmail.split('@')[0];

  const filteredSessions = sessions.filter((s) => {
    const title = (s.title || 'New session').toLowerCase();
    return !searchQuery.trim() || title.includes(searchQuery.toLowerCase());
  });

  return (
    <aside className="claude-sidebar">
      {/* Top Action Row */}
      <div className="sidebar-top-bar">
        <button
          type="button"
          onClick={onNewSession}
          className="sidebar-new-btn"
          title="Start a new session"
        >
          <span className="plus-icon">+</span>
          <span>New session</span>
        </button>

        <button
          type="button"
          onClick={onToggle}
          className="sidebar-icon-btn"
          title="Collapse sidebar"
        >
          ◫
        </button>
      </div>

      {/* Filter Sessions */}
      <div className="sidebar-search-wrap">
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search sessions..."
          className="sidebar-search-input"
        />
      </div>

      {/* Sessions List Only */}
      <div className="sidebar-sessions-scroll">
        <div className="sidebar-group-header">
          <span>Sessions</span>
          <button
            type="button"
            onClick={onRefreshSessions}
            className="sidebar-mini-btn"
            title="Refresh sessions"
          >
            ↻
          </button>
        </div>

        <div className="sidebar-session-items">
          {filteredSessions.map((sess) => {
            const isActive = sess.id === activeSessionId;
            const cleanTitle = (sess.title || 'New session').replace(/[*`]/g, '');
            return (
              <button
                key={sess.id}
                type="button"
                onClick={() => onSelectSession(sess.id)}
                className={`claude-session-row ${
                  isActive ? 'claude-session-row-active' : ''
                }`}
              >
                <span className="session-row-title">{cleanTitle}</span>
              </button>
            );
          })}

          {filteredSessions.length === 0 && (
            <div className="sidebar-empty-note">No sessions found.</div>
          )}
        </div>
      </div>

      {/* Bottom User Profile (Initials Avatar + Email ABOVE Sign Out) */}
      <div className="sidebar-user-footer">
        <div className="user-profile-row" title={cleanEmail}>
          <div className="user-initial-avatar">{initialLetter}</div>
          <div className="user-identity-text">
            <div className="user-display-name">{displayName}</div>
            <div className="user-email-sub">{cleanEmail}</div>
          </div>
        </div>

        <button
          type="button"
          onClick={onLogout}
          className="sidebar-signout-btn"
        >
          Sign out
        </button>
      </div>
    </aside>
  );
}