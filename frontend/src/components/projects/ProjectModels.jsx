import { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react';
import { fmtBytes, fmtDate } from '../../utils/format';
import { extOf, isViewable } from './modelFormats';

// three.js is ~600 KB of the bundle and only projects with printed parts need
// it, so the viewer is split out and fetched the first time one is shown.
const ModelViewer = lazy(() => import('./ModelViewer'));

// Everything the API accepts (ALLOWED_MODEL_EXTENSIONS in backend config.py).
const ACCEPT = '.stl,.3mf,.obj,.step,.stp,.scad,.gcode,.bgcode,.f3d';

// Parsing a huge mesh blocks the main thread, so big models wait for a click.
const AUTO_PREVIEW_MAX_BYTES = 25 * 1024 * 1024;

const fmtDims = (dims) =>
  dims ? `${dims.x.toFixed(1)} × ${dims.y.toFixed(1)} × ${dims.z.toFixed(1)} mm` : null;

/**
 * One model: preview on the left, what it is on the right.
 *
 * The canvas is only mounted once the card scrolls into view — a project with
 * fifteen printed parts would otherwise open fifteen WebGL contexts at once
 * and hit the browser's limit.
 */
const ModelCard = ({ file, url, onDelete }) => {
  const cardRef = useRef(null);
  const [visible, setVisible] = useState(false);
  const [manualLoad, setManualLoad] = useState(false);
  const [stats, setStats] = useState(null);

  const viewable = isViewable(file.filename);
  const tooBig = (file.size || 0) > AUTO_PREVIEW_MAX_BYTES;
  const showViewer = viewable && visible && (!tooBig || manualLoad);

  useEffect(() => {
    const node = cardRef.current;
    if (!node || !viewable || visible) return undefined;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: '200px' }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [viewable, visible]);

  const handleLoaded = useCallback((s) => setStats(s), []);

  return (
    <div ref={cardRef} className="flex gap-4 p-3 border border-dark-border rounded-lg bg-dark-surface">
      <div className="w-40 h-32 flex-shrink-0">
        {showViewer ? (
          <Suspense
            fallback={
              <div className="w-full h-full flex items-center justify-center bg-dark-bg border border-dark-border rounded-lg text-xs text-dark-textMuted">
                Loading viewer…
              </div>
            }
          >
            <ModelViewer url={url} filename={file.filename} onLoad={handleLoaded} className="w-full h-full" />
          </Suspense>
        ) : (
          <div className="w-full h-full flex flex-col items-center justify-center gap-2 bg-dark-bg border border-dark-border rounded-lg text-center px-2">
            {viewable && tooBig ? (
              <>
                <span className="text-xs text-dark-textMuted">{fmtBytes(file.size)} — preview off by default</span>
                <button onClick={() => setManualLoad(true)} className="link text-xs">
                  Load preview
                </button>
              </>
            ) : (
              <span className="text-xs text-dark-textMuted">
                {viewable ? '…' : `No preview for ${extOf(file.filename) || 'this format'}`}
              </span>
            )}
          </div>
        )}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-3">
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="link text-sm font-medium break-all"
            title={file.filename}
          >
            {file.filename || `model #${file.id}`}
          </a>
          <button
            onClick={onDelete}
            className="text-dark-textMuted hover:text-dark-error p-1 flex-shrink-0"
            title="Delete model"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
              />
            </svg>
          </button>
        </div>

        <dl className="mt-1.5 space-y-0.5 text-xs text-dark-textMuted">
          {stats?.dims && (
            <div className="tabular-nums" title="Bounding box, model units assumed to be millimetres">
              {fmtDims(stats.dims)}
            </div>
          )}
          <div className="tabular-nums">
            {fmtBytes(file.size)}
            {stats?.format ? ` · ${stats.format}` : ''}
            {stats?.triangles ? ` · ${stats.triangles.toLocaleString()} tris` : ''}
          </div>
          <div>Added {fmtDate(file.created_at)}</div>
        </dl>

        <a href={url} download={file.filename} className="link text-xs inline-block mt-2">
          Download
        </a>
      </div>
    </div>
  );
};

/**
 * The project page's 3D-model section: printed parts for the build, kept
 * apart from schematics/firmware/docs in the Files card.
 */
const ProjectModels = ({ models, fileUrl, onUpload, onDelete, uploading }) => {
  const inputRef = useRef(null);

  const handlePick = (e) => {
    const file = e.target.files?.[0];
    if (file) onUpload(file);
    e.target.value = '';
  };

  return (
    <div className="card">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h2 className="text-lg font-semibold">
          3D Models
          {models.length > 0 && (
            <span className="ml-2 text-sm font-normal text-dark-textMuted tabular-nums">{models.length}</span>
          )}
        </h2>
        <label className="btn-secondary text-sm py-1.5 cursor-pointer">
          {uploading ? 'Uploading...' : 'Upload Model'}
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            onChange={handlePick}
            className="hidden"
            disabled={uploading}
          />
        </label>
      </div>

      {models.length === 0 ? (
        <p className="text-sm text-dark-textMuted">
          No 3D models attached. STL, 3MF and OBJ preview in the browser; STEP, SCAD, F3D and
          G-code are stored for download.
        </p>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
          {models.map((f) => (
            <ModelCard key={f.id} file={f} url={fileUrl(f)} onDelete={() => onDelete(f.id)} />
          ))}
        </div>
      )}
    </div>
  );
};

export default ProjectModels;
