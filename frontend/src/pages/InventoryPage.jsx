import { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import componentService from '../services/componentService';
import { asList, errMsg } from '../services/api';
import Pagination from '../components/common/Pagination';
import QtyText from '../components/common/QtyText';

const PER_PAGE = 25;

const nameOf = (x) => (typeof x === 'string' ? x : x?.name);

const SortHeader = ({ label, field, sort, order, onSort, className = '' }) => (
  <th
    className={`sortable text-left py-2 px-3 font-medium text-dark-textMuted ${className}`}
    onClick={() => onSort(field)}
  >
    {label}
    {sort === field && <span className="ml-1">{order === 'asc' ? '▲' : '▼'}</span>}
  </th>
);

const InventoryPage = () => {
  const navigate = useNavigate();
  const [showUrlModal, setShowUrlModal] = useState(false);
  const [productUrl, setProductUrl] = useState('');
  const [urlBusy, setUrlBusy] = useState(false);
  const [urlError, setUrlError] = useState('');

  const handleFromUrl = async (e) => {
    e.preventDefault();
    setUrlBusy(true);
    setUrlError('');
    try {
      const data = await componentService.fromUrl(productUrl.trim());
      setShowUrlModal(false);
      setProductUrl('');
      navigate('/inventory/new', { state: { draft: data.draft } });
    } catch (err) {
      setUrlError(errMsg(err, 'Could not read that product page'));
    } finally {
      setUrlBusy(false);
    }
  };
  const queryClient = useQueryClient();

  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [category, setCategory] = useState('');
  const [tag, setTag] = useState('');
  const [location, setLocation] = useState('');
  const [lowStock, setLowStock] = useState(false);
  const [outOfStock, setOutOfStock] = useState(false);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState('name');
  const [order, setOrder] = useState('asc');
  const [actionError, setActionError] = useState('');

  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedSearch(search);
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [search]);

  const params = {
    search: debouncedSearch,
    category,
    tag,
    location,
    low_stock: lowStock ? 1 : undefined,
    out_of_stock: outOfStock ? 1 : undefined,
    page,
    per_page: PER_PAGE,
    sort,
    order,
  };

  const { data, isLoading, error } = useQuery({
    queryKey: ['components', params],
    queryFn: () => componentService.list(params),
    placeholderData: (prev) => prev,
  });

  const { data: categoriesData } = useQuery({
    queryKey: ['categories'],
    queryFn: () => componentService.categories(),
    staleTime: Infinity,
  });
  const { data: tagsData } = useQuery({
    queryKey: ['tags'],
    queryFn: () => componentService.tags(),
  });
  const { data: locationsData } = useQuery({
    queryKey: ['locations'],
    queryFn: () => componentService.locations(),
  });

  const categories = asList(categoriesData, 'categories');
  const tags = asList(tagsData, 'tags');
  const locations = asList(locationsData, 'locations');

  const adjustMutation = useMutation({
    mutationFn: ({ id, delta }) => componentService.adjust(id, delta),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['components'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      setActionError('');
    },
    onError: (err) => setActionError(errMsg(err, 'Stock adjustment failed')),
  });

  const handleSort = (field) => {
    if (sort === field) {
      setOrder(order === 'asc' ? 'desc' : 'asc');
    } else {
      setSort(field);
      setOrder('asc');
    }
    setPage(1);
  };

  const items = data?.items || [];
  const total = data?.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / (data?.per_page || PER_PAGE)));

  const setFilter = (setter) => (e) => {
    setter(e.target.value);
    setPage(1);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1>Inventory</h1>
        <button onClick={() => setShowUrlModal(true)} className="btn-secondary">
          Add from URL
        </button>
        <Link to="/inventory/new" className="btn-primary">
          Add Component
        </Link>
      </div>

      {/* Filters */}
      <div className="card p-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name, MPN, specs..."
            className="input"
          />
          <select value={category} onChange={setFilter(setCategory)} className="input">
            <option value="">All categories</option>
            {categories.map((c) => (
              <option key={nameOf(c)} value={nameOf(c)}>
                {nameOf(c)}
              </option>
            ))}
          </select>
          <select value={tag} onChange={setFilter(setTag)} className="input">
            <option value="">All tags</option>
            {tags.map((t) => (
              <option key={nameOf(t)} value={nameOf(t)}>
                {nameOf(t)}
              </option>
            ))}
          </select>
          <select value={location} onChange={setFilter(setLocation)} className="input">
            <option value="">All locations</option>
            {locations.map((l) => (
              <option key={nameOf(l)} value={nameOf(l)}>
                {nameOf(l)}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-wrap gap-5 mt-3">
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={lowStock}
              onChange={(e) => {
                setLowStock(e.target.checked);
                setPage(1);
              }}
              className="accent-current"
            />
            <span className={lowStock ? 'text-dark-warning' : 'text-dark-textMuted'}>
              Low stock only
            </span>
          </label>
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={outOfStock}
              onChange={(e) => {
                setOutOfStock(e.target.checked);
                setPage(1);
              }}
              className="accent-current"
            />
            <span className={outOfStock ? 'text-dark-error' : 'text-dark-textMuted'}>
              Out of stock only
            </span>
          </label>
          <span className="text-sm text-dark-textMuted ml-auto tabular-nums">
            {total} component{total === 1 ? '' : 's'}
          </span>
        </div>
      </div>

      {showUrlModal && (
        <div className="card border border-dark-border">
          <form onSubmit={handleFromUrl} className="flex flex-col sm:flex-row gap-3">
            <input
              type="url"
              required
              autoFocus
              value={productUrl}
              onChange={(e) => setProductUrl(e.target.value)}
              placeholder="Paste an Amazon / AliExpress / Adafruit / Mouser / DigiKey product URL"
              className="input flex-1"
            />
            <button type="submit" disabled={urlBusy} className="btn-primary">
              {urlBusy ? 'Reading page...' : 'Fetch'}
            </button>
            <button type="button" onClick={() => setShowUrlModal(false)} className="btn-secondary">
              Cancel
            </button>
          </form>
          {urlError && <div className="alert-error mt-3">{urlError}</div>}
          {urlBusy && (
            <p className="text-xs text-dark-textMuted mt-2">
              Claude is reading the product page - this takes 10-30 seconds.
            </p>
          )}
        </div>
      )}

      {actionError && <div className="alert-error">{actionError}</div>}
      {error && <div className="alert-error">Failed to load components: {error.message}</div>}

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-dark-border bg-dark-elevated">
                <th className="py-2 pl-3 w-12"></th>
                <SortHeader label="Name" field="name" sort={sort} order={order} onSort={handleSort} />
                <SortHeader label="Category" field="category" sort={sort} order={order} onSort={handleSort} className="hidden sm:table-cell" />
                <SortHeader label="Location" field="location" sort={sort} order={order} onSort={handleSort} className="hidden md:table-cell" />
                <th className="text-left py-2 px-3 font-medium text-dark-textMuted hidden lg:table-cell">
                  Tags
                </th>
                <SortHeader label="Qty" field="qty_on_hand" sort={sort} order={order} onSort={handleSort} className="text-right" />
                <th className="py-2 px-3"></th>
              </tr>
            </thead>
            <tbody>
              {isLoading && items.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-10 text-center text-dark-textMuted">
                    Loading...
                  </td>
                </tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-10 text-center text-dark-textMuted">
                    No components match the current filters.
                  </td>
                </tr>
              ) : (
                items.map((c) => (
                  <tr
                    key={c.id}
                    onClick={() => navigate(`/inventory/${c.id}`)}
                    className="border-b border-dark-border last:border-b-0 hover:bg-dark-elevated cursor-pointer"
                  >
                    <td className="py-2 pl-3">
                      {c.image_url ? (
                        <img
                          src={c.image_url}
                          alt=""
                          loading="lazy"
                          className="w-10 h-10 object-contain rounded bg-dark-bg"
                        />
                      ) : (
                        <div className="w-10 h-10 rounded bg-dark-elevated" />
                      )}
                    </td>
                    <td className="py-2.5 px-3">
                      <p className="font-medium">{c.name}</p>
                      <p className="text-xs text-dark-textMuted">
                        {[c.manufacturer, c.mpn].filter(Boolean).join(' · ')}
                      </p>
                    </td>
                    <td className="py-2.5 px-3 text-dark-textMuted hidden sm:table-cell">
                      {c.category}
                    </td>
                    <td className="py-2.5 px-3 text-dark-textMuted hidden md:table-cell">
                      {c.location || '—'}
                    </td>
                    <td className="py-2.5 px-3 hidden lg:table-cell">
                      <div className="flex flex-wrap gap-1">
                        {(c.tags || []).map((t) => (
                          <span key={nameOf(t)} className="chip-neutral">
                            {nameOf(t)}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="py-2.5 px-3 text-right">
                      <QtyText qty={c.qty_on_hand} minQty={c.min_qty} />
                      {c.min_qty > 0 && (
                        <span className="text-xs text-dark-textMuted"> / {c.min_qty}</span>
                      )}
                    </td>
                    <td className="py-2.5 px-3" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => adjustMutation.mutate({ id: c.id, delta: -1 })}
                          disabled={adjustMutation.isPending || (c.qty_on_hand ?? 0) <= 0}
                          className="w-7 h-7 rounded bg-dark-elevated border border-dark-border text-dark-textMuted hover:text-dark-text hover:border-dark-accent disabled:opacity-40 disabled:cursor-not-allowed"
                          title="Decrement stock"
                        >
                          −
                        </button>
                        <button
                          onClick={() => adjustMutation.mutate({ id: c.id, delta: 1 })}
                          disabled={adjustMutation.isPending}
                          className="w-7 h-7 rounded bg-dark-elevated border border-dark-border text-dark-textMuted hover:text-dark-text hover:border-dark-accent disabled:opacity-40"
                          title="Increment stock"
                        >
                          +
                        </button>
                      </div>
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

export default InventoryPage;
