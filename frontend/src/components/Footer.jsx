import Icon from './Icon.jsx';

export default function Footer() {
  return (
    <footer className="site-footer">
      <div className="wrap">
        <div className="foot-brand">
          <img
            className="seal-img"
            style={{ width: 52, height: 52 }}
            src="/US-AlcoholAndTobaccoTaxAndTradeBureau-Seal.svg"
            alt="TTB seal"
          />
          <div>
            <div style={{ fontWeight: 800, color: '#fff', fontSize: 16 }}>
              Alcohol &amp; Tobacco Tax and Trade Bureau
            </div>
            <div className="foot-note">
              Public Certificate of Label Approval (COLA) Registry.
            </div>
          </div>
        </div>
        <nav className="foot-links">
          <h4>Resources</h4>
          <a href="https://my.ttb.gov/" target="_blank" rel="noopener noreferrer">
            myTTB <Icon name="external" size={14} />
          </a>
          <a
            href="https://www.ttb.gov/system/files/images/pdfs/forms/f510031.pdf"
            target="_blank"
            rel="noopener noreferrer"
          >
            COLA Application Form <Icon name="external" size={14} />
          </a>
          <a
            href="https://www.ttb.gov/regulated-commodities/labeling/labeling-resources"
            target="_blank"
            rel="noopener noreferrer"
          >
            COLA Resources <Icon name="external" size={14} />
          </a>
        </nav>
      </div>
    </footer>
  );
}
