import { useState } from 'react';
import { Link, useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import componentService from '../services/componentService';
import { errMsg } from '../services/api';
import QtyText from '../components/common/QtyText';
import { fmtDate, fmtDateTime, fmtMoney } from '../utils/format';
import { vendorOrderUrl } from '../utils/vendors';
import StatusChip from '../components/common/StatusChip';

const nameOf = (x) => (typeof x === 'string' ? x : x?.name);

const REASON_LABELS = {
  initial: 'Initial stock',
  order_received: 'Order received',
  project_use: 'Project use',
  adjustment: 'Adjustment',
};

const ComponentDetailPage = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [delta, setDelta] = useState('');
  const [note, setNote] = useState('');
  const [actionError, setActionError] = useState('');
  const [enrichNote, setEnrichNote] = useState('');
  const [showLookup, setShowLookup] = useState(false);
  const [lookupQuery, setLookupQuery] = useState('');
  const [candidates, setCandidates] = useState(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ['component', id],
    queryFn: () => componentService.get(id),
  });

  // Defensive: backend may return the component flat or nested
  const component = data?.component || data || {};
  const transactions = data?.transactions || component.transactions || [];
  const usedIn = data?.used_in || component.used_in || [];
  const orders = data?.orders || component.orders || [];

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['component', id] });
    queryClient.invalidateQueries({ queryKey: ['components'] });
    queryClient.invalidateQueries({ queryKey: ['dashboard'] });
  };

  const adjustMutation = useMutation({
    mutationFn: ({ d, n }) => componentService.adjust(id, d, n),
    onSuccess: () => {
      invalidate();
      setDelta('');
      setNote('');
      setActionError('');
    },
    onError: (err) => setActionError(errMsg(err, 'Adjustment failed')),
  });

  const deleteMutation = useMutation({
    mutationFn: () => componentService.remove(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['components'] });
      navigate('/inventory');
    },
    onError: (err) => setActionError(errMsg(err, 'Delete failed')),
  });

  const handleAdjust = (e) => {
    e.preventDefault();
    const d = parseInt(delta, 10);
    if (!d) {
      setActionError('Enter a non-zero adjustment (e.g. 5 or -3)');
      return;
    }
    adjustMutation.mutate({ d, n: note });
  };

  const enrichMutation = useMutation({
    mutationFn: () => componentService.enrich(id),
    onSuccess: (res) => {
      invalidate();
      setActionError('');
      const r = res?.enriched || {};
      const found = [
        r.image && 'image',
        r.datasheet && 'datasheet',
        r.manufacturer && 'manufacturer',
        r.mpn && 'part number',
        r.description && 'description',
        r.specs > 0 && `${r.specs} spec${r.specs === 1 ? '' : 's'}`,
      ].filter(Boolean);
      setEnrichNote(
        found.length
          ? `Enrichment added: ${found.join(', ')}.`
          : 'Nothing new found on the web for this component.'
      );
    },
    onError: (err) => {
      setEnrichNote('');
      setActionError(errMsg(err, 'Enrichment failed'));
    },
  });

  const lookupMutation = useMutation({
    mutationFn: (query) => componentService.lookup(id, query),
    onSuccess: (res) => {
      setCandidates(res?.candidates || []);
      setActionError('');
    },
    onError: (err) => setActionError(errMsg(err, 'Lookup failed')),
  });

  const applyCandidateMutation = useMutation({
    mutationFn: (candidate) => componentService.applyCandidate(id, candidate),
    onSuccess: (res) => {
      invalidate();
      const r = res?.applied || {};
      const changed = [
        r.image && 'image',
        r.datasheet && 'datasheet',
        r.manufacturer && 'manufacturer',
        r.mpn && 'part number',
        r.description && 'description',
        r.specs > 0 && `${r.specs} spec${r.specs === 1 ? '' : 's'}`,
      ].filter(Boolean);
      setEnrichNote(changed.length ? `Applied: ${changed.join(', ')}.` : 'Candidate had nothing new to apply.');
      setShowLookup(false);
      setCandidates(null);
      setActionError('');
    },
    onError: (err) => setActionError(errMsg(err, 'Failed to apply candidate')),
  });

  const handleLookup = (e) => {
    e.preventDefault();
    setCandidates(null);
    lookupMutation.mutate(lookupQuery.trim());
  };

  const openLookup = () => {
    setLookupQuery(component.name || '');
    setCandidates(null);
    setShowLookup(true);
  };

  const handleDelete = () => {
    if (window.confirm(`Delete "${component.name}"? This cannot be undone.`)) {
      deleteMutation.mutate();
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
    return <div className="alert-error">Failed to load component: {error.message}</div>;
  }

  const specs = component.specs || {};

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link to="/inventory" className="link text-sm">
            ← Inventory
          </Link>
          <h1 className="mt-1">{component.name}</h1>
          <p className="text-dark-textMuted text-sm mt-1">
            {[component.category, component.manufacturer, component.mpn]
              .filter(Boolean)
              .join(' · ')}
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={openLookup} className="btn-secondary" title="Web-search this part with your own terms and pick from candidate matches">
            Look Up
          </button>
          <button
            onClick={() => enrichMutation.mutate()}
            disabled={enrichMutation.isPending}
            className="btn-secondary"
            title="Search the web for an image, datasheet, and missing specs (never overwrites existing data)"
          >
            {enrichMutation.isPending ? 'Searching web...' : 'Enrich'}
          </button>
          <Link to={`/inventory/${id}/edit`} className="btn-secondary">
            Edit
          </Link>
          <button
            onClick={handleDelete}
            disabled={deleteMutation.isPending}
            className="btn-danger"
          >
            Delete
          </button>
        </div>
      </div>

      {actionError && <div className="alert-error">{actionError}</div>}
      {enrichNote && (
        <div className="card py-2 px-3 text-sm text-dark-textMuted">{enrichNote}</div>
      )}

      {showLookup && (
        <div className="card space-y-4">
          <form onSubmit={handleLookup} className="flex flex-col sm:flex-row gap-3">
            <input
              type="text"
              autoFocus
              value={lookupQuery}
              onChange={(e) => setLookupQuery(e.target.value)}
              placeholder="Search terms, e.g. part number, brand, connector type..."
              className="input flex-1"
            />
            <button type="submit" disabled={lookupMutation.isPending} className="btn-primary">
              {lookupMutation.isPending ? 'Searching...' : 'Search'}
            </button>
            <button
              type="button"
              onClick={() => { setShowLookup(false); setCandidates(null); }}
              className="btn-secondary"
            >
              Close
            </button>
          </form>
          {lookupMutation.isPending && (
            <p className="text-xs text-dark-textMuted">
              Claude is searching the web - this takes 10-30 seconds.
            </p>
          )}
          {candidates && candidates.length === 0 && (
            <p className="text-sm text-dark-textMuted">No candidates found - try different terms.</p>
          )}
          {candidates && candidates.length > 0 && (
            <div className="space-y-3">
              {candidates.map((cand, i) => (
                <div key={i} className="flex gap-4 p-3 bg-dark-elevated rounded-lg items-start">
                  {cand.image_urls?.[0] && (
                    <img
                      src={cand.image_urls[0]}
                      alt=""
                      className="w-16 h-16 object-contain rounded bg-dark-bg flex-shrink-0"
                      onError={(e) => { e.target.style.display = 'none'; }}
                    />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">{cand.title}</p>
                    <p className="text-xs text-dark-textMuted">
                      {[cand.manufacturer, cand.mpn].filter(Boolean).join(' · ')}
                    </p>
                    {cand.description && (
                      <p className="text-sm text-dark-textMuted mt-1">{cand.description}</p>
                    )}
                    <p className="text-xs mt-1 space-x-3">
                      {cand.source_url && (
                        <a href={cand.source_url} target="_blank" rel="noreferrer" className="link">
                          source page
                        </a>
                      )}
                      {cand.datasheet_url && (
                        <a href={cand.datasheet_url} target="_blank" rel="noreferrer" className="link">
                          datasheet
                        </a>
                      )}
                    </p>
                  </div>
                  <button
                    onClick={() => applyCandidateMutation.mutate(cand)}
                    disabled={applyCandidateMutation.isPending}
                    className="btn-primary flex-shrink-0"
                  >
                    {applyCandidateMutation.isPending ? 'Applying...' : 'Apply'}
                  </button>
                </div>
              ))}
              <p className="text-xs text-dark-textMuted">
                Apply replaces the image and datasheet with the candidate's, fills empty
                manufacturer / part number / description, and merges new specs. Your
                component name and stock are never changed.
              </p>
            </div>
          )}
        </div>
      )}

      <div className="grid lg:grid-cols-3 gap-6">
        {/* Left column: image + stock */}
        <div className="space-y-6">
          <div className="card">
            {component.image_url || component.image ? (
              <img
                src={component.image_url || `/uploads/${component.image}`}
                alt={component.name}
                className="w-full rounded-lg object-contain max-h-64 bg-dark-bg"
              />
            ) : (
              <div className="flex items-center justify-center h-40 bg-dark-elevated rounded-lg text-dark-textMuted text-sm">
                No image
              </div>
            )}
          </div>

          <div className="card">
            <h2 className="text-lg font-semibold mb-3">Stock</h2>
            <div className="flex items-baseline gap-2 mb-1">
              <QtyText
                qty={component.qty_on_hand}
                minQty={component.min_qty}
                className="!text-3xl"
              />
              <span className="text-dark-textMuted text-sm">on hand</span>
            </div>
            <p className="text-sm text-dark-textMuted mb-4">
              Minimum: {component.min_qty ?? 0}
              {component.location && <> · Location: {component.location}</>}
            </p>

            <form onSubmit={handleAdjust} className="space-y-2">
              <div className="flex gap-2">
                <input
                  type="number"
                  value={delta}
                  onChange={(e) => setDelta(e.target.value)}
                  placeholder="± qty"
                  className="input w-28"
                />
                <input
                  type="text"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="Note (optional)"
                  className="input flex-1"
                />
              </div>
              <button
                type="submit"
                disabled={adjustMutation.isPending}
                className="btn-secondary w-full"
              >
                {adjustMutation.isPending ? 'Adjusting...' : 'Adjust Stock'}
              </button>
            </form>
          </div>

          {/* Used in projects */}
          <div className="card">
            <h2 className="text-lg font-semibold mb-3">Used In</h2>
            {usedIn.length === 0 ? (
              <p className="text-sm text-dark-textMuted">Not used in any projects.</p>
            ) : (
              <ul className="space-y-1">
                {usedIn.map((p) => (
                  <li key={p.id}>
                    <Link to={`/projects/${p.id}`} className="link text-sm">
                      {p.name}
                    </Link>
                    {p.status && (
                      <span className="chip-neutral ml-2">{p.status}</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        {/* Right column: details + history */}
        <div className="lg:col-span-2 space-y-6">
          <div className="card">
            <h2 className="text-lg font-semibold mb-3">Details</h2>
            {component.description && (
              <p className="text-sm mb-4">{component.description}</p>
            )}

            <div className="grid sm:grid-cols-2 gap-x-6 gap-y-2 text-sm">
              {Object.entries(specs).map(([key, value]) => (
                <div key={key} className="flex justify-between gap-3 py-1 border-b border-dark-border">
                  <span className="text-dark-textMuted">{key}</span>
                  <span className="text-right break-all">{String(value)}</span>
                </div>
              ))}
              {Object.keys(specs).length === 0 && (
                <p className="text-dark-textMuted">No specs recorded.</p>
              )}
            </div>

            <div className="flex flex-wrap gap-1 mt-4">
              {(component.tags || []).map((t) => (
                <span key={nameOf(t)} className="chip-neutral">
                  {nameOf(t)}
                </span>
              ))}
            </div>

            {component.datasheet_url && (
              <a
                href={component.datasheet_url}
                target="_blank"
                rel="noopener noreferrer"
                className="link inline-flex items-center gap-1 text-sm mt-4"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                Datasheet
              </a>
            )}

            {component.notes && (
              <div className="mt-4 p-3 bg-dark-elevated rounded text-sm text-dark-textMuted whitespace-pre-wrap">
                {component.notes}
              </div>
            )}
          </div>

          {/* Order history */}
          {orders.length > 0 && (
            <div className="card">
              <h2 className="text-lg font-semibold mb-3">Orders</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-dark-border text-dark-textMuted">
                      <th className="text-left py-2 pr-3 font-medium">Date</th>
                      <th className="text-left py-2 pr-3 font-medium">Vendor</th>
                      <th className="text-left py-2 pr-3 font-medium hidden sm:table-cell">Order #</th>
                      <th className="text-right py-2 pr-3 font-medium">Qty</th>
                      <th className="text-right py-2 pr-3 font-medium hidden sm:table-cell">Unit $</th>
                      <th className="text-left py-2 font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {orders.map((o, i) => (
                      <tr key={i} className="border-b border-dark-border last:border-b-0">
                        <td className="py-2 pr-3 text-dark-textMuted whitespace-nowrap">
                          {fmtDate(o.order_date)}
                        </td>
                        <td className="py-2 pr-3 capitalize">
                          <Link to={`/orders/${o.order_id}`} className="link">
                            {o.vendor}
                          </Link>
                        </td>
                        <td className="py-2 pr-3 font-mono text-xs hidden sm:table-cell">
                          {vendorOrderUrl(o.vendor, o.vendor_order_no) ? (
                            <a
                              href={vendorOrderUrl(o.vendor, o.vendor_order_no)}
                              target="_blank"
                              rel="noreferrer"
                              className="link"
                            >
                              {o.vendor_order_no}
                            </a>
                          ) : (
                            o.vendor_order_no || '—'
                          )}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums">{o.qty}</td>
                        <td className="py-2 pr-3 text-right tabular-nums hidden sm:table-cell">
                          {o.unit_price != null ? fmtMoney(o.unit_price) : '—'}
                        </td>
                        <td className="py-2">
                          <StatusChip status={o.status} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Stock history */}
          <div className="card">
            <h2 className="text-lg font-semibold mb-3">Stock History</h2>
            {transactions.length === 0 ? (
              <p className="text-sm text-dark-textMuted">No transactions yet.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-dark-border text-dark-textMuted">
                      <th className="text-left py-2 pr-3 font-medium">When</th>
                      <th className="text-right py-2 pr-3 font-medium">Δ</th>
                      <th className="text-left py-2 pr-3 font-medium">Reason</th>
                      <th className="text-left py-2 pr-3 font-medium hidden sm:table-cell">Note</th>
                      <th className="text-left py-2 font-medium hidden md:table-cell">By</th>
                    </tr>
                  </thead>
                  <tbody>
                    {transactions.map((t) => (
                      <tr key={t.id} className="border-b border-dark-border last:border-b-0">
                        <td className="py-2 pr-3 text-dark-textMuted whitespace-nowrap">
                          {fmtDateTime(t.timestamp || t.created_at)}
                        </td>
                        <td
                          className={`py-2 pr-3 text-right tabular-nums ${
                            t.delta < 0 ? 'text-dark-textMuted' : ''
                          }`}
                        >
                          {t.delta > 0 ? `+${t.delta}` : t.delta}
                        </td>
                        <td className="py-2 pr-3">{REASON_LABELS[t.reason] || t.reason}</td>
                        <td className="py-2 pr-3 text-dark-textMuted hidden sm:table-cell">
                          {t.note || '—'}
                        </td>
                        <td className="py-2 text-dark-textMuted hidden md:table-cell">
                          {t.user || t.username || '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default ComponentDetailPage;
