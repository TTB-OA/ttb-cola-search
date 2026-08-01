import { useState } from 'react';
import Icon from './Icon.jsx';

export default function GovBanner() {
  const [open, setOpen] = useState(false);
  return (
    <div className="gov-banner">
      <div className="wrap">
        <span className="flag" aria-hidden="true"></span>
        <span className="banner-text">An official website of the United States government</span>
        <button onClick={() => setOpen(!open)}>Here's how you know {open ? '▲' : '▾'}</button>
      </div>
      {open && (
        <div
          className="wrap"
          style={{ paddingBottom: 12, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, maxWidth: 980 }}
        >
          <div className="row gap-10" style={{ alignItems: 'flex-start' }}>
            <Icon name="info" size={22} />
            <div>
              <b>Official websites use .gov</b>
              <div className="muted" style={{ fontSize: 12.5 }}>
                A <b>.gov</b> website belongs to an official government organization in the United States.
              </div>
            </div>
          </div>
          <div className="row gap-10" style={{ alignItems: 'flex-start' }}>
            <Icon name="check" size={22} />
            <div>
              <b>Secure .gov websites use HTTPS</b>
              <div className="muted" style={{ fontSize: 12.5 }}>
                A lock means you've safely connected to the .gov website.
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
