import { useEffect, useState } from 'react';
import Icon from './Icon.jsx';

// Most searches answer in well under a second, so a notice from the first
// frame would only flash. Past `delay` the query is plainly one of the heavy
// ones, and the user should know it is still working rather than stuck.
const STILL_WORKING_MS = 12000;

export default function SlowNotice({
  active,
  delay = 2500,
  title = 'This is a complex search',
  detail = 'It covers millions of label records, so it can take several seconds. Results will appear here automatically.',
  stillDetail = 'Still working. Results will appear as soon as the search finishes.',
  className = '',
}) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    setElapsed(0);
    if (!active) return undefined;
    const started = Date.now();
    const timer = setInterval(() => {
      setElapsed(Date.now() - started);
    }, 500);
    return () => {
      clearInterval(timer);
    };
  }, [active]);

  if (!active || elapsed < delay) return null;

  return (
    <div className={`slow-notice ${className}`} role="status" aria-live="polite">
      <Icon name="loader" size={20} className="spin slow-notice-ico" />
      <div className="slow-notice-body">
        <strong>{title}</strong>
        <span>{elapsed >= STILL_WORKING_MS ? stillDetail : detail}</span>
      </div>
      <span className="slow-notice-time mono" aria-hidden="true">
        {Math.floor(elapsed / 1000)}s
      </span>
    </div>
  );
}
