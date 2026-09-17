import { useState } from 'react';
import { Link } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import ComponentPicker from '../common/ComponentPicker';

/**
 * The solder/assembly order for a project, and the mechanical check on it.
 *
 * The check is the reason this section exists. Solder a XIAO flat onto its
 * carrier and the BAT+/BAT- pads on its underside are gone — the board works,
 * the battery can never be attached, and nothing in the schematic or the BOM
 * said so. Each step therefore declares what it NEEDS reachable and what it
 * HIDES, and the order is verified rather than merely written down.
 *
 * ISA-101: gray while the order is clean, amber for an unaddressed hazard, red
 * for a real conflict. There is no green "checks passed" badge — a correct
 * assembly order is the normal state and does not warrant color.
 */

const tagsToText = (tags) => (tags || []).join(', ');

const EMPTY_FORM = {
  title: '',
  body_md: '',
  needs_access: '',
  obstructs: '',
  component_id: null,
  component_name: '',
};

/** Chip for one access tag. Flagged red when it is the tag in a conflict. */
const TagChip = ({ tag, kind, conflicted }) => (
  <span
    className={conflicted ? 'chip-alarm' : 'chip-neutral'}
    title={
      kind === 'needs'
        ? 'Must still be reachable to do this step'
        : 'Out of reach once this step is done'
    }
  >
    <span className="opacity-60 mr-1">{kind === 'needs' ? 'needs' : 'hides'}</span>
    {tag}
  </span>
);

const StepForm = ({ initial, busy, onSubmit, onCancel, onPickComponent }) => {
  const [form, setForm] = useState(initial);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  return (
    <form
      className="p-3 bg-dark-elevated rounded-lg space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (!form.title.trim()) return;
        onSubmit(form);
      }}
    >
      <input
        value={form.title}
        onChange={set('title')}
        placeholder="What you do in this step, e.g. Tin the XIAO BAT+/BAT- pads"
        className="input w-full"
        autoFocus
      />

      <textarea
        value={form.body_md || ''}
        onChange={set('body_md')}
        rows={3}
        placeholder="Detail, markdown — iron temperature, which side, what to check before moving on"
        className="input w-full font-mono text-sm"
      />

      <div className="grid sm:grid-cols-2 gap-3">
        <label className="block">
          <span className="text-xs text-dark-textMuted uppercase tracking-wide">
            Needs access to
          </span>
          <input
            value={form.needs_access}
            onChange={set('needs_access')}
            placeholder="xiao-underside, c1-pads"
            className="input w-full mt-1 font-mono text-sm"
          />
          <span className="text-xs text-dark-textMuted">
            Contacts that must still be reachable to do this step.
          </span>
        </label>

        <label className="block">
          <span className="text-xs text-dark-textMuted uppercase tracking-wide">
            Puts out of reach
          </span>
          <input
            value={form.obstructs}
            onChange={set('obstructs')}
            placeholder="xiao-underside"
            className="input w-full mt-1 font-mono text-sm"
          />
          <span className="text-xs text-dark-textMuted">
            Contacts nothing can get at once this step is done.
          </span>
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() =>
            onPickComponent((component) =>
              setForm((f) => ({
                ...f,
                component_id: component.id,
                component_name: component.name,
              }))
            )
          }
          className="btn-secondary text-sm py-1.5"
        >
          {form.component_id ? `Part: ${form.component_name}` : '+ Link a BOM part'}
        </button>
        {form.component_id && (
          <button
            type="button"
            onClick={() => setForm({ ...form, component_id: null, component_name: '' })}
            className="text-xs text-dark-textMuted hover:text-dark-error"
          >
            clear part
          </button>
        )}
        <span className="flex-1" />
        <button type="button" onClick={onCancel} className="btn-secondary text-sm py-1.5">
          Cancel
        </button>
        <button type="submit" disabled={busy} className="btn-primary text-sm py-1.5">
          {busy ? 'Saving…' : 'Save step'}
        </button>
      </div>
    </form>
  );
};

