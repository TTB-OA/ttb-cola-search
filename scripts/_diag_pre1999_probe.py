"""One-off: live re-probe of pre-1999 COLAs against both COLAs Online routes to a label.

Run from inside pipeline/: uv run python ../scripts/_diag_pre1999_probe.py ID [ID ...]
"""
import sys
from urllib.parse import quote

from cola.pipeline.image_ingest import (
    DETAIL_URL_TEMPLATES,
    DIRECT_IMAGE_URL_TEMPLATE,
    build_ttb_session,
    detail_page_is_error,
)

session = build_ttb_session(verify_tls=True)

for cola_id in sys.argv[1:]:
    enc = quote(cola_id, safe="")
    page = session.get(DETAIL_URL_TEMPLATES[1].format(cola_id=enc), timeout=60).text
    attachments = page.count("publicViewAttachment")
    img = session.get(DIRECT_IMAGE_URL_TEMPLATE.format(cola_id=enc), timeout=60)
    kind = img.headers.get("Content-Type", "")
    is_image = kind.startswith("image/") and len(img.content) > 5000
    print(f"{cola_id:>15}  page={'ERROR' if detail_page_is_error(page) else 'ok'}"
          f"  attachments={attachments}  publicViewImage={img.status_code} {kind} "
          f"{len(img.content):,}B  -> {'IMAGE' if is_image else 'no image'}")
