import { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import componentService from '../../services/componentService';
import Modal from './Modal';
import QtyText from './QtyText';

/**
 * Search-driven component picker modal.
 * Props: onSelect(component), onClose(), title
 */
const ComponentPicker = ({ onSelect, onClose, title = 'Select Component' }) => {
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  const { data, isLoading } = useQuery({
    queryKey: ['componentPicker', debounced],
    queryFn: () => componentService.list({ search: debounced, per_page: 15 }),
  });

  const items = data?.items || [];

  return (
    <Modal title={title} onClose={onClose} wide>
      <input
        type="text"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search by name, MPN, specs..."
        className="input mb-4"
        autoFocus
      />

      {isLoading ? (
        <div className="flex justify-center py-8">
          <div className="w-8 h-8 border-4 border-dark-accent border-t-transparent rounded-full spinner"></div>
        </div>
      ) : items.length === 0 ? (
        <p className="text-dark-textMuted text-center py-6">No components found.</p>
      ) : (
        <div className="max-h-96 overflow-y-auto divide-y divide-dark-border border border-dark-border rounded-lg">
          {items.map((c) => (
            <button
              key={c.id}
              onClick={() => onSelect(c)}
              className="w-full flex items-center justify-between gap-4 px-4 py-3 text-left hover:bg-dark-elevated transition-colors"
            >
              <div className="min-w-0">
                <p className="font-medium truncate">{c.name}</p>
                <p className="text-xs text-dark-textMuted truncate">
                  {[c.category, c.mpn, c.location].filter(Boolean).join(' · ')}
                </p>
              </div>
              <QtyText qty={c.qty_on_hand} minQty={c.min_qty} suffix=" on hand" />
            </button>
          ))}
        </div>
      )}
    </Modal>
  );
};

export default ComponentPicker;
