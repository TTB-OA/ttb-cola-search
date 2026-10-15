"""One-off: raw markup of the old-form NET CONTENTS / ALCOHOL CONTENT / VINTAGE / FAX cells.

Run from inside pipeline/: uv run python ../scripts/_diag_old_cells.py ID [ID ...]
"""
import re
import sys
from urllib.parse import quote

from bs4 import BeautifulSoup

from cola.pipeline.image_ingest import DETAIL_URL_TEMPLATES, build_ttb_session

session = build_ttb_session(verify_tls=True)
HEADINGS = re.compile(r"^\s*\d+\.\s*(NET CONTENTS|ALCOHOL CONTENT|WINE VINTAGE|FAX NUMBER)", re.I)

for cola_id in sys.argv[1:]:
    html = session.get(DETAIL_URL_TEMPLATES[0].format(cola_id=quote(cola_id, safe="")),
                       timeout=60).text
    soup = BeautifulSoup(html, "html.parser")
    print(f"\n===== {cola_id}")
    for tag in soup.select("div.label, div.boldlabel"):
        text = " ".join(tag.get_text(" ").split())
        if HEADINGS.match(text):
            cell = tag.find_parent("td")
            print(f"--- {text[:40]}")
            print("   ", re.sub(r"\s+", " ", str(cell))[:700])
