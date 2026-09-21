// Holds pending image-search Files between the search form and the results
// page. A File can't ride along in a URL, so we stash it here on submit and
// put the returned handle in the URL instead.
//
// A map rather than a single slot is what makes the back button work: returning
// to /results?mode=image&isid=... after opening a detail page finds the upload
// again instead of a dead end.
const MAX_STASHED = 5;

const stash = new Map();
let seq = 0;

export function setPendingImageSearch(payload) {
  const id = `${Date.now().toString(36)}${(seq++).toString(36)}`;
  stash.set(id, payload);
  // Map iterates in insertion order, so the first key is the oldest upload.
  while (stash.size > MAX_STASHED) stash.delete(stash.keys().next().value);
  return id;
}

export function readPendingImageSearch(id) {
  return (id && stash.get(id)) || null;
}
