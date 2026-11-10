// CSV building and file download for exported search results.
//
// Text searches are exported by the API (GET /colas/export.csv), which can
// reach every match. Image and describe results exist only as the rows already
// on screen, so those are written here; the columns mirror EXPORT_COLUMNS in
// src/api/routers/colas.py so both files open the same way.

export const EXPORT_COLUMNS = [
  ['TTB ID', 'ttbId'],
  ['Serial Number', 'serial'],
  ['Status', 'status'],
  ['Approval Date', 'approvalDate'],
  ['Brand Name', 'brand'],
  ['Fanciful Name', 'fanciful'],
  ['Commodity', 'category'],
  ['Class/Type', 'classType'],
  ['Class/Type Description', 'classSub'],
  ['Domestic/Imported', 'originGroup'],
  ['Origin', 'origin'],
  ['Applicant', 'applicant'],
  ['Permit Number', 'permit'],
  ['Primary Permit', 'permitId'],
  ['Permit Holder', 'permitName'],
  ['Permit City', 'permitCity'],
  ['Permit State', 'permitState'],
  ['Submitter', 'submitter'],
];

// Spreadsheet apps read a cell starting with one of these as a formula, and
// brand and applicant names are applicant-supplied text.
const FORMULA_LEAD = /^[=+\-@\t\r]/;

function cell(value) {
  if (value === null || value === undefined) return '';
  let s = String(value);
  if (FORMULA_LEAD.test(s)) s = `'${s}`;
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

// `extra` adds leading columns, e.g. [['Rank', (r, i) => i + 1]].
export function resultsToCsv(rows, extra = []) {
  const header = [...extra.map(([h]) => h), ...EXPORT_COLUMNS.map(([h]) => h)];
  const lines = [header.map(cell).join(',')];
  rows.forEach((r, i) => {
    lines.push([...extra.map(([, get]) => get(r, i)), ...EXPORT_COLUMNS.map(([, key]) => r[key])].map(cell).join(','));
  });
  // The byte-order mark makes Excel read the file as UTF-8.
  return '﻿' + lines.join('\r\n') + '\r\n';
}

export function exportFilename(prefix = 'cola-search') {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${prefix}-${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}.csv`;
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Let the browser start the download before the URL is revoked.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
