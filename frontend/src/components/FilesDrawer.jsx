import { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { apiClient } from '../api/client';

export default function FilesDrawer({
  isOpen,
  onClose,
  workspace,
  files,
  onAttachFile,
}) {
  const [filterQuery, setFilterQuery] = useState('');
  const [activeFile, setActiveFile] = useState(null);
  const [fileContent, setFileContent] = useState('');
  const [fileLoading, setFileLoading] = useState(false);
  const [viewMode, setViewMode] = useState('preview'); // 'preview' | 'code'

  useEffect(() => {
    setActiveFile(null);
    setFileContent('');
  }, [workspace]);

  if (!isOpen) {
    return null;
  }

  const isMarkdown = activeFile && activeFile.toLowerCase().endsWith('.md');

  const filteredFiles = files.filter((f) =>
    !filterQuery.trim() ? true : f.toLowerCase().includes(filterQuery.toLowerCase())
  );

  async function handleOpenFile(fname) {
    setActiveFile(fname);
    setViewMode(fname.toLowerCase().endsWith('.md') ? 'preview' : 'code');
    setFileLoading(true);
    const res = await apiClient.readWorkspaceFile(workspace, fname);
    setFileContent(
      res.error ? `Error loading file: ${res.error}` : res.content || ''
    );
    setFileLoading(false);
  }

  return (
    <section className="right-files-split">
      {/* Center-Right Content Viewer Pane (opens when a file is selected or shows placeholder) */}
      <div className="file-content-pane">
        <div className="content-pane-header">
          {activeFile ? (
            <div className="active-file-tab">
              <span className="mono">{activeFile}</span>
              <button
                type="button"
                onClick={() => setActiveFile(null)}
                className="tab-close-btn"
                title="Close file"
              >
                ✕
              </button>
            </div>
          ) : (
            <span className="pane-title-muted">Files</span>
          )}

          <div className="content-pane-controls">
            {activeFile && isMarkdown && (
              <div className="md-mode-toggle" title="Toggle Markdown Preview / Source Code">
                <button
                  type="button"
                  onClick={() => setViewMode('preview')}
                  className={`mode-pill ${viewMode === 'preview' ? 'mode-pill-active' : ''}`}
                >
                  Preview
                </button>
                <button
                  type="button"
                  onClick={() => setViewMode('code')}
                  className={`mode-pill mono ${viewMode === 'code' ? 'mode-pill-active' : ''}`}
                >
                  &lt;/&gt;
                </button>
              </div>
            )}
            {activeFile && (
              <button
                type="button"
                onClick={() => onAttachFile(activeFile)}
                className="attach-action-btn mono"
                title="Insert @file into chat"
              >
                +@
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="pane-close-btn"
              title="Close files panel"
            >
              ✕
            </button>
          </div>
        </div>

        <div className="content-pane-body">
          {!activeFile ? (
            <div className="pane-empty-state">
              <div className="pane-folder-icon">📁</div>
              <div className="pane-empty-title">Open files appear here</div>
              <div className="pane-empty-sub">Pick a file in the tree on the right.</div>
            </div>
          ) : fileLoading ? (
            <div className="pane-empty-state">
              <div className="pane-empty-sub mono">Loading {activeFile}...</div>
            </div>
          ) : isMarkdown && viewMode === 'preview' ? (
            <div className="md-preview-container">
              <div className="md-file-breadcrumb mono">
                {workspace.split('/').pop()} / {activeFile}
              </div>
              <div className="claude-markdown">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {fileContent}
                </ReactMarkdown>
              </div>
            </div>
          ) : (
            <pre className="raw-code-viewer mono">
              <code>{fileContent || '(Empty file)'}</code>
            </pre>
          )}
        </div>
      </div>

      {/* Far-Right File Tree Sidebar */}
      <div className="file-tree-pane">
        <div className="tree-search-box">
          <input
            type="text"
            value={filterQuery}
            onChange={(e) => setFilterQuery(e.target.value)}
            placeholder="Filter files..."
            className="tree-filter-input"
          />
        </div>

        <div className="tree-list-scroll">
          {filteredFiles.map((fname) => {
            const isSelected = activeFile === fname;
            return (
              <div
                key={fname}
                onClick={() => handleOpenFile(fname)}
                className={`tree-file-row ${isSelected ? 'tree-file-row-active' : ''}`}
              >
                <span className="tree-file-label mono" title={fname}>
                  📄 {fname}
                </span>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onAttachFile(fname);
                  }}
                  className="tree-attach-btn mono"
                  title={`Attach @${fname}`}
                >
                  @
                </button>
              </div>
            );
          })}

          {filteredFiles.length === 0 && (
            <div className="tree-empty-msg">No matching files</div>
          )}
        </div>
      </div>
    </section>
  );
}