"""One-off: full text of the older 'SHOW ANY WORDING' box and the label headings on old form pages.

Run from inside pipeline/: uv run python ../scripts/_diag_old_item15.py ID [ID ...]
"""
import re
import sys
from urllib.parse import quote

from bs4 import BeautifulSoup

from cola.pipeline.image_ingest import DETAIL_URL_TEMPLATES, build_ttb_session

session = build_ttb_session(verify_tls=True)

for cola_id in sys.argv[1:]:
    html = session.get(DETAIL_URL_TEMPLATES[0].format(cola_id=quote(cola_id, safe="")),
                       timeout=60).text
    soup = BeautifulSoup(html, "html.parser")
    headings = [" ".join(t.get_text(" ").split()) for t in soup.select("div.label, div.boldlabel")]
    print(f"\n===== {cola_id}")
    print("headings:", [h[:45] for h in headings if re.match(r"^\d+a?\.", h)])
    for div in soup.select("div.data"):
        text = " ".join(div.get_text(" ").split())
        if "SHOW ANY WORDING" in text or "SHOW ANY INFORMATION" in text:
            print("item-15 box:", text[:700])
