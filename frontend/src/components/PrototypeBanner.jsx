import Icon from './Icon.jsx';

export default function PrototypeBanner() {
  return (
    <div className="prototype-banner" role="status">
      <div className="wrap">
        <Icon name="info" size={16} />
        <span>
          <b>Prototype</b> — this tool is a prototype to assess capabilities. It is not intended for public use.
        </span>
      </div>
    </div>
  );
}
