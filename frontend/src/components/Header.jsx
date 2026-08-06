import { Link, NavLink } from 'react-router-dom';
import Icon from './Icon.jsx';
import { useTour } from './Tour.jsx';

export default function Header() {
  const { start } = useTour();
  return (
    <header className="site-header">
      <div className="wrap">
        <Link className="brand" to="/">
          <img className="seal-img" src="/US-AlcoholAndTobaccoTaxAndTradeBureau-Seal.svg" alt="TTB seal" />
          <span className="brand-text">
            <span className="agency">Alcohol &amp; Tobacco Tax and Trade Bureau</span>
            <span className="product">
              Public COLA <b>Registry</b>
            </span>
          </span>
        </Link>
        <nav className="header-nav">
          <NavLink to="/" className={({ isActive }) => (isActive ? 'active' : '')} end>
            Search
          </NavLink>
          <a href="https://my.ttb.gov/" target="_blank" rel="noopener noreferrer" className="row gap-6">
            myTTB <Icon name="external" size={14} />
          </a>
          <a
            href="https://www.ttb.gov/system/files/images/pdfs/forms/f510031.pdf"
            target="_blank"
            rel="noopener noreferrer"
            className="row gap-6"
          >
            COLA Application Form <Icon name="external" size={14} />
          </a>
          <a
            href="https://www.ttb.gov/regulated-commodities/labeling/labeling-resources"
            target="_blank"
            rel="noopener noreferrer"
            className="row gap-6"
          >
            COLA Resources <Icon name="external" size={14} />
          </a>
          <button type="button" className="nav-tour" data-tour="tour-button" onClick={start}>
            <Icon name="info" size={14} /> Tour
          </button>
        </nav>
      </div>
    </header>
  );
}
