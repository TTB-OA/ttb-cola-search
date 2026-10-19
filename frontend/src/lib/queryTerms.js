// Split a keyword query into the terms worth highlighting, mirroring the API's
// websearch_to_tsquery parsing: "quoted phrases" stay together, bare words are
// matched independently, `or` is an operator, and `-term` is an exclusion.
export function queryTerms(q) {
  const src = String(q || '').replace(/[%*]/g, ' ');
  const terms = [];
  const re = /(-?)"([^"]*)"|(\S+)/g;
  let m;
  while ((m = re.exec(src))) {
    if (m[3] !== undefined) {
      const word = m[3].replace(/"/g, '');
      if (word.startsWith('-') || word.toLowerCase() === 'or') continue;
      terms.push(word.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, ''));
    } else if (!m[1]) {
      terms.push(m[2].trim().replace(/\s+/g, ' '));
    }
  }
  return [...new Set(terms.map((t) => t.toLowerCase()).filter(Boolean))];
}

const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

// Case-insensitive pattern matching any term; phrase words tolerate any run of whitespace.
export function termsPattern(terms) {
  const list = (Array.isArray(terms) ? terms : [terms]).map((t) => String(t || '').trim()).filter(Boolean);
  if (!list.length) return null;
  const alts = list
    .sort((a, b) => b.length - a.length)
    .map((t) => t.split(/\s+/).map(escapeRe).join('\\s+'));
  return new RegExp(`(${alts.join('|')})`, 'gi');
}

export function matchesTerms(text, terms) {
  const re = termsPattern(terms);
  return !!(re && text && re.test(String(text)));
}
