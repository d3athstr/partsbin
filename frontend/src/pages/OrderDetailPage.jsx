import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import orderService from '../services/orderService';
import { errMsg } from '../services/api';
import StatusChip from '../components/common/StatusChip';
import ComponentPicker from '../components/common/ComponentPicker';
import CreateComponentModal from '../components/orders/CreateComponentModal';
import { fmtDate, fmtMoney } from '../utils/format';
import { vendorOrderUrl } from '../utils/vendors';

const MatchStatusText = ({ status }) => {
  if (status === 'confirmed') return <span className="chip-neutral">confirmed</span>;
  if (status === 'ignored') return <span className="chip-neutral">ignored</span>;
  return <span className="chip-warn">{status || 'unmatched'}</span>;
};

const OrderDetailPage = () => {
  const { id } = useParams();
  const queryClient = useQueryClient();

  const [actionError, setActionError] = useState('');
  const [pickingItem, setPickingItem] = useState(null); // item being re-matched
  const [creatingItem, setCreatingItem] = useState(null); // item spawning a new component

  const { data, isLoading, error } = useQuery({
    queryKey: ['order', id],
    queryFn: () => orderService.get(id),
  });

  const order = data?.order || data || {};
  const items = data?.items || order.items || [];

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['order', id] });
    queryClient.invalidateQueries({ queryKey: ['orders'] });
    queryClient.invalidateQueries({ queryKey: ['reviewPending'] });
    queryClient.invalidateQueries({ queryKey: ['dashboard'] });
  };

  const itemMutation = useMutation({
    mutationFn: ({ itemId, payload }) => orderService.updateItem(id, itemId, payload),
    onSuccess: () => {
      invalidate();
      setActionError('');
    },
    onError: (err) => setActionError(errMsg(err, 'Item update failed')),
  });

  const createComponentMutation = useMutation({
    mutationFn: ({ itemId, overrides }) =>
      orderService.createComponentFromItem(id, itemId, overrides),
    onSuccess: () => {
      invalidate();
      queryClient.invalidateQueries({ queryKey: ['components'] });
      setCreatingItem(null);
      setActionError('');
    },
    onError: (err) => setActionError(errMsg(err, 'Failed to create component')),
  });

  const autoCreateMutation = useMutation({
    mutationFn: () => orderService.autoCreateComponents(id),
    onSuccess: (res) => {
      invalidate();
      queryClient.invalidateQueries({ queryKey: ['components'] });
      const failed = res?.failed?.length || 0;
      setActionError(
        failed ? `${failed} item${failed === 1 ? '' : 's'} could not be auto-created - match manually.` : ''
      );
    },
    onError: (err) => setActionError(errMsg(err, 'Auto-create failed')),
  });

  const ignoreMutation = useMutation({
    mutationFn: () => orderService.update(id, { status: 'ignored' }),
    onSuccess: () => {
      invalidate();
      setActionError('');
    },
    onError: (err) => setActionError(errMsg(err, 'Failed to ignore order')),
  });

  const receiveMutation = useMutation({
    mutationFn: () => orderService.receive(id),
    onSuccess: () => {
      invalidate();
      queryClient.invalidateQueries({ queryKey: ['components'] });
      setActionError('');
    },
    onError: (err) => setActionError(errMsg(err, 'Receive failed')),
  });

  if (isLoading) {
    return (
      <div className="flex justify-center py-16">
        <div className="w-10 h-10 border-4 border-dark-accent border-t-transparent rounded-full spinner"></div>
      </div>
    );
  }

  if (error) {
    return <div className="alert-error">Failed to load order: {error.message}</div>;
  }

  const unresolved = items.filter(
    (it) => it.match_status !== 'confirmed' && it.match_status !== 'ignored'
  );
  const allResolved = items.length > 0 && unresolved.length === 0;
  const isReceived = order.status === 'received';

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link to="/orders" className="link text-sm">
            ← Orders
          </Link>
          <div className="flex items-center gap-3 mt-1">
            <h1 className="capitalize">
              {order.vendor}{' '}
              {order.vendor_order_no &&
                (vendorOrderUrl(order.vendor, order.vendor_order_no) ? (
                  <a
                    href={vendorOrderUrl(order.vendor, order.vendor_order_no)}
                    target="_blank"
                    rel="noreferrer"
                    className="link font-mono text-xl"
                    title="Open the order on the vendor's site"
                  >
                    #{order.vendor_order_no}
                  </a>
                ) : (
                  <span className="font-mono text-xl">#{order.vendor_order_no}</span>
                ))}
            </h1>
            <StatusChip status={order.status} needsReview={!isReceived && unresolved.length > 0} />
          </div>
          {order.raw_subject && (
            <p className="text-dark-textMuted text-sm mt-1">{order.raw_subject}</p>
          )}
        </div>

        {!isReceived && (
          <div className="text-right">
            <div className="flex flex-wrap gap-2 justify-end">
              {order.status !== 'ignored' && (
                <button
                  onClick={() => ignoreMutation.mutate()}
                  disabled={ignoreMutation.isPending}
                  className="btn-secondary"
                  title="Hide this order - it will not affect stock"
                >
                  {ignoreMutation.isPending ? 'Ignoring...' : 'Ignore Order'}
                </button>
              )}
              {unresolved.length > 0 && (
                <button
                  onClick={() => autoCreateMutation.mutate()}
                  disabled={autoCreateMutation.isPending}
                  className="btn-secondary"
                  title="Claude infers a component (name, category, specs) for each pending item"
                >
                  {autoCreateMutation.isPending ? 'Asking Claude...' : 'Auto-create Components'}
                </button>
              )}
              <button
                onClick={() => receiveMutation.mutate()}
                disabled={!allResolved || receiveMutation.isPending}
                className="btn-primary"
              >
                {receiveMutation.isPending ? 'Receiving...' : 'Mark Received'}
              </button>
            </div>
            {!allResolved && (
              <p className="text-xs text-dark-warning mt-2 max-w-xs">
                {items.length === 0
                  ? 'No items on this order yet.'
                  : `${unresolved.length} item${unresolved.length === 1 ? '' : 's'} still need${
                      unresolved.length === 1 ? 's' : ''
                    } to be confirmed or ignored before receiving.`}
              </p>
            )}
          </div>
        )}
      </div>

      {actionError && <div className="alert-error">{actionError}</div>}

      {/* Order meta */}
      <div className="card">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
          <div>
            <p className="text-xs text-dark-textMuted uppercase tracking-wide">Ordered</p>
            <p className="mt-1">{fmtDate(order.order_date)}</p>
          </div>
          <div>
            <p className="text-xs text-dark-textMuted uppercase tracking-wide">Total</p>
            <p className="mt-1 tabular-nums">{fmtMoney(order.total)}</p>
          </div>
          <div>
            <p className="text-xs text-dark-textMuted uppercase tracking-wide">Gmail Account</p>
            <p className="mt-1 truncate">{order.gmail_account || '—'}</p>
          </div>
          <div>
            <p className="text-xs text-dark-textMuted uppercase tracking-wide">Tracking</p>
            {order.tracking_no ? (
              <p className="mt-1">
                {order.tracking_url ? (
                  <a
                    href={order.tracking_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="link font-mono text-xs"
                  >
                    {order.tracking_no}
                  </a>
                ) : (
                  <span className="font-mono text-xs">{order.tracking_no}</span>
                )}
                {order.carrier && (
                  <span className="text-dark-textMuted ml-1">({order.carrier})</span>
                )}
              </p>
            ) : (
              <p className="mt-1 text-dark-textMuted">—</p>
            )}
          </div>
        </div>
        {order.notes && (
          <p className="mt-4 p-3 bg-dark-elevated rounded text-sm text-dark-textMuted whitespace-pre-wrap">
            {order.notes}
          </p>
        )}
      </div>

      {/* Items / review queue */}
      <div className="card">
        <h2 className="text-lg font-semibold mb-4">Items</h2>
        {items.length === 0 ? (
          <p className="text-sm text-dark-textMuted">No items parsed for this order.</p>
        ) : (
          <div className="space-y-3">
            {items.map((item) => {
              const suggested = item.suggested_component || null;
              const confirmed = item.component || null;
              const resolved =
                item.match_status === 'confirmed' || item.match_status === 'ignored';

              return (
                <div
                  key={item.id}
                  className={`p-4 rounded-lg border ${
                    resolved
                      ? 'bg-dark-elevated border-dark-border'
                      : 'bg-dark-elevated border-dark-warning border-opacity-40'
                  }`}
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm font-medium break-words">
                        {item.raw_title}
                        {item.is_kit && (
                          <span className="ml-2 align-middle text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded border border-dark-border text-dark-textMuted">
                            kit
                          </span>
                        )}
                        {item.parent_item_id && (
                          <span className="ml-2 align-middle text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded border border-dark-border text-dark-textMuted">
                            kit part
                          </span>
                        )}
                      </p>
                      <p className="text-xs text-dark-textMuted mt-0.5 tabular-nums">
                        qty {item.qty ?? 1}
                        {item.unit_price != null && ` · ${fmtMoney(item.unit_price)} each`}
                      </p>
                    </div>
                    <MatchStatusText status={item.match_status} />
                  </div>

                  {/* Match state */}
                  <div className="mt-3">
                    {item.match_status === 'confirmed' && confirmed ? (
                      <p className="text-sm">
                        <span className="text-dark-textMuted">Matched to </span>
                        <Link to={`/inventory/${confirmed.id}`} className="link">
                          {confirmed.name}
                        </Link>
                      </p>
                    ) : item.match_status === 'ignored' ? (
                      <p className="text-sm text-dark-textMuted">
                        {item.is_kit
                          ? 'Kit — exploded into individual part items on this order.'
                          : 'Ignored — will not affect stock.'}
                      </p>
                    ) : (
                      <div className="space-y-2">
                        {suggested ? (
                          <p className="text-sm">
                            <span className="text-dark-textMuted">Suggested match: </span>
                            <Link to={`/inventory/${suggested.id}`} className="link">
                              {suggested.name}
                            </Link>
                            {suggested.mpn && (
                              <span className="text-dark-textMuted text-xs ml-2">
                                {suggested.mpn}
                              </span>
                            )}
                          </p>
                        ) : (
                          <p className="text-sm text-dark-textMuted">
                            No suggested match found.
                          </p>
                        )}

                        <div className="flex flex-wrap gap-2">
                          {suggested && (
                            <>
                              <button
                                onClick={() =>
                                  itemMutation.mutate({
                                    itemId: item.id,
                                    payload: { match_status: 'confirmed' },
                                  })
                                }
                                disabled={itemMutation.isPending}
                                className="btn-primary text-sm py-1.5"
                              >
                                Accept Match
                              </button>
                              <button
                                onClick={() =>
                                  itemMutation.mutate({
                                    itemId: item.id,
                                    payload: {
                                      match_status: 'unmatched',
                                      clear_suggestion: true,
                                    },
                                  })
                                }
                                disabled={itemMutation.isPending}
                                className="btn-secondary text-sm py-1.5"
                              >
                                Not a Match
                              </button>
                            </>
                          )}
                          <button
                            onClick={() => setPickingItem(item)}
                            className="btn-secondary text-sm py-1.5"
                          >
                            Pick Component...
                          </button>
                          <button
                            onClick={() => setCreatingItem(item)}
                            className="btn-secondary text-sm py-1.5"
                          >
                            Create New Component
                          </button>
                          <button
                            onClick={() =>
                              itemMutation.mutate({
                                itemId: item.id,
                                payload: { match_status: 'ignored' },
                              })
                            }
                            disabled={itemMutation.isPending}
                            className="btn-secondary text-sm py-1.5"
                          >
                            Ignore
                          </button>
                        </div>
                        {isReceived && (
                          <p className="text-xs text-dark-textMuted">
                            This order was already received — matching this item
                            will add its stock.
                          </p>
                        )}
                      </div>
                    )}

                    {/* Resolved items can be re-matched or undone at any time;
                        on received orders the backend moves stock to match. */}
                    {resolved && (
                      <div className="mt-2 flex flex-wrap items-center gap-3">
                        <button
                          onClick={() => setPickingItem(item)}
                          className="text-xs text-dark-textMuted hover:text-dark-text underline"
                        >
                          change match
                        </button>
                        <button
                          onClick={() =>
                            itemMutation.mutate({
                              itemId: item.id,
                              payload: { match_status: 'unmatched' },
                            })
                          }
                          disabled={itemMutation.isPending}
                          className="text-xs text-dark-textMuted hover:text-dark-text underline"
                        >
                          {item.match_status === 'ignored' ? 'un-ignore' : 'undo match'}
                        </button>
                        {isReceived && item.match_status === 'confirmed' && (
                          <span className="text-xs text-dark-textMuted">
                            (stock adjusts on change/undo)
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {isReceived && (
        <p className="text-sm text-dark-textMuted">
          This order has been received; confirmed items were added to stock.
        </p>
      )}

      {/* Pick-different-component modal */}
      {pickingItem && (
        <ComponentPicker
          title={`Match: ${pickingItem.raw_title?.slice(0, 60) || 'item'}`}
          onClose={() => setPickingItem(null)}
          onSelect={(component) => {
            itemMutation.mutate({
              itemId: pickingItem.id,
              payload: { component_id: component.id, match_status: 'confirmed' },
            });
            setPickingItem(null);
          }}
        />
      )}

      {/* Create-new-component modal */}
      {creatingItem && (
        <CreateComponentModal
          item={creatingItem}
          busy={createComponentMutation.isPending}
          onClose={() => setCreatingItem(null)}
          onSubmit={async (overrides) => {
            await createComponentMutation.mutateAsync({
              itemId: creatingItem.id,
              overrides,
            });
          }}
        />
      )}
    </div>
  );
};

export default OrderDetailPage;
