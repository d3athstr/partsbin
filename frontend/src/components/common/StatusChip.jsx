/**
 * ISA-101 order status chip.
 * Gray for normal lifecycle states (ordered/delivered/received),
 * blue for in-transit info (shipped), amber when human action is needed.
 */
const StatusChip = ({ status, needsReview = false }) => {
  if (needsReview) {
    return <span className="chip-warn">needs review</span>;
  }
  if (status === 'shipped') {
    return <span className="chip-info">shipped</span>;
  }
  return <span className="chip-neutral">{status || 'unknown'}</span>;
};

export default StatusChip;
