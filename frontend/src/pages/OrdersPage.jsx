import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import orderService from '../services/orderService';
import Pagination from '../components/common/Pagination';
import StatusChip from '../components/common/StatusChip';
import { fmtDate, fmtMoney } from '../utils/format';
import { vendorOrderUrl } from '../utils/vendors';

const PER_PAGE = 25;
const STATUSES = ['ordered', 'shipped', 'delivered', 'received', 'ignored'];
const VENDORS = ['amazon', 'aliexpress', 'adafruit', 'mouser', 'digikey', 'seeed', 'rokland', 'jlcpcb', 'pololu', 'ebay', 'polycase', 'onlinemetals', 'yakima', 'other'];

/**
 * An order "needs review" when any of its items still needs a human
 * match decision, or the order is delivered but not yet received.
 */
const orderNeedsReview = (o) => {
  if (o.needs_review !== undefined) return !!o.needs_review;
  if (o.pending_items !== undefined) return o.pending_items > 0;
  return false;
};

const OrdersPage = () => {
  const navigate = useNavigate();
  const [status, setStatus] = useState('');
  const [vendor, setVendor] = useState('');
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState('created_at');
  const [sortOrder, setSortOrder] = useState('desc');
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');

  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedSearch(search.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [search]);

  const toggleSort = (key) => {
    if (sort === key) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSort(key);
      setSortOrder(key === 'vendor' || key === 'status' ? 'asc' : 'desc');
    }
    setPage(1);
  };

  const SortHeader = ({ sortKey, className = '', children }) => (
    <th
      className={`py-2 px-3 font-medium cursor-pointer select-none hover:text-dark-text ${className}`}
      onClick={() => toggleSort(sortKey)}
      title="Sort by this column"
    >
      {children}
      {sort === sortKey && (
        <span className="ml-1">{sortOrder === 'asc' ? '\u25b4' : '\u25be'}</span>
      )}
    </th>
  );

  const { data, isLoading, error } = useQuery({
    queryKey: ['orders', status, vendor, page, sort, sortOrder, debouncedSearch],
    queryFn: () =>
      orderService.list({ status, vendor, page, per_page: PER_PAGE, sort, order: sortOrder, q: debouncedSearch }),
    placeholderData: (prev) => prev,
  });

  const { data: pendingData } = useQuery({
    queryKey: ['reviewPending'],
    queryFn: () => orderService.pendingReview(),
  });

  // Order ids needing review, from the review queue endpoint
  const pendingOrderIds = new Set(
    (pendingData?.items || []).map((it) => it.order_id ?? it.id)
  );

  const items = data?.items || [];
  const total = data?.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / (data?.per_page || PER_PAGE)));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1>Orders</h1>
        {(pendingData?.count ?? 0) > 0 && (
          <span className="chip-warn">{pendingData.count} pending review</span>
        )}
      </div>

      <div className="card p-4 flex flex-col sm:flex-row gap-3">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search orders, items, order #..."
          className="input sm:flex-1"
        />
        <select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setPage(1);
          }}
          className="input sm:w-48"
        >
          <option value="">Active (needs action)</option>
          <option value="all">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select
          value={vendor}
          onChange={(e) => {
            setVendor(e.target.value);
            setPage(1);
          }}
          className="input sm:w-48"
        >
          <option value="">All vendors</option>
          {VENDORS.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
        <span className="text-sm text-dark-textMuted sm:ml-auto self-center tabular-nums">
          {total} order{total === 1 ? '' : 's'}
        </span>
      </div>

      {error && <div className="alert-error">Failed to load orders: {error.message}</div>}

      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-dark-border bg-dark-elevated text-dark-textMuted">
                <SortHeader sortKey="vendor" className="text-left">Vendor</SortHeader>
                <SortHeader sortKey="vendor_order_no" className="text-left">Order #</SortHeader>
                <SortHeader sortKey="order_date" className="text-left hidden sm:table-cell">Date</SortHeader>
                <th className="text-left py-2 px-3 font-medium hidden md:table-cell">Subject</th>
                <SortHeader sortKey="total" className="text-right hidden sm:table-cell">Total</SortHeader>
                <SortHeader sortKey="status" className="text-left">Status</SortHeader>
              </tr>
            </thead>
            <tbody>
              {isLoading && items.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-10 text-center text-dark-textMuted">
                    Loading...
                  </td>
                </tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-10 text-center text-dark-textMuted">
                    No orders found.
                  </td>
                </tr>
              ) : (
                items.map((o) => (
                  <tr
                    key={o.id}
                    onClick={() => navigate(`/orders/${o.id}`)}
                    className="border-b border-dark-border last:border-b-0 hover:bg-dark-elevated cursor-pointer"
                  >
                    <td className="py-2.5 px-3 capitalize">{o.vendor}</td>
                    <td className="py-2.5 px-3 font-mono text-xs">
                      {vendorOrderUrl(o.vendor, o.vendor_order_no) ? (
                        <a
                          href={vendorOrderUrl(o.vendor, o.vendor_order_no)}
                          target="_blank"
                          rel="noreferrer"
                          className="link"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {o.vendor_order_no}
                        </a>
                      ) : (
                        o.vendor_order_no || '—'
                      )}
                    </td>
                    <td className="py-2.5 px-3 text-dark-textMuted hidden sm:table-cell">
                      {fmtDate(o.order_date)}
                    </td>
                    <td className="py-2.5 px-3 text-dark-textMuted hidden md:table-cell max-w-xs truncate">
                      {o.raw_subject || '—'}
                    </td>
                    <td className="py-2.5 px-3 text-right tabular-nums hidden sm:table-cell">
                      {fmtMoney(o.total)}
                    </td>
                    <td className="py-2.5 px-3">
                      <StatusChip
                        status={o.status}
                        needsReview={orderNeedsReview(o) || pendingOrderIds.has(o.id)}
                      />
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
    </div>
  );
};

export default OrdersPage;
