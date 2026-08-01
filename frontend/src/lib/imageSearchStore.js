// Holds a pending image-search File between the search form and the results
// page. A File can't ride along in a URL, so we stash it here on submit and
// read it back on the results route. Cleared once consumed.
let pending = null;

export function setPendingImageSearch(payload) {
  pending = payload;
}

export function takePendingImageSearch() {
  const p = pending;
  return p;
}

export function clearPendingImageSearch() {
  pending = null;
}
