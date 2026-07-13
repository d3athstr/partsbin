import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { errMsg } from '../../services/api';

const STATUSES = ['planning', 'active', 'built', 'on_hold', 'retired'];

/**
 * Shared project create/edit form with side-by-side markdown preview.
 * Props: initial, onSubmit(payload), submitLabel, busy
 */
const ProjectForm = ({ initial = {}, onSubmit, submitLabel = 'Save', busy = false }) => {
  const [name, setName] = useState(initial.name || '');
  const [status, setStatus] = useState(initial.status || 'planning');
  const [description, setDescription] = useState(initial.description || '');
  const [repoUrl, setRepoUrl] = useState(initial.repo_url || '');
  const [readme, setReadme] = useState(initial.readme_md || '');
  const [tagsText, setTagsText] = useState(
    (initial.tags || []).map((t) => (typeof t === 'string' ? t : t?.name)).join(', ')
  );
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (!name.trim()) {
      setError('Name is required');
      return;
    }

    const payload = {
      name: name.trim(),
      status,
      description: description.trim() || null,
      readme_md: readme,
      repo_url: repoUrl.trim() || null,
      tags: tagsText
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean),
    };

    try {
      await onSubmit(payload);
    } catch (err) {
      setError(errMsg(err, 'Save failed'));
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {error && <div className="alert-error">{error}</div>}

      <div className="card space-y-4">
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium mb-2">Name *</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="input"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-2">Status</label>
            <select value={status} onChange={(e) => setStatus(e.target.value)} className="input">
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s.replace('_', ' ')}
                </option>
              ))}
            </select>
          </div>
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium mb-2">Description</label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="input"
              placeholder="One-line summary"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-2">Repo URL</label>
            <input
              type="url"
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              className="input"
              placeholder="https://github.com/..."
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-2">Tags (comma-separated)</label>
            <input
              type="text"
              value={tagsText}
              onChange={(e) => setTagsText(e.target.value)}
              className="input"
              placeholder="esp32, led, 3d-print"
            />
          </div>
        </div>
      </div>

      {/* Markdown editor with live preview */}
      <div className="card">
        <h2 className="text-lg font-semibold mb-3">Documentation (Markdown)</h2>
        <div className="grid lg:grid-cols-2 gap-4">
          <textarea
            value={readme}
            onChange={(e) => setReadme(e.target.value)}
            className="input font-mono text-sm min-h-[24rem]"
            placeholder={'# Project Name\n\nBuild notes, wiring, firmware, links...'}
          />
          <div className="border border-dark-border rounded-lg p-4 min-h-[24rem] overflow-y-auto bg-dark-bg">
            {readme.trim() ? (
              <div className="markdown-body">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{readme}</ReactMarkdown>
              </div>
            ) : (
              <p className="text-dark-textMuted text-sm">Preview appears here...</p>
            )}
          </div>
        </div>
      </div>

      <div className="flex gap-3">
        <button type="submit" disabled={busy} className="btn-primary">
          {busy ? 'Saving...' : submitLabel}
        </button>
      </div>
    </form>
  );
};

export default ProjectForm;
