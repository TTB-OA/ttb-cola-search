import { tagClass } from '../lib/format.js';

const STATUS_MAP = { Approved: 'approved', Pending: 'pending', Revoked: 'revoked', Expired: 'expired' };

export function StatusBadge({ status }) {
  return (
    <span className={'badge ' + (STATUS_MAP[status] || 'expired')}>
      <span className="dot"></span>
      {status || 'Unknown'}
    </span>
  );
}

export function CatTag({ rec }) {
  return <span className={'tag ' + tagClass(rec.category)}>{rec.category}</span>;
}
