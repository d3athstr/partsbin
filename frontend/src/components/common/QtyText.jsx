/**
 * ISA-101 stock quantity text: plain gray when OK, amber when at/below
 * min_qty, red when out of stock. No green for healthy stock.
 */
const QtyText = ({ qty, minQty, suffix = '', className = '' }) => {
  const q = Number(qty) || 0;
  const min = Number(minQty) || 0;

  let cls = 'text-dark-text';
  if (q <= 0) cls = 'text-dark-error font-semibold';
  else if (min > 0 && q <= min) cls = 'text-dark-warning font-semibold';

  return (
    <span className={`${cls} ${className} whitespace-nowrap text-sm tabular-nums`}>
      {q}
      {suffix}
    </span>
  );
};

export default QtyText;
