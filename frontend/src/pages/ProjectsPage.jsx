import { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import projectService from '../services/projectService';
import Pagination from '../components/common/Pagination';
import { fmtDate, fmtMoney } from '../utils/format';

const PER_PAGE = 24;
const STATUSES = ['planning', 'active', 'on_hold', 'done'];

const StatusLabel = ({ status }) => (
  <span className="chip-neutral">{(status || '').replace('_', ' ')}</span>
);

const ProjectsPage = () => {
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [status, setStatus] = useState('');
  const [page, setPage] = useState(1);

  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedSearch(search);
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [search]);

  const { data, isLoading, error } = useQuery({
    queryKey: ['projects', debouncedSearch, status, page],
    queryFn: () =>
      projectService.list({
        search: debouncedSearch,
        status,
        page,
        per_page: PER_PAGE,
      }),
    placeholderData: (prev) => prev,
  });

  const items = data?.items || [];
  const total = data?.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / (data?.per_page || PER_PAGE)));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1>Projects</h1>
        <Link to="/projects/new" className="btn-primary">
          New Project
        </Link>
      </div>

      <div className="card p-4 flex flex-col sm:flex-row gap-3">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search projects..."
          className="input flex-1"
        />
        <select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setPage(1);
          }}
          className="input sm:w-48"
        >
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s.replace('_', ' ')}
            </option>
          ))}
        </select>
      </div>

      {error && <div className="alert-error">Failed to load projects: {error.message}</div>}

      {isLoading && items.length === 0 ? (
        <div className="flex justify-center py-16">
          <div className="w-10 h-10 border-4 border-dark-accent border-t-transparent rounded-full spinner"></div>
        </div>
      ) : items.length === 0 ? (
        <div className="card text-center py-12 text-dark-textMuted">
          No projects found.
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {items.map((p) => (
            <button
              key={p.id}
              onClick={() => navigate(`/projects/${p.id}`)}
              className="card text-left hover:border-dark-accent transition-colors"
            >
              <div className="flex items-start justify-between gap-2 mb-2">
                <h3 className="text-base font-semibold">{p.name}</h3>
                <StatusLabel status={p.status} />
              </div>
              {p.description && (
                <p className="text-sm text-dark-textMuted line-clamp-3 mb-3">{p.description}</p>
              )}
              {p.cost?.projected_total > 0 && (
                <p className="text-sm mb-1 tabular-nums">
                  {fmtMoney(p.cost.projected_total)}
                  <span className="text-xs text-dark-textMuted">
                    {' '}
                    {p.cost.lines_with_actual === p.cost.line_count
                      ? 'spent'
                      : p.cost.lines_with_actual > 0
                        ? `projected · ${p.cost.lines_with_actual}/${p.cost.line_count} lines bought`
                        : 'estimated'}
                  </span>
                </p>
              )}
              <p className="text-xs text-dark-textMuted">
                {p.updated_at ? `Updated ${fmtDate(p.updated_at)}` : p.created_at ? `Created ${fmtDate(p.created_at)}` : ''}
              </p>
            </button>
          ))}
        </div>
      )}

      <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
    </div>
  );
};

export default ProjectsPage;
