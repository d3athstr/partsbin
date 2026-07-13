import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import componentService from '../../services/componentService';
import { asList, errMsg } from '../../services/api';

const nameOf = (x) => (typeof x === 'string' ? x : x?.name);

/**
 * Shared create/edit component form.
 * Props:
 *   initial   — existing component (edit mode) or {} / prefill
 *   onSubmit  — async (payload, imageFile) => void
 *   submitLabel
 *   busy
 */
const ComponentForm = ({ initial = {}, onSubmit, submitLabel = 'Save', busy = false }) => {
  const queryClient = useQueryClient();

  const [name, setName] = useState(initial.name || '');
  const [category, setCategory] = useState(initial.category || '');
  const [manufacturer, setManufacturer] = useState(initial.manufacturer || '');
  const [mpn, setMpn] = useState(initial.mpn || '');
  const [description, setDescription] = useState(initial.description || '');
  const [qtyOnHand, setQtyOnHand] = useState(
    initial.qty_on_hand !== undefined ? String(initial.qty_on_hand) : '0'
  );
  const [minQty, setMinQty] = useState(
    initial.min_qty !== undefined ? String(initial.min_qty) : '0'
  );
  const [location, setLocation] = useState(initial.location || '');
  const [datasheetUrl, setDatasheetUrl] = useState(initial.datasheet_url || '');
  const [notes, setNotes] = useState(initial.notes || '');
  const [specRows, setSpecRows] = useState(() => {
    const entries = Object.entries(initial.specs || {});
    return entries.length > 0
      ? entries.map(([key, value]) => ({ key, value: String(value) }))
      : [{ key: '', value: '' }];
  });
  const [selectedTags, setSelectedTags] = useState(
    (initial.tags || []).map((t) => nameOf(t))
  );
  const [newTag, setNewTag] = useState('');
  const [imageFile, setImageFile] = useState(null);
  const [error, setError] = useState('');

  const isEdit = !!initial.id;

  const { data: categoriesData } = useQuery({
    queryKey: ['categories'],
    queryFn: () => componentService.categories(),
    staleTime: Infinity,
  });
  const { data: tagsData } = useQuery({
    queryKey: ['tags'],
    queryFn: () => componentService.tags(),
  });

  const categories = asList(categoriesData, 'categories');
  const tags = asList(tagsData, 'tags');

  const createTagMutation = useMutation({
    mutationFn: (tagName) => componentService.createTag(tagName),
    onSuccess: (_data, tagName) => {
      queryClient.invalidateQueries({ queryKey: ['tags'] });
      setSelectedTags((prev) => [...new Set([...prev, tagName])]);
      setNewTag('');
    },
    onError: (err) => setError(errMsg(err, 'Failed to create tag')),
  });

  const toggleTag = (tagName) => {
    setSelectedTags((prev) =>
      prev.includes(tagName) ? prev.filter((t) => t !== tagName) : [...prev, tagName]
    );
  };

  const setSpecRow = (i, field, value) => {
    setSpecRows((rows) => rows.map((r, idx) => (idx === i ? { ...r, [field]: value } : r)));
  };

  const addSpecRow = () => setSpecRows((rows) => [...rows, { key: '', value: '' }]);
  const removeSpecRow = (i) => setSpecRows((rows) => rows.filter((_, idx) => idx !== i));

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

    const specs = {};
    specRows.forEach(({ key, value }) => {
      if (key.trim()) specs[key.trim()] = value;
    });

    const payload = {
      name: name.trim(),
      category,
      specs,
      manufacturer: manufacturer.trim() || null,
      mpn: mpn.trim() || null,
      description: description.trim() || null,
      min_qty: parseInt(minQty, 10) || 0,
      location: location.trim() || null,
      datasheet_url: datasheetUrl.trim() || null,
      notes: notes.trim() || null,
      tags: selectedTags,
    };

    // qty_on_hand only settable on create (edits go through /adjust transactions)
    if (!isEdit) {
      payload.qty_on_hand = parseInt(qtyOnHand, 10) || 0;
    }

    try {
      await onSubmit(payload, imageFile);
    } catch (err) {
      setError(errMsg(err, 'Save failed'));
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {error && <div className="alert-error">{error}</div>}

      <div className="card space-y-4">
        <h2 className="text-lg font-semibold">Basics</h2>
        <div className="grid sm:grid-cols-2 gap-4">
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium mb-2">Name *</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="input"
              placeholder="e.g. 10k 1/4W resistor"
              required
            />
          </div>
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
            <label className="block text-sm font-medium mb-2">Location (bin/drawer)</label>
            <input
              type="text"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              className="input"
              placeholder="e.g. Drawer B3"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-2">Manufacturer</label>
            <input
              type="text"
              value={manufacturer}
              onChange={(e) => setManufacturer(e.target.value)}
              className="input"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-2">MPN</label>
            <input
              type="text"
              value={mpn}
              onChange={(e) => setMpn(e.target.value)}
              className="input"
              placeholder="Manufacturer part number"
            />
          </div>
          {!isEdit && (
            <div>
              <label className="block text-sm font-medium mb-2">Qty on hand</label>
              <input
                type="number"
                min="0"
                value={qtyOnHand}
                onChange={(e) => setQtyOnHand(e.target.value)}
                className="input"
              />
            </div>
          )}
          <div>
            <label className="block text-sm font-medium mb-2">Min qty (low-stock threshold)</label>
            <input
              type="number"
              min="0"
              value={minQty}
              onChange={(e) => setMinQty(e.target.value)}
              className="input"
            />
          </div>
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium mb-2">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="input"
              rows={2}
            />
          </div>
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium mb-2">Datasheet URL</label>
            <input
              type="url"
              value={datasheetUrl}
              onChange={(e) => setDatasheetUrl(e.target.value)}
              className="input"
              placeholder="https://..."
            />
          </div>
        </div>
      </div>

      {/* Specs editor */}
      <div className="card space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Specs</h2>
          <button type="button" onClick={addSpecRow} className="btn-secondary text-sm py-1">
            + Add spec
          </button>
        </div>
        <p className="text-xs text-dark-textMuted">
          Free-form key/value pairs: resistance, capacitance, voltage, package, pinout...
        </p>
        <div className="space-y-2">
          {specRows.map((row, i) => (
            <div key={i} className="flex gap-2">
              <input
                type="text"
                value={row.key}
                onChange={(e) => setSpecRow(i, 'key', e.target.value)}
                placeholder="Key (e.g. voltage)"
                className="input w-1/3"
              />
              <input
                type="text"
                value={row.value}
                onChange={(e) => setSpecRow(i, 'value', e.target.value)}
                placeholder="Value (e.g. 3.3V)"
                className="input flex-1"
              />
              <button
                type="button"
                onClick={() => removeSpecRow(i)}
                className="px-3 text-dark-textMuted hover:text-dark-error"
                title="Remove"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Tags */}
      <div className="card space-y-3">
        <h2 className="text-lg font-semibold">Tags</h2>
        <div className="flex flex-wrap gap-2">
          {tags.map((t) => {
            const tn = nameOf(t);
            const active = selectedTags.includes(tn);
            return (
              <button
                key={tn}
                type="button"
                onClick={() => toggleTag(tn)}
                className={`chip ${
                  active
                    ? 'bg-dark-accent bg-opacity-20 text-dark-accent border border-dark-accent border-opacity-40'
                    : 'bg-dark-elevated text-dark-textMuted border border-dark-border hover:text-dark-text'
                }`}
              >
                {tn}
              </button>
            );
          })}
          {tags.length === 0 && (
            <span className="text-sm text-dark-textMuted">No tags yet.</span>
          )}
        </div>
        <div className="flex gap-2">
          <input
            type="text"
            value={newTag}
            onChange={(e) => setNewTag(e.target.value)}
            placeholder="New tag name"
            className="input flex-1"
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                if (newTag.trim()) createTagMutation.mutate(newTag.trim());
              }
            }}
          />
          <button
            type="button"
            onClick={() => newTag.trim() && createTagMutation.mutate(newTag.trim())}
            disabled={createTagMutation.isPending || !newTag.trim()}
            className="btn-secondary"
          >
            Add Tag
          </button>
        </div>
      </div>

      {/* Image */}
      <div className="card space-y-3">
        <h2 className="text-lg font-semibold">Image</h2>
        {isEdit && (initial.image_url || initial.image) && !imageFile && (
          <img
            src={initial.image_url || `/uploads/${initial.image}`}
            alt={initial.name}
            className="max-h-40 rounded-lg bg-dark-bg"
          />
        )}
        <input
          type="file"
          accept="image/*"
          onChange={(e) => setImageFile(e.target.files?.[0] || null)}
          className="block text-sm text-dark-textMuted file:mr-3 file:btn-secondary file:border-0 file:rounded-lg file:px-4 file:py-2 file:bg-dark-elevated file:text-dark-text file:cursor-pointer"
        />
        {imageFile && (
          <p className="text-xs text-dark-textMuted">Selected: {imageFile.name}</p>
        )}
      </div>

      {/* Notes */}
      <div className="card space-y-3">
        <h2 className="text-lg font-semibold">Notes</h2>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          className="input font-mono text-sm"
          rows={4}
          placeholder="Anything worth remembering about this part..."
        />
      </div>

      <div className="flex gap-3">
        <button type="submit" disabled={busy} className="btn-primary">
          {busy ? 'Saving...' : submitLabel}
        </button>
      </div>
    </form>
  );
};

export default ComponentForm;
