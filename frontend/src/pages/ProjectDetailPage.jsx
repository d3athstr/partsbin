import { useState, useRef } from 'react';
import { Link, useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import projectService from '../services/projectService';
import { errMsg } from '../services/api';
import ComponentPicker from '../components/common/ComponentPicker';
import { fmtDate } from '../utils/format';

const FILE_KINDS = ['image', 'pdf', 'schematic', 'firmware', 'other'];
const PROJECT_STATUSES = ['planning', 'active', 'built', 'on_hold', 'retired'];

const fileUrl = (f) => f.url || (f.filename ? `/uploads/projects/${f.filename}` : '#');

/**
 * BOM availability coloring (ISA-101): gray when covered, amber when the
 * line is short, red when the component has zero stock.
 */
const AvailabilityText = ({ line }) => {
  const available = Number(line.available ?? line.component?.qty_on_hand ?? 0);
  const short = !!line.short;

  let cls = 'text-dark-textMuted';
  if (available <= 0 && short) cls = 'text-dark-error font-semibold';
  else if (short) cls = 'text-dark-warning font-semibold';

  return (
    <span className={`${cls} tabular-nums text-sm whitespace-nowrap`}>
      {available}
      {short && (available <= 0 ? ' — none in stock' : ' — short')}
    </span>
  );
};

const ProjectDetailPage = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [actionError, setActionError] = useState('');
  const [showPicker, setShowPicker] = useState(false);
  const [pickQty, setPickQty] = useState('1');
  const [consumingLine, setConsumingLine] = useState(null);
  const [consumeQty, setConsumeQty] = useState('1');
  const [uploadKind, setUploadKind] = useState('image');
  const fileInputRef = useRef(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ['project', id],
    queryFn: () => projectService.get(id),
  });

  const project = data?.project || data || {};
  const bom = data?.bom || project.bom || [];
  const files = data?.files || project.files || [];

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['project', id] });
    queryClient.invalidateQueries({ queryKey: ['components'] });
    queryClient.invalidateQueries({ queryKey: ['dashboard'] });
  };

  const addBomMutation = useMutation({
    mutationFn: ({ component_id, qty_planned }) =>
      projectService.addBomLine(id, { component_id, qty_planned }),
    onSuccess: () => {
      invalidate();
      setActionError('');
    },
    onError: (err) => setActionError(errMsg(err, 'Failed to add BOM line')),
  });

  const deleteBomMutation = useMutation({
    mutationFn: (lineId) => projectService.deleteBomLine(id, lineId),
    onSuccess: () => invalidate(),
    onError: (err) => setActionError(errMsg(err, 'Failed to remove BOM line')),
  });

  const consumeMutation = useMutation({
    mutationFn: ({ lineId, qty }) => projectService.consume(id, lineId, qty),
    onSuccess: () => {
      invalidate();
      setConsumingLine(null);
      setConsumeQty('1');
      setActionError('');
    },
    onError: (err) => setActionError(errMsg(err, 'Consume failed')),
  });

  const uploadMutation = useMutation({
    mutationFn: ({ file, kind }) => projectService.uploadFile(id, file, kind),
    onSuccess: () => {
      invalidate();
      if (fileInputRef.current) fileInputRef.current.value = '';
      setActionError('');
    },
    onError: (err) => setActionError(errMsg(err, 'Upload failed')),
  });

  const deleteFileMutation = useMutation({
    mutationFn: (fileId) => projectService.deleteFile(id, fileId),
    onSuccess: () => invalidate(),
    onError: (err) => setActionError(errMsg(err, 'Failed to delete file')),
  });

  const deleteProjectMutation = useMutation({
    mutationFn: () => projectService.remove(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      navigate('/projects');
    },
    onError: (err) => setActionError(errMsg(err, 'Delete failed')),
  });

  const statusMutation = useMutation({
    mutationFn: (status) => projectService.update(id, { status }),
    onSuccess: () => {
      // Stock warnings are scoped to active projects, so a status change can
      // add/clear dashboard warnings — refresh it too.
      queryClient.invalidateQueries({ queryKey: ['project', id] });
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      setActionError('');
    },
    onError: (err) => setActionError(errMsg(err, 'Failed to update status')),
  });

  const handleUpload = (e) => {
    const file = e.target.files?.[0];
    if (file) {
      uploadMutation.mutate({ file, kind: uploadKind });
    }
  };

  const handleDeleteProject = () => {
    if (window.confirm(`Delete project "${project.name}"? This cannot be undone.`)) {
      deleteProjectMutation.mutate();
    }
  };

  if (isLoading) {
    return (
      <div className="flex justify-center py-16">
        <div className="w-10 h-10 border-4 border-dark-accent border-t-transparent rounded-full spinner"></div>
      </div>
    );
  }

  if (error) {
    return <div className="alert-error">Failed to load project: {error.message}</div>;
  }

  const imageFiles = files.filter((f) => f.kind === 'image');
  const otherFiles = files.filter((f) => f.kind !== 'image');

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link to="/projects" className="link text-sm">
            ← Projects
          </Link>
          <div className="flex items-center gap-3 mt-1">
            <h1>{project.name}</h1>
            <select
              value={project.status || 'planning'}
              onChange={(e) => statusMutation.mutate(e.target.value)}
              disabled={statusMutation.isPending}
              className="input py-1 text-sm w-auto"
              title="Only 'active' projects drive dashboard stock warnings"
            >
              {PROJECT_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s.replace('_', ' ')}
                </option>
              ))}
            </select>
          </div>
          {project.description && (
            <p className="text-dark-textMuted text-sm mt-1">{project.description}</p>
          )}
          {project.repo_url && (
            <a
              href={project.repo_url}
              target="_blank"
              rel="noopener noreferrer"
              className="link text-sm inline-block mt-1"
            >
              {project.repo_url}
            </a>
          )}
        </div>
        <div className="flex gap-2">
          <Link to={`/projects/${id}/edit`} className="btn-secondary">
            Edit
          </Link>
          <button
            onClick={handleDeleteProject}
            disabled={deleteProjectMutation.isPending}
            className="btn-danger"
          >
            Delete
          </button>
        </div>
      </div>

      {actionError && <div className="alert-error">{actionError}</div>}

      {/* BOM */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Bill of Materials</h2>
          <button onClick={() => setShowPicker(true)} className="btn-secondary text-sm py-1.5">
            + Add Component
          </button>
        </div>

        {bom.length === 0 ? (
          <p className="text-sm text-dark-textMuted">No components in the BOM yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-dark-border text-dark-textMuted">
                  <th className="text-left py-2 pr-3 font-medium">Component</th>
                  <th className="text-right py-2 pr-3 font-medium">Planned</th>
                  <th className="text-right py-2 pr-3 font-medium">Used</th>
                  <th className="text-right py-2 pr-3 font-medium">Available</th>
                  <th className="py-2"></th>
                </tr>
              </thead>
              <tbody>
                {bom.map((line) => {
                  const comp = line.component || {};
                  const lineId = line.id ?? line.line_id;
                  return (
                    <tr key={lineId} className="border-b border-dark-border last:border-b-0">
                      <td className="py-2.5 pr-3">
                        <Link to={`/inventory/${comp.id ?? line.component_id}`} className="link">
                          {comp.name || line.component_name || `#${line.component_id}`}
                        </Link>
                        {line.note && (
                          <p className="text-xs text-dark-textMuted">{line.note}</p>
                        )}
                      </td>
                      <td className="py-2.5 pr-3 text-right tabular-nums">{line.qty_planned}</td>
                      <td className="py-2.5 pr-3 text-right tabular-nums">{line.qty_used ?? 0}</td>
                      <td className="py-2.5 pr-3 text-right">
                        <AvailabilityText line={line} />
                      </td>
                      <td className="py-2.5 text-right whitespace-nowrap">
                        {consumingLine === lineId ? (
                          <span className="inline-flex items-center gap-1">
                            <input
                              type="number"
                              min="1"
                              value={consumeQty}
                              onChange={(e) => setConsumeQty(e.target.value)}
                              className="input w-20 py-1 text-sm"
                              autoFocus
                            />
                            <button
                              onClick={() =>
                                consumeMutation.mutate({
                                  lineId,
                                  qty: parseInt(consumeQty, 10) || 1,
                                })
                              }
                              disabled={consumeMutation.isPending}
                              className="btn-primary text-xs px-2 py-1"
                            >
                              OK
                            </button>
                            <button
                              onClick={() => setConsumingLine(null)}
                              className="btn-secondary text-xs px-2 py-1"
                            >
                              ✕
                            </button>
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-2">
                            <button
                              onClick={() => {
                                setConsumingLine(lineId);
                                setConsumeQty('1');
                              }}
                              className="text-xs px-2 py-1 rounded bg-dark-elevated border border-dark-border text-dark-textMuted hover:text-dark-text hover:border-dark-accent"
                              title="Consume stock into this project"
                            >
                              Consume
                            </button>
                            <button
                              onClick={() => {
                                if (window.confirm('Remove this BOM line?')) {
                                  deleteBomMutation.mutate(lineId);
                                }
                              }}
                              className="text-dark-textMuted hover:text-dark-error p-1"
                              title="Remove line"
                            >
                              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                              </svg>
                            </button>
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {showPicker && (
          <div className="mt-4 p-3 bg-dark-elevated rounded-lg flex items-center gap-3">
            <label className="text-sm text-dark-textMuted">Qty planned:</label>
            <input
              type="number"
              min="1"
              value={pickQty}
              onChange={(e) => setPickQty(e.target.value)}
              className="input w-24 py-1"
            />
            <span className="text-sm text-dark-textMuted">then pick a component →</span>
          </div>
        )}
      </div>

      {/* Documentation */}
      <div className="card">
        <h2 className="text-lg font-semibold mb-4">Documentation</h2>
        {project.readme_md ? (
          <div className="markdown-body">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{project.readme_md}</ReactMarkdown>
          </div>
        ) : (
          <p className="text-sm text-dark-textMuted">
            No documentation yet.{' '}
            <Link to={`/projects/${id}/edit`} className="link">
              Add some
            </Link>
            .
          </p>
        )}
      </div>

      {/* Files */}
      <div className="card">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <h2 className="text-lg font-semibold">Files</h2>
          <div className="flex items-center gap-2">
            <select
              value={uploadKind}
              onChange={(e) => setUploadKind(e.target.value)}
              className="input py-1.5 w-32"
            >
              {FILE_KINDS.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
            <label className="btn-secondary text-sm py-1.5 cursor-pointer">
              {uploadMutation.isPending ? 'Uploading...' : 'Upload File'}
              <input
                ref={fileInputRef}
                type="file"
                onChange={handleUpload}
                className="hidden"
                disabled={uploadMutation.isPending}
              />
            </label>
          </div>
        </div>

        {files.length === 0 ? (
          <p className="text-sm text-dark-textMuted">No files uploaded.</p>
        ) : (
          <div className="space-y-4">
            {imageFiles.length > 0 && (
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
                {imageFiles.map((f) => (
                  <div key={f.id} className="relative group">
                    <a href={fileUrl(f)} target="_blank" rel="noopener noreferrer">
                      <img
                        src={fileUrl(f)}
                        alt={f.original_name || f.filename}
                        className="w-full h-32 object-cover rounded-lg bg-dark-bg border border-dark-border"
                      />
                    </a>
                    <button
                      onClick={() => {
                        if (window.confirm('Delete this file?')) {
                          deleteFileMutation.mutate(f.id);
                        }
                      }}
                      className="absolute top-1 right-1 p-1 rounded bg-dark-bg bg-opacity-80 text-dark-textMuted hover:text-dark-error opacity-0 group-hover:opacity-100 transition-opacity"
                      title="Delete file"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>
                ))}
              </div>
            )}

            {otherFiles.length > 0 && (
              <ul className="divide-y divide-dark-border border border-dark-border rounded-lg">
                {otherFiles.map((f) => (
                  <li key={f.id} className="flex items-center justify-between gap-3 px-4 py-2.5">
                    <div className="flex items-center gap-3 min-w-0">
                      <span className="chip-neutral">{f.kind}</span>
                      <a
                        href={fileUrl(f)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="link text-sm truncate"
                      >
                        {f.original_name || f.filename || `file #${f.id}`}
                      </a>
                    </div>
                    <div className="flex items-center gap-3 flex-shrink-0">
                      <span className="text-xs text-dark-textMuted">
                        {fmtDate(f.created_at || f.uploaded_at)}
                      </span>
                      <button
                        onClick={() => {
                          if (window.confirm('Delete this file?')) {
                            deleteFileMutation.mutate(f.id);
                          }
                        }}
                        className="text-dark-textMuted hover:text-dark-error p-1"
                        title="Delete file"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      {/* Component picker modal for BOM */}
      {showPicker && (
        <ComponentPicker
          title="Add Component to BOM"
          onClose={() => setShowPicker(false)}
          onSelect={(component) => {
            addBomMutation.mutate({
              component_id: component.id,
              qty_planned: parseInt(pickQty, 10) || 1,
            });
            setShowPicker(false);
            setPickQty('1');
          }}
        />
      )}
    </div>
  );
};

export default ProjectDetailPage;
