import React from 'react';

/**
 * Quantity on hand, coloured by exception state.
 *
 * ISA-101: colour marks an ABNORMAL condition that needs an operator decision.
 * A part that is at zero but already ORDERED is not abnormal — you have
 * already acted, and there is nothing left to decide — so it renders MUTED,
 * not red. Only a genuine zero (nothing on hand, nothing coming) is an alarm.
 * Nothing here is ever green: normal is plain.
 */
const QtyText = ({ qty, minQty, qtyOnOrder = 0, suffix = '', className = '' }) => {
  const q = Number(qty) || 0;
  const min = Number(minQty) || 0;
  const onOrder = Number(qtyOnOrder) || 0;

  let cls = 'text-dark-text';
  if (q <= 0 && onOrder > 0) cls = 'text-dark-textMuted';
  else if (q <= 0) cls = 'text-dark-error font-semibold';
  else if (min > 0 && q <= min) cls = 'text-dark-warning font-semibold';

  return (
    <span className={`${cls} ${className} whitespace-nowrap text-sm tabular-nums`}>
      {q}
      {suffix}
      {q <= 0 && onOrder > 0 && (
        <span className="text-dark-textMuted"> · {onOrder} on order</span>
      )}
    </span>
  );
};
export default QtyText;
