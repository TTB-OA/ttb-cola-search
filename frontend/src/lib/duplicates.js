// Vector search marks a result whose matched image is near-identical to a
// higher-ranked one with `duplicateOf`; fold those under their lead so each
// distinct piece of artwork is reviewed once.
export function groupDuplicates(rows) {
  const groups = [];
  const byId = new Map();
  for (const r of rows || []) {
    const lead = r.duplicateOf && byId.get(r.duplicateOf);
    if (lead) {
      lead.dupes.push(r);
    } else {
      const g = { lead: r, dupes: [] };
      groups.push(g);
      byId.set(r.id, g);
    }
  }
  return groups;
}
