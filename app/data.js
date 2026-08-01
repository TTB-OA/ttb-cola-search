/* ============================================================
   COLA Search — mock dataset
   Fictional brands. Fields mirror the public COLA registry.
   ============================================================ */
(function () {
  // curated label palettes {bg, ink}
  var PAL = {
    cream_burgundy: { bg: '#f3ece0', ink: '#5b1726' },
    cream_navy:     { bg: '#f1ede3', ink: '#1c2c4c' },
    black_gold:     { bg: '#1a1a1a', ink: '#d6b15e' },
    forest_cream:   { bg: '#eef0e6', ink: '#2c4a2e' },
    ink_silver:     { bg: '#16181d', ink: '#c9ced6' },
    amber_brown:    { bg: '#efe2c8', ink: '#5a3210' },
    slate_cream:    { bg: '#e9ecef', ink: '#2f3b45' },
    blush_plum:     { bg: '#f6e9ec', ink: '#5a2a4a' },
    sand_teal:      { bg: '#e9efe9', ink: '#16524f' },
    rust_cream:     { bg: '#f1e6dc', ink: '#7a2d12' },
    midnight_blue:  { bg: '#13233f', ink: '#cdd9ec' },
    olive_gold:     { bg: '#33361f', ink: '#d8c889' }
  };
  var palKeys = Object.keys(PAL);

  // category -> tag class + label style
  function meta(cat) {
    switch (cat) {
      case 'Wine':              return { tag: 'wine',    style: 'frame' };
      case 'Malt Beverage':     return { tag: 'beer',    style: 'minimal' };
      case 'Distilled Spirits': return { tag: 'spirits', style: 'spirits' };
      default:                  return { tag: '',        style: 'frame' };
    }
  }

  // raw records (compact). pal index assigned, derived fields computed below.
  var R = [
    ['Cedar Hollow','Estate Reserve','Wine','TABLE WINE','RED WINE','California','USA','Approved','2025-09-18','2025-08-02','BWC-CA-2241','750 mL','13.5%','cream_burgundy','Cedar Hollow Vineyards, Napa, CA'],
    ['Marisol','Coastal Albariño','Wine','TABLE WINE','WHITE WINE','Spain','Spain','Approved','2025-07-30','2025-06-14','IMP-ES-0098','750 mL','12.5%','sand_teal','Bodegas Marisol, imported by Atlantic Vine Co.'],
    ['Ironwood','Straight Bourbon','Spirits','DISTILLED SPIRITS SPECIALTY','BOURBON WHISKY','Kentucky','USA','Approved','2025-10-05','2025-08-21','DSP-KY-417','750 mL','45%','amber_brown','Ironwood Distilling Co., Bardstown, KY'],
    ['Blue Heron','Hazy IPA','Beer','MALT BEVERAGE','ALE','Oregon','USA','Approved','2026-01-12','2025-12-02','BR-OR-1180','16 fl oz','6.8%','slate_cream','Blue Heron Brewing, Portland, OR'],
    ['Golden Marsh','Brut Sparkling','Wine','SPARKLING WINE','CHAMPAGNE STYLE','France','France','Approved','2025-05-22','2025-03-30','IMP-FR-2210','750 mL','12%','black_gold','Maison Golden Marsh, imported by Reverie Selections'],
    ['Old Tannery','Barrel Gin','Spirits','DISTILLED SPIRITS SPECIALTY','GIN','Tennessee','USA','Pending','2026-02-03','2026-01-19','DSP-TN-209','700 mL','44%','forest_cream','Old Tannery Spirits, Nashville, TN'],
    ['Vela','Rosé of Grenache','Wine','TABLE WINE','ROSE WINE','California','USA','Approved','2025-06-08','2025-04-27','BWC-CA-3318','750 mL','12.8%','blush_plum','Vela Wine Company, Paso Robles, CA'],
    ['Northwind','Cold-Press Cider','Cider','HARD CIDER','APPLE CIDER','Washington','USA','Approved','2025-11-14','2025-10-01','BWC-WA-0771','500 mL','6.2%','forest_cream','Northwind Orchards, Yakima, WA'],
    ['Cardinal & Crow','London Dry','Spirits','DISTILLED SPIRITS SPECIALTY','GIN','New York','USA','Approved','2025-08-19','2025-07-08','DSP-NY-512','750 mL','47%','ink_silver','Cardinal & Crow Distillery, Brooklyn, NY'],
    ['Verde Valle','Reposado','Spirits','DISTILLED SPIRITS SPECIALTY','TEQUILA','Mexico','Mexico','Approved','2025-09-02','2025-07-21','IMP-MX-1044','750 mL','40%','olive_gold','Destileria Verde Valle, imported by Sol & Sand'],
    ['Stonecutter','Imperial Stout','Beer','MALT BEVERAGE','STOUT','Vermont','USA','Approved','2025-12-09','2025-11-03','BR-VT-0345','12 fl oz','9.4%','ink_silver','Stonecutter Brewing, Burlington, VT'],
    ['Halcyon','Late Harvest Riesling','Wine','TABLE WINE','WHITE WINE','New York','USA','Approved','2025-10-27','2025-09-15','BWC-NY-2089','375 mL','9.5%','cream_navy','Halcyon Cellars, Finger Lakes, NY'],
    ['Maris','Limoncello','Spirits','DISTILLED SPIRITS SPECIALTY','CORDIAL/LIQUEUR','Italy','Italy','Approved','2025-07-15','2025-05-29','IMP-IT-0623','500 mL','28%','blush_plum','Maris Liquori, imported by Riviera Imports'],
    ['Foxglove','Dry-Hopped Pilsner','Beer','MALT BEVERAGE','LAGER','Colorado','USA','Approved','2026-01-28','2025-12-18','BR-CO-1456','12 fl oz','5.1%','forest_cream','Foxglove Brewing, Denver, CO'],
    ['Ember & Oak','Single Malt','Spirits','DISTILLED SPIRITS SPECIALTY','WHISKY','Scotland','Scotland','Approved','2025-04-11','2025-02-22','IMP-SC-3301','700 mL','46%','amber_brown','Ember & Oak Distillers, imported by Highland Trade'],
    ['Tidewater','Oyster Stout','Beer','MALT BEVERAGE','STOUT','Maryland','USA','Pending','2026-02-20','2026-02-04','BR-MD-0612','16 fl oz','5.8%','midnight_blue','Tidewater Brewing, Annapolis, MD'],
    ['Solstice','Orange Wine','Wine','TABLE WINE','WHITE WINE','Oregon','USA','Approved','2025-09-29','2025-08-12','BWC-OR-1903','750 mL','12.2%','rust_cream','Solstice Vineyards, Willamette Valley, OR'],
    ['Quillon','Añejo','Spirits','DISTILLED SPIRITS SPECIALTY','TEQUILA','Mexico','Mexico','Approved','2025-06-25','2025-05-10','IMP-MX-2087','750 mL','40%','amber_brown','Casa Quillon, imported by Agave Norte'],
    ['Marrow','Farmhouse Saison','Beer','MALT BEVERAGE','ALE','California','USA','Approved','2025-08-06','2025-06-30','BR-CA-2240','750 mL','6.5%','cream_navy','Marrow Brewing Project, Oakland, CA'],
    ['Petrichor','Pét-Nat','Wine','SPARKLING WINE','SPARKLING WINE','Australia','Australia','Approved','2025-11-30','2025-10-19','IMP-AU-0512','750 mL','11.5%','blush_plum','Petrichor Wines, imported by Southern Cross Selections'],
    ['Wanderlight','Spiced Rum','Spirits','DISTILLED SPIRITS SPECIALTY','RUM','Puerto Rico','USA','Revoked','2024-12-10','2024-10-28','IMP-PR-0188','750 mL','35%','black_gold','Wanderlight Distillery, San Juan, PR'],
    ['Gravel & Grace','Cabernet Franc','Wine','TABLE WINE','RED WINE','Washington','USA','Approved','2025-10-14','2025-09-01','BWC-WA-3390','750 mL','13.9%','cream_burgundy','Gravel & Grace Estate, Walla Walla, WA'],
    ['Lantern Bay','Session Ale','Beer','MALT BEVERAGE','ALE','Massachusetts','USA','Approved','2025-05-19','2025-04-03','BR-MA-0934','12 fl oz','4.6%','sand_teal','Lantern Bay Brewing, Gloucester, MA'],
    ['Saffron Coast','Vermentino','Wine','TABLE WINE','WHITE WINE','Italy','Italy','Approved','2025-07-02','2025-05-18','IMP-IT-2241','750 mL','12.5%','olive_gold','Saffron Coast, imported by Mare Nostrum Wines'],
    ['Cedar Hollow','Hillside Chardonnay','Wine','TABLE WINE','WHITE WINE','California','USA','Approved','2025-11-06','2025-09-24','BWC-CA-2241','750 mL','13.1%','cream_navy','Cedar Hollow Vineyards, Napa, CA'],
    ['Cedar Hollow','Old Vine Zinfandel','Wine','TABLE WINE','RED WINE','California','USA','Approved','2024-08-14','2024-07-01','BWC-CA-2241','750 mL','14.2%','rust_cream','Cedar Hollow Vineyards, Napa, CA'],
    ['Blue Heron','West Coast Pilsner','Beer','MALT BEVERAGE','LAGER','Oregon','USA','Approved','2025-09-10','2025-07-29','BR-OR-1180','12 fl oz','5.2%','sand_teal','Blue Heron Brewing, Portland, OR'],
    ['Ironwood','Rye Whisky','Spirits','DISTILLED SPIRITS SPECIALTY','RYE WHISKY','Kentucky','USA','Approved','2025-03-18','2025-02-02','DSP-KY-417','750 mL','46.5%','black_gold','Ironwood Distilling Co., Bardstown, KY']
  ];

  function ttbId(year, idx) {
    // 14-digit: YY + 3-digit julian-ish + 5-digit sequence + 4 random-ish
    var yy = String(year).slice(2);
    var julian = String(40 + idx * 11).padStart(3, '0');
    var seq = String(1001 + idx).padStart(5, '0');
    var tail = String(100 + (idx * 37) % 900).padStart(4, '0');
    return yy + julian + seq + tail;
  }

  var VARIETALS = ['Albariño','Grenache','Riesling','Cabernet Franc','Vermentino','Chardonnay','Zinfandel'];
  var APPELLATIONS = { 'Cedar Hollow': 'Napa Valley', 'Vela': 'Paso Robles', 'Halcyon': 'Finger Lakes', 'Gravel & Grace': 'Walla Walla Valley', 'Solstice': 'Willamette Valley' };

  // mock image_analysis_items — extracted text w/ bounding boxes per label face
  function labelItems(rec) {
    var items = [
      { face: 'front', file: 'label_1.jpg', type: 'class_type', text: rec.classSub, box: { x: 22, y: 20, w: 56, h: 6 }, conf: 0.94 },
      { face: 'front', file: 'label_1.jpg', type: 'brand_name', text: rec.brand, box: { x: 14, y: 30, w: 72, h: 15 }, conf: 0.99 },
      { face: 'front', file: 'label_1.jpg', type: 'fanciful_name', text: rec.fanciful, box: { x: 20, y: 53, w: 60, h: 7 }, conf: 0.97 },
      { face: 'front', file: 'label_1.jpg', type: 'origin', text: rec.origin, box: { x: 26, y: 63, w: 48, h: 5 }, conf: 0.91 },
      { face: 'front', file: 'label_1.jpg', type: 'net_contents', text: rec.netContents, box: { x: 20, y: 70, w: 26, h: 5 }, conf: 0.88 },
      { face: 'front', file: 'label_1.jpg', type: 'alcohol_content', text: rec.abv + ' ALC/VOL', box: { x: 50, y: 70, w: 30, h: 5 }, conf: 0.90 },
      { face: 'back', file: 'label_2.jpg', type: 'government_warning', text: 'GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic beverages during pregnancy…', box: { x: 12, y: 58, w: 76, h: 18 }, conf: 0.96 },
      { face: 'back', file: 'label_2.jpg', type: 'applicant_name', text: rec.applicant.split(', imported by')[0], box: { x: 16, y: 28, w: 68, h: 7 }, conf: 0.93 },
      { face: 'back', file: 'label_2.jpg', type: 'net_contents', text: rec.netContents, box: { x: 34, y: 80, w: 32, h: 5 }, conf: 0.89 },
      { face: 'neck', file: 'label_3.jpg', type: 'brand_name', text: rec.brand, box: { x: 18, y: 38, w: 64, h: 12 }, conf: 0.95 }
    ];
    return items.map(function (it) { return Object.assign({ model: 'ttb-ocr-v2' }, it, { conf: Math.round((it.conf - (rec.id % 3) * 0.007) * 100) / 100 }); });
  }

  var CAT_MAP = { 'Beer': 'Malt Beverage', 'Spirits': 'Distilled Spirits', 'Cider': 'Wine' };

  var DATA = R.map(function (r, i) {
    var cat = CAT_MAP[r[2]] || r[2];
    var m = meta(cat);
    var pal = PAL[r[13]];
    var approval = r[8];
    var year = parseInt(approval.slice(0, 4), 10);
    return {
      id: i + 1,
      ttbId: ttbId(year, i),
      serial: String(year).slice(2) + (cat === 'Wine' ? 'W' : cat === 'Malt Beverage' ? 'M' : 'S') + String(1000 + i * 7),
      brand: r[0],
      fanciful: r[1],
      category: cat,
      classType: r[3],
      classTypeCode: String(80 + i),
      classSub: r[4],
      originState: r[5],
      originCountry: r[6],
      origin: r[5],
      isDomestic: r[6] === 'USA',
      originGroup: r[6] === 'USA' ? 'Domestic' : 'Imported',
      originCode: r[6] === 'USA' ? '00' : '0' + (10 + i),
      status: r[7],
      approvalDate: r[8],
      receivedDate: r[9],
      permit: r[10],
      netContents: r[11],
      abv: r[12],
      palKey: r[13],
      bg: pal.bg,
      ink: pal.ink,
      applicant: r[14],
      tagClass: m.tag,
      labelStyle: m.style,
      qualifications: i % 4 === 0 ? 'TTB has reviewed this label for compliance with applicable regulations. No statement on the label shall be construed as a guarantee of quality.' : '',
      formula: (cat === 'Distilled Spirits') ? String(900000 + i * 311) : '',
      vendorCode: 'V' + String(20000 + i * 13),
      // schema-aligned detail fields (cola_parsed_data)
      applicationType: 'CERTIFICATE OF LABEL APPROVAL',
      forSaleIn: 'All States',
      bottleCapacity: r[11],
      mailingAddress: r[14].split(', imported by')[0],
      grapeVarietals: cat === 'Wine' ? VARIETALS.filter(function (v) { return r[1].toLowerCase().includes(v.toLowerCase()); }) : [],
      appellation: cat === 'Wine' ? (APPELLATIONS[r[0]] || '') : ''
    };
  });

  DATA.forEach(function (d) { d.imageItems = labelItems(d); });

  function fmtDate(iso) {
    if (!iso) return '—';
    var d = new Date(iso + 'T00:00:00');
    return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
  }

  // simple visual-similarity score generator (deterministic) for image search mock
  function visualScore(rec, seed) {
    var s = (rec.id * 53 + seed * 17) % 100;
    return 62 + (s % 36); // 62-97
  }

  window.COLA = {
    DATA: DATA,
    PAL: PAL,
    palKeys: palKeys,
    fmtDate: fmtDate,
    visualScore: visualScore,
    CATEGORIES: ['Wine', 'Malt Beverage', 'Distilled Spirits'],
    ORIGINS: Array.from(new Set(DATA.map(function (d) { return d.origin; }))).sort(),
    SOURCES: ['Domestic', 'Imported'],
    DOMESTIC_ORIGINS: Array.from(new Set(DATA.filter(function (d) { return d.isDomestic; }).map(function (d) { return d.origin; }))).sort(),
    IMPORTED_ORIGINS: Array.from(new Set(DATA.filter(function (d) { return !d.isDomestic; }).map(function (d) { return d.origin; }))).sort(),
    STATUSES: ['Approved', 'Pending', 'Revoked']
  };
})();
