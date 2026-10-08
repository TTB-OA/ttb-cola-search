"""One-off: run the detail-page parsers against live COLAs Online pages.

Run from inside pipeline/: uv run python ../scripts/_diag_form_parse.py
"""
from cola.pipeline.image_ingest import (
    DETAIL_URL_TEMPLATES,
    build_ttb_session,
    detail_page_is_error,
    extract_form_flags,
    extract_search_view_fields,
)

E_FILED = ("26195001000391", "24183001000094", "26212001000481")
PAPER = ("00154000000090", "17032002000006")

session = build_ttb_session(verify_tls=True)

for cola_id in E_FILED:
    html = session.get(DETAIL_URL_TEMPLATES[0].format(cola_id=cola_id), timeout=60).text
    assert not detail_page_is_error(html), cola_id
    flags = extract_form_flags(html)
    print(f"\n== form view {cola_id}")
    for key, value in flags.items():
        if value is not None:
            print(f"  {key:22} {value!r}")

for cola_id in PAPER:
    html = session.get(DETAIL_URL_TEMPLATES[1].format(cola_id=cola_id), timeout=60).text
    assert not detail_page_is_error(html), cola_id
    print(f"\n== search view {cola_id}")
    print(" ", extract_search_view_fields(html))
