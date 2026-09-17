import { Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import dashboardService from '../services/dashboardService';
import StatusChip from '../components/common/StatusChip';
import QtyText from '../components/common/QtyText';
import { fmtDate, fmtDateTime } from '../utils/format';

/**
 * Exception-first dashboard (ISA-101 / HP-HMI):
 * healthy = plain gray; only abnormal states get color.
 */

const TokenStatus = ({ status }) => {
  const s = (status || 'unknown').toLowerCase();
  if (s === 'ok' || s === 'valid') {
    return <span className="text-sm text-dark-textMuted">token OK</span>;
  }
  if (s === 'missing') {
    return <span className="chip-warn">token missing</span>;
  }
  return <span className="chip-alarm">token {s}</span>;
};

const ExceptionList = ({ title, items, tone, emptyText }) => {
  // ISA-101: colour means an operator decision is owed. 'muted' is for states
  // that are merely informational — an already-ordered part is not a fault, so
  // it gets no alarm colour at all.
  const border =
    tone === 'alarm' ? 'border-l-dark-error'
    : tone === 'warn' ? 'border-l-dark-warning'
    : 'border-l-dark-border';
  const heading =
    tone === 'alarm' ? 'text-dark-error'
    : tone === 'warn' ? 'text-dark-warning'
    : 'text-dark-textMuted';

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <h2 className={`text-lg font-semibold ${items.length > 0 ? heading : 'text-dark-textMuted'}`}>
          {title}
        </h2>
        <span className="text-sm text-dark-textMuted tabular-nums">{items.length}</span>
      </div>
      {items.length === 0 ? (
        <p className="text-sm text-dark-textMuted">{emptyText}</p>
      ) : (
        <ul className="space-y-2">
          {items.map((c) => (
            <li key={c.id}>
              <Link
                to={`/inventory/${c.id}`}
                className={`flex items-center justify-between gap-3 px-3 py-2 bg-dark-elevated rounded border-l-4 ${border} hover:bg-dark-bg transition-colors`}
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate">{c.name}</p>
                  <p className="text-xs text-dark-textMuted truncate">
                    {[c.category, c.location].filter(Boolean).join(' · ')}
                  </p>
                  {c.projects?.length > 0 && (
                    <p className="text-xs text-dark-textMuted truncate mt-0.5">
                      for {c.projects.join(', ')}
                    </p>
                  )}
                </div>
                <QtyText qty={c.qty_on_hand} minQty={c.min_qty} qtyOnOrder={c.qty_on_order} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

const Dashboard = () => {
  const navigate = useNavigate();
  const { data, isLoading, error } = useQuery({
    queryKey: ['dashboard'],
    queryFn: () => dashboardService.get(),
  });

  if (isLoading) {
    return (
      <div className="flex justify-center py-16">
        <div className="w-10 h-10 border-4 border-dark-accent border-t-transparent rounded-full spinner"></div>
      </div>
    );
  }

  if (error) {
    return <div className="alert-error">Failed to load dashboard: {error.message}</div>;
  }

  const outOfStock = data?.out_of_stock || [];
  const onOrder = data?.on_order || [];
  const lowStock = data?.low_stock || [];
  const pendingReview = data?.pending_review ?? 0;
  const recentOrders = data?.recent_orders || [];
  const ingest = data?.ingest || [];
  // The routine "everything is fine" ingest panel is gone — mail now arrives at
  // the dedicated mailbox, so per-account Gmail token chatter is not news.
  // What must never be silent is a source that has STOPPED working: a dead
  // Gmail token cost two days of orders in August and nobody noticed. So this
  // surfaces on fault only — invisible when healthy, loud when not.
  const ingestFaults = ingest.filter((src) =>
    src.source === 'imap'
      ? src.state !== 'ok'
      : (src.token ?? src.token_status) !== 'ok' || !!src.last_error
  );
  const totals = data?.totals || {};

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1>Dashboard</h1>
      </div>

      {/* Totals row — plain gray, informational */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className="card py-4">
          <p className="text-xs uppercase tracking-wide text-dark-textMuted">Components</p>
          <p className="text-2xl font-semibold tabular-nums mt-1">{totals.components ?? '—'}</p>
        </div>
        <div className="card py-4">
          <p className="text-xs uppercase tracking-wide text-dark-textMuted">Projects</p>
          <p className="text-2xl font-semibold tabular-nums mt-1">{totals.projects ?? '—'}</p>
        </div>
        <div className="card py-4">
          <p className="text-xs uppercase tracking-wide text-dark-textMuted">Orders</p>
          <p className="text-2xl font-semibold tabular-nums mt-1">{totals.orders ?? '—'}</p>
        </div>
        <Link to="/orders" className="card py-4 hover:bg-dark-elevated transition-colors">
          <p className="text-xs uppercase tracking-wide text-dark-textMuted">Pending Review</p>
          <p
            className={`text-2xl font-semibold tabular-nums mt-1 ${
              pendingReview > 0 ? 'text-dark-warning' : 'text-dark-textMuted'
            }`}
          >
            {pendingReview}
          </p>
        </Link>
      </div>

      {/* Exceptions */}
      <div className="grid md:grid-cols-2 gap-6">
        <ExceptionList
          title="Out of Stock"
          items={outOfStock}
          tone="alarm"
          emptyText="No components out of stock."
        />
        <ExceptionList
          title="Low Stock"
          items={lowStock}
          tone="warn"
          emptyText="No components below minimum."
        />
        <ExceptionList
          title="On Order"
          items={onOrder}
          tone="muted"
          emptyText="Nothing on order."
        />
      </div>

      <div className={`grid gap-6 ${ingestFaults.length > 0 ? 'lg:grid-cols-3' : ''}`}>
        {/* Recent orders — takes the full width when no fault card sits beside it */}
        <div className={`card ${ingestFaults.length > 0 ? 'lg:col-span-2' : ''}`}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold">Recent Orders</h2>
            <Link to="/orders" className="link text-sm">
              View all
            </Link>
          </div>
          {recentOrders.length === 0 ? (
            <p className="text-sm text-dark-textMuted">No recent orders.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-dark-border text-dark-textMuted">
                    <th className="text-left py-2 pr-3 font-medium">Vendor</th>
                    <th className="text-left py-2 pr-3 font-medium">Order #</th>
                    <th className="text-left py-2 pr-3 font-medium">Date</th>
                    <th className="text-left py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {recentOrders.map((o) => (
                    <tr
                      key={o.id}
                      className="border-b border-dark-border last:border-b-0 hover:bg-dark-elevated cursor-pointer"
                      onClick={() => navigate(`/orders/${o.id}`)}
                    >
                      <td className="py-2 pr-3 capitalize">{o.vendor}</td>
                      <td className="py-2 pr-3 font-mono text-xs">{o.vendor_order_no || '—'}</td>
                      <td className="py-2 pr-3 text-dark-textMuted">{fmtDate(o.order_date)}</td>
                      <td className="py-2">
                        <StatusChip status={o.status} needsReview={!!o.needs_review} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Ingest health — rendered ONLY when a source is failing */}
        {ingestFaults.length > 0 && (
          <div className="card border-l-4 border-l-dark-error">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-dark-error">Ingest Fault</h2>
              <Link to="/settings" className="link text-sm">
                Manage
              </Link>
            </div>
            <ul className="space-y-3">
              {ingestFaults.map((src, i) => (
                <li key={src.email || src.account || i} className="p-3 bg-dark-elevated rounded">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium truncate">
                      {src.source === 'imap' ? 'mailbox: ' + src.user : src.email || src.account}
                    </p>
                    <TokenStatus
                      status={src.source === 'imap' ? src.state : src.token ?? src.token_status}
                    />
                  </div>
                  {src.last_poll && (
                    <p className="text-xs text-dark-textMuted mt-1">
                      Last poll: {fmtDateTime(src.last_poll)}
                    </p>
                  )}
                  {(src.last_error || src.error) && (
                    <p className="text-xs text-dark-error mt-1 break-words">
                      {src.last_error || src.error}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
};

export default Dashboard;
