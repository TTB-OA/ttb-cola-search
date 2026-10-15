"""One-off: dump the item 15 / item 20 / expiration markup from live form-view pages.

Run from inside pipeline/: uv run python ../scripts/_diag_old_form_markup.py ID [ID ...]
"""
import re
import sys
from urllib.parse import quote

from cola.pipeline.image_ingest import (
    DETAIL_URL_TEMPLATES,
    build_ttb_session,
    extract_form_flags,
)

session = build_ttb_session(verify_tls=True)

for cola_id in sys.argv[1:]:
    html = session.get(DETAIL_URL_TEMPLATES[0].format(cola_id=quote(cola_id, safe="")),
                       timeout=60).text
    flat = re.sub(r"\s+", " ", html)
    print(f"\n===== {cola_id}  ({len(html):,} bytes)  form revision: "
          f"{(re.search(r'TTB F 5100\.31 \([^)]*\)', flat) or [None])[0]}")
    for label in ("15. ", "SHOW ANY INFORMATION", "AUTHORIZED SIGNATURE", "publicViewSignature",
                  "EXPIRATION DATE"):
        i = flat.find(label)
        print(f"--- {label!r}: " + (flat[max(0, i - 60):i + 420] if i >= 0 else "NOT FOUND"))
    flags = extract_form_flags(html)
    print("parsed:", {k: flags.get(k) for k in ("ttb_signed", "container_text", "applicant_signature", "printed_name")})