const ProjectAssembly = ({
  assembly,
  busy,
  onAdd,
  onUpdate,
  onDelete,
  onReorder,
}) => {
  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [pickerFor, setPickerFor] = useState(null);

  const steps = assembly?.steps || [];
  const conflicts = assembly?.conflicts || [];
  const hazards = assembly?.hazards || [];
  const unaddressed = hazards.filter((h) => !h.addressed);
  const status = assembly?.status || 'none';
  const doneCount = assembly?.steps_done || 0;

  // Which (step, tag) pairs are implicated in a conflict, so the offending
  // chips can be picked out of the row instead of leaving you to match step
  // numbers against a banner by eye.
  const conflictTags = new Set();
  conflicts.forEach((c) => {
    conflictTags.add(`${c.step_id}:${c.tag}`);
    conflictTags.add(`${c.blocked_by_id}:${c.tag}`);
  });

  const statusChip = () => {
    if (status === 'conflict') {
      return (
        <span className="chip-alarm">
          {conflicts.length} order conflict{conflicts.length === 1 ? '' : 's'}
        </span>
      );
    }
    if (status === 'warning') {
      return (
        <span className="chip-warn">
          {steps.length === 0
            ? 'no assembly order'
            : `${unaddressed.length} hazard${unaddressed.length === 1 ? '' : 's'} unaddressed`}
        </span>
      );
    }
    if (status === 'ok') {
      return (
        <span className="chip-neutral">
          {doneCount}/{steps.length} done
        </span>
      );
    }
    return null;
  };

  const move = (index, delta) => {
    const target = index + delta;
    if (target < 0 || target >= steps.length) return;
    const order = steps.map((s) => s.id);
    [order[index], order[target]] = [order[target], order[index]];
    onReorder(order);
  };

  const submitNew = (form) => {
    onAdd({
      title: form.title.trim(),
      body_md: form.body_md || null,
      needs_access: form.needs_access,
      obstructs: form.obstructs,
      component_id: form.component_id,
    });
    setAdding(false);
  };

  const submitEdit = (stepId) => (form) => {
    onUpdate(stepId, {
      title: form.title.trim(),
      body_md: form.body_md || null,
      needs_access: form.needs_access,
      obstructs: form.obstructs,
      component_id: form.component_id,
    });
    setEditingId(null);
  };

  return (
    <div className="card">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold">Assembly Order</h2>
          {statusChip()}
        </div>
        <button
          onClick={() => {
            setAdding(true);
            setEditingId(null);
          }}
          className="btn-secondary text-sm py-1.5"
        >
          + Add Step
        </button>
      </div>

      {/* Conflicts: the recorded order will strand a contact. */}
      {conflicts.length > 0 && (
        <div className="alert-error mb-4 space-y-1.5">
          {conflicts.map((c, i) => (
            <p key={i} className="text-sm">
              {c.message}
            </p>
          ))}
        </div>
      )}

      {/* Hazards inherited from the BOM: a part known to hide a contact that
          no step in this order mentions. Fires even with no steps at all. */}
      {unaddressed.length > 0 && (
        <div className="alert-warn mb-4 space-y-1.5">
          {unaddressed.map((h) => (
            <p key={h.component_id} className="text-sm">
              {h.message}
              {h.assembly_notes && (
                <span className="block text-dark-textMuted mt-0.5">{h.assembly_notes}</span>
              )}
            </p>
          ))}
        </div>
      )}

      {steps.length === 0 && !adding ? (
        <p className="text-sm text-dark-textMuted">
          No assembly order recorded. Write the steps in the order you will actually solder
          them — the order gets checked against what each step puts out of reach.
        </p>
      ) : (
        <ol className="space-y-2">
          {steps.map((step, index) => {
            const stepConflicted = conflicts.some((c) => c.step_id === step.id);
            const blocksSomething = conflicts.some((c) => c.blocked_by_id === step.id);

            if (editingId === step.id) {
              return (
                <li key={step.id}>
                  <StepForm
                    initial={{
                      title: step.title,
                      body_md: step.body_md || '',
                      needs_access: tagsToText(step.needs_access),
                      obstructs: tagsToText(step.obstructs),
                      component_id: step.component?.id ?? step.component_id ?? null,
                      component_name: step.component?.name || '',
                    }}
                    busy={busy}
                    onSubmit={submitEdit(step.id)}
                    onCancel={() => setEditingId(null)}
                    onPickComponent={(cb) => setPickerFor(() => cb)}
                  />
                </li>
              );
            }

            return (
              <li
                key={step.id}
                className={`flex gap-3 p-3 rounded-lg border ${
                  stepConflicted
                    ? 'border-dark-error bg-dark-error bg-opacity-5'
                    : blocksSomething
                      ? 'border-dark-warning border-opacity-50'
                      : 'border-dark-border'
                }`}
              >
                <input
                  type="checkbox"
                  checked={!!step.done}
                  onChange={() => onUpdate(step.id, { done: !step.done })}
                  className="mt-1 h-4 w-4 flex-shrink-0 accent-dark-accent"
                  title={step.done ? 'Mark not done' : 'Mark done'}
                />

                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="tabular-nums text-dark-textMuted text-sm">{step.seq}.</span>
                    <span
                      className={`font-medium ${step.done ? 'line-through text-dark-textMuted' : ''}`}
                    >
                      {step.title}
                    </span>
                    {step.component && (
                      <Link
                        to={`/inventory/${step.component.id}`}
                        className="link text-xs whitespace-nowrap"
                      >
                        {step.component.name}
                      </Link>
                    )}
                  </div>

                  {step.body_md && (
                    <div className="markdown-body text-sm mt-1.5">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{step.body_md}</ReactMarkdown>
                    </div>
                  )}

                  {(step.needs_access.length > 0 || step.obstructs.length > 0) && (
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {step.needs_access.map((t) => (
                        <TagChip
                          key={`n-${t}`}
                          tag={t}
                          kind="needs"
                          conflicted={conflictTags.has(`${step.id}:${t}`) && stepConflicted}
                        />
                      ))}
                      {step.obstructs.map((t) => (
                        <TagChip
                          key={`o-${t}`}
                          tag={t}
                          kind="obstructs"
                          conflicted={conflictTags.has(`${step.id}:${t}`) && blocksSomething}
                        />
                      ))}
                    </div>
                  )}
                </div>

                <div className="flex flex-col items-center gap-1 flex-shrink-0">
                  <button
                    onClick={() => move(index, -1)}
                    disabled={index === 0 || busy}
                    className="text-dark-textMuted hover:text-dark-text disabled:opacity-30 px-1"
                    title="Move earlier"
                  >
                    ▲
                  </button>
                  <button
                    onClick={() => move(index, 1)}
                    disabled={index === steps.length - 1 || busy}
                    className="text-dark-textMuted hover:text-dark-text disabled:opacity-30 px-1"
                    title="Move later"
                  >
                    ▼
                  </button>
                </div>

                <div className="flex flex-col gap-2 flex-shrink-0">
                  <button
                    onClick={() => {
                      setEditingId(step.id);
                      setAdding(false);
                    }}
                    className="text-xs text-dark-textMuted hover:text-dark-accent"
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => {
                      if (window.confirm(`Remove step ${step.seq}?`)) onDelete(step.id);
                    }}
                    className="text-xs text-dark-textMuted hover:text-dark-error"
                  >
                    Delete
                  </button>
                </div>
              </li>
            );
          })}
        </ol>
      )}

      {adding && (
        <div className="mt-3">
          <StepForm
            initial={EMPTY_FORM}
            busy={busy}
            onSubmit={submitNew}
            onCancel={() => setAdding(false)}
            onPickComponent={(cb) => setPickerFor(() => cb)}
          />
        </div>
      )}

      {/* Hazards this order does account for — kept visible so the reason a
          step exists survives the person who wrote it. */}
      {hazards.some((h) => h.addressed) && (
        <div className="mt-4 pt-3 border-t border-dark-border text-xs text-dark-textMuted space-y-1">
          {hazards
            .filter((h) => h.addressed)
            .map((h) => (
              <p key={h.component_id}>{h.message}</p>
            ))}
        </div>
      )}

      {pickerFor && (
        <ComponentPicker
          title="Link a part to this step"
          onClose={() => setPickerFor(null)}
          onSelect={(component) => {
            pickerFor(component);
            setPickerFor(null);
          }}
        />
      )}
    </div>
  );
};

export default ProjectAssembly;
