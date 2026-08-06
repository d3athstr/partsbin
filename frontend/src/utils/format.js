export const fmtDate = (value) => {
  if (!value) return '—';
  const d = new Date(value);
  if (isNaN(d.getTime())) return String(value);
  return d.toLocaleDateString();
};

export const fmtDateTime = (value) => {
  if (!value) return '—';
  const d = new Date(value);
  if (isNaN(d.getTime())) return String(value);
  return d.toLocaleString();
};

export const fmtMoney = (value) => {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  if (isNaN(n)) return String(value);
  return n.toLocaleString(undefined, { style: 'currency', currency: 'USD' });
};

/**
 * Per-unit prices: sub-dollar parts (resistors at $0.0142/ea) need more than
 * two decimals or they all round to the same "$0.01".
 */
export const fmtUnitMoney = (value) => {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  if (isNaN(n)) return String(value);
  const digits = n !== 0 && Math.abs(n) < 1 ? 4 : 2;
  return n.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
};

/** Signed money for variance readouts: +$4.10 over, -$2.05 under. */
export const fmtVariance = (value) => {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  if (isNaN(n)) return String(value);
  return `${n > 0 ? '+' : n < 0 ? '−' : ''}${fmtMoney(Math.abs(n))}`;
};
