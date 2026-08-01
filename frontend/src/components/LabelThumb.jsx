// Renders a real label image when a URL is available, falling back to a
// procedural placeholder (mirrors the prototype look) when the image is
// missing or fails to load.
import { useState } from 'react';
import { placeholderStyle } from '../lib/format.js';

function Placeholder({ rec, style }) {
  const { bg, ink } = placeholderStyle(rec);
  const kicker = rec.classSub || rec.category;
  return (
    <div
      className="label-thumb style-classic"
      style={{ '--lt-bg': bg, '--lt-ink': ink, ...(style || {}) }}
      aria-label={(rec.brand || 'Label') + ' label'}
    >
      <div className="lt-inner">
        <div className="lt-kicker">{kicker}</div>
        <div className="lt-brand">{rec.brand}</div>
        <div className="lt-rule"></div>
        {rec.fanciful && <div className="lt-fanciful">{rec.fanciful}</div>}
        <div className="lt-foot">{rec.origin}</div>
        {(rec.netContents || rec.abv) && (
          <div className="lt-abv">
            {[rec.netContents, rec.abv && `${rec.abv} ALC/VOL`].filter(Boolean).join(' · ')}
          </div>
        )}
      </div>
    </div>
  );
}

export default function LabelThumb({ rec, style, src }) {
  const url = src || rec.thumbUrl;
  const [failed, setFailed] = useState(false);

  if (!url || failed) return <Placeholder rec={rec} style={style} />;

  return (
    <div className="label-thumb label-photo" style={style} aria-label={(rec.brand || 'Label') + ' label'}>
      <img
        src={url}
        alt={(rec.brand || 'Label') + ' label image'}
        loading="lazy"
        onError={() => setFailed(true)}
      />
    </div>
  );
}

export { Placeholder };
