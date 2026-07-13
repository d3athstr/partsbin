import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import componentService from '../../services/componentService';
import { asList, errMsg } from '../../services/api';
import Modal from '../common/Modal';

const nameOf = (x) => (typeof x === 'string' ? x : x?.name);

/**
 * Create a new component pre-filled from an order item (auto-confirms
 * the match server-side via the create-component endpoint).
 * Props: item (order item), onSubmit(overrides), onClose, busy
 */
const CreateComponentModal = ({ item, onSubmit, onClose, busy }) => {
  const [name, setName] = useState(item.raw_title || '');
  const [category, setCategory] = useState('');
  const [location, setLocation] = useState('');
  const [minQty, setMinQty] = useState('0');
  const [mpn, setMpn] = useState('');
  const [error, setError] = useState('');

  const { data: categoriesData } = useQuery({
    queryKey: ['categories'],
    queryFn: () => componentService.categories(),
    staleTime: Infinity,
  });
  const categories = asList(categoriesData, 'categories');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!name.trim()) {
      setError('Name is required');
      return;
    }
    if (!category) {
      setError('Category is required');
      return;
    }
    try {
      await onSubmit({
        name: name.trim(),
        category,
        location: location.trim() || undefined,
        min_qty: parseInt(minQty, 10) || 0,
        mpn: mpn.trim() || undefined,
      });
    } catch (err) {
      setError(errMsg(err, 'Failed to create component'));
    }
  };

  return (
    <Modal title="Create New Component from Item" onClose={onClose}>
      <p className="text-xs text-dark-textMuted mb-4">
        From email: <span className="text-dark-text">{item.raw_title}</span>
        {item.qty ? ` (qty ${item.qty})` : ''}
      </p>

      {error && <div className="alert-error mb-4">{error}</div>}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium mb-2">Name *</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="input"
            required
            autoFocus
          />
        </div>
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium mb-2">Category *</label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="input"
              required
            >
              <option value="">Select category...</option>
              {categories.map((c) => (
                <option key={nameOf(c)} value={nameOf(c)}>
                  {nameOf(c)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium mb-2">Location</label>
            <input
              type="text"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              className="input"
              placeholder="e.g. Drawer B3"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-2">MPN</label>
            <input
              type="text"
              value={mpn}
              onChange={(e) => setMpn(e.target.value)}
              className="input"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-2">Min qty</label>
            <input
              type="number"
              min="0"
              value={minQty}
              onChange={(e) => setMinQty(e.target.value)}
              className="input"
            />
          </div>
        </div>

        <p className="text-xs text-dark-textMuted">
          Stock is added when the order is marked received (qty {item.qty ?? 1}).
        </p>

        <div className="flex gap-2 justify-end">
          <button type="button" onClick={onClose} className="btn-secondary">
            Cancel
          </button>
          <button type="submit" disabled={busy} className="btn-primary">
            {busy ? 'Creating...' : 'Create & Confirm'}
          </button>
        </div>
      </form>
    </Modal>
  );
};

export default CreateComponentModal;
