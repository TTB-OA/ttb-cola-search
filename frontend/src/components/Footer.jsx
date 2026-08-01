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
      </div>
    </footer>
  );
}
