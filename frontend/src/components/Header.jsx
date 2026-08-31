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
              TTB COLA <b>Registry</b>
            </span>
          </span>
        </Link>
        <nav className="header-nav">
          <NavLink to="/" className={({ isActive }) => (isActive ? 'active' : '')} end>
            Search
          </NavLink>
          <NavLink to="/coverage" className={({ isActive }) => (isActive ? 'active' : '')} data-tour="coverage-link">
            Coverage
          </NavLink>
          <NavLink to="/analytics" className={({ isActive }) => (isActive ? 'active' : '')}>
            Analytics
          </NavLink>
          <a href="/docs" target="_blank" rel="noopener noreferrer">
            API
          </a>
          <button type="button" className="nav-tour" data-tour="tour-button" onClick={start}>
            <Icon name="info" size={14} /> Tour
          </button>
        </nav>
        <nav className="header-nav-mobile" aria-label="Primary">
          <NavLink to="/" className={({ isActive }) => (isActive ? 'active' : '')} end>
            <Icon name="search" size={14} /> Search
          </NavLink>
          <NavLink to="/coverage" className={({ isActive }) => (isActive ? 'active' : '')}>
            <Icon name="grid" size={14} /> Coverage
          </NavLink>
          <NavLink to="/analytics" className={({ isActive }) => (isActive ? 'active' : '')}>
            <Icon name="table" size={14} /> Analytics
          </NavLink>
          <a href="/docs" target="_blank" rel="noopener noreferrer">
            <Icon name="external" size={14} /> API
          </a>
          <button type="button" onClick={start}>
            <Icon name="info" size={14} /> Tour
          </button>
        </nav>
      </div>
    </header>
  );
}
