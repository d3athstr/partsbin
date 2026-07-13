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
  const border = tone === 'alarm' ? 'border-l-dark-error' : 'border-l-dark-warning';
  const heading = tone === 'alarm' ? 'text-dark-error' : 'text-dark-warning';

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
                </div>
                <QtyText qty={c.qty_on_hand} minQty={c.min_qty} />
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
  const lowStock = data?.low_stock || [];
  const pendingReview = data?.pending_review ?? 0;
  const recentOrders = data?.recent_orders || [];
  const ingest = data?.ingest || [];
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
      </div>

      <div className="grid lg:grid-cols-3 gap-6">
        {/* Recent orders */}
        <div className="card lg:col-span-2">
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

        {/* Gmail ingest / token status */}
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold">Email Ingest</h2>
            <Link to="/settings" className="link text-sm">
              Manage
            </Link>
          </div>
          {ingest.length === 0 ? (
            <p className="text-sm text-dark-textMuted">No Gmail accounts configured.</p>
          ) : (
            <ul className="space-y-3">
              {ingest.map((acct, i) => (
                <li key={acct.email || acct.account || i} className="p-3 bg-dark-elevated rounded">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium truncate">
                      {acct.email || acct.account || acct.user}
                    </p>
                    <TokenStatus status={acct.token_status ?? acct.token} />
                  </div>
                  <p className="text-xs text-dark-textMuted mt-1">
                    Last poll: {fmtDateTime(acct.last_poll)}
                  </p>
                  {acct.last_error && (
                    <p className="text-xs text-dark-error mt-1 break-words">{acct.last_error}</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
