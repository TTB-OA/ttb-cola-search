// Holds a pending image-search File between the search form and the results
// page. A File can't ride along in a URL, so we stash it here on submit and
// read it back on the results route.
let pending = null;

export function setPendingImageSearch(payload) {
  pending = payload;
}

// Non-destructive on purpose: StrictMode double-invokes the state initialiser
// that reads this, so consuming on read would drop the file on the second pass.
// The results page clears it once it holds the value.
export function readPendingImageSearch() {
  return pending;
}

export function clearPendingImageSearch() {
  pending = null;
}
