"""API response models. Field names serialize to camelCase to match the UI."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ImageRef(ApiModel):
    file_name: str
    face: str
    img_type: str | None = None
    url: str
    width_px: int | None = None
    height_px: int | None = None
    # 0-100, computed upstream in vw_colas; drives display order.
    visual_interest_score: float | None = None
    visual_interest_rank: int | None = None


class ImageItem(ApiModel):
    face: str
    file: str | None = None
    type: str
    text: str
    conf: float | None = None
    box: dict[str, Any] | None = None
    model: str | None = None


class PermitRef(ApiModel):
    permit_id: str | None = None
    primary: bool = False
    name: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None


class Qualification(ApiModel):
    id: int | None = None
    text: str | None = None
    comment: str | None = None


class ProcessingStatus(ApiModel):
    """Which enrichment passes have run for a COLA.

    Only the list pass is guaranteed; detail fill, image download, OCR and
    embedding are backfilled asynchronously, so these distinguish "absent from
    the data" from "not processed yet".
    """

    detail_loaded: bool = False
    images_loaded: bool = False
    text_analyzed: bool = False
    embedded: bool = False


class ColaSummary(ApiModel):
    # Verbatim TTB id: not numeric, suffixes and embedded spaces occur.
    id: str
    ttb_id: str
    serial: str | None = None
    brand: str | None = None
    fanciful: str | None = None
    category: str
    class_type: str | None = None
    class_sub: str | None = None
    origin: str | None = None
    origin_group: str
    origin_flag: str | None = None
    status: str | None = None
    approval_date: date | None = None
    permit: str | None = None
    permit_id: str | None = None
    permit_name: str | None = None
    permit_city: str | None = None
    permit_state: str | None = None
    applicant: str | None = None
    submitter: str | None = None
    thumb_url: str | None = None
    score: float | None = None


class ColaDetail(ColaSummary):
    class_type_code: str | None = None
    origin_code: str | None = None
    received_code: str | None = None
    received_description: str | None = None
    final_status: bool | None = None
    net_contents: str | None = None
    abv: str | None = None
    mailing_address: str | None = None
    # Items transcribed from the certificate image rather than the API; blank
    # until the form-scrape pass has run for the record.
    source_of_product: str | None = None
    type_of_product: str | None = None
    application_type: str | None = None
    exemption_state: str | None = None
    resubmission_ttb_id: str | None = None
    application_date: date | None = None
    issued_date: date | None = None
    expiration_date: date | None = None
    for_sale_in: str | None = None
    vendor_code: str | None = None
    formula: str | None = None
    appellation: str | None = None
    grape_varietals: list[str] = []
    qualifications: str | None = None
    qualification_items: list[Qualification] = []
    permits: list[PermitRef] = []
    submitter_id: str | None = None
    submitter_phone: str | None = None
    submitter_fax: str | None = None
    images: list[ImageRef] = []
    image_items: list[ImageItem] = []
    details_url: str | None = None
    form_url: str | None = None
    processing: ProcessingStatus = ProcessingStatus()


class FacetBucket(ApiModel):
    value: str
    count: int


class Facets(ApiModel):
    commodity: list[FacetBucket] = []
    source: list[FacetBucket] = []
    origin: list[FacetBucket] = []
    status: list[FacetBucket] = []
    permit_state: list[FacetBucket] = []


class SearchResponse(ApiModel):
    items: list[ColaSummary] = []
    total: int = 0
    # True when the match count hit the server's cap; `total` is then a floor.
    total_is_capped: bool = False
    page: int = 1
    page_size: int = 24
    facets: Facets | None = None


class ReferenceData(ApiModel):
    categories: list[str] = []
    sources: list[str] = []
    statuses: list[str] = []
    domestic_origins: list[str] = []
    imported_origins: list[str] = []
    permit_states: list[str] = []


# ---------------------------------------------------------------------------
# Pipeline coverage
# ---------------------------------------------------------------------------
class CoverageCounts(ApiModel):
    """Records that reached each pipeline stage. Stages are cumulative."""

    # Upstream truth. Null when the pipeline never recorded an expected count
    # for the period, which is not the same as zero.
    api_count: int | None = None
    ingested_count: int = 0
    detail_count: int = 0
    image_count: int = 0
    ocr_count: int = 0
    embedding_count: int = 0


class CoverageYear(CoverageCounts):
    year: int


class SearchIndexStatus(ApiModel):
    """How far the materialised search surface trails the source tables."""

    # Planner estimates (pg_class.reltuples), not exact counts: an exact count
    # of a multi-million-row table costs more than the number is worth here.
    searchable_count: int | None = None
    label_text_count: int | None = None
    # Records queued for re-materialisation, and how long the oldest has waited.
    pending_count: int = 0
    oldest_pending_at: datetime | None = None


class CompleteRange(ApiModel):
    """Oldest and newest COLAs that finished every pipeline stage.

    Both are null until at least one record has cleared detail, images, OCR and
    embedding; they are the same record when only one has.
    """

    earliest: ColaSummary | None = None
    latest: ColaSummary | None = None


class CoverageResponse(ApiModel):
    years: list[CoverageYear] = []
    totals: CoverageCounts = CoverageCounts()
    # Null when the status query failed, so the rest of the page still renders.
    search: SearchIndexStatus | None = None
    # Null when the lookup failed; the rest of the page still renders.
    complete_range: CompleteRange | None = None
    # When the coverage table was last rebuilt; absent if it has never run.
    as_of: datetime | None = None


# ---------------------------------------------------------------------------
# Usage dashboard
# ---------------------------------------------------------------------------
class NamedCount(ApiModel):
    label: str
    count: int


class TimePoint(ApiModel):
    """One bucket of a time series. Extra keys vary by panel."""

    t: datetime
    values: dict[str, float] = {}


class LatencyRow(ApiModel):
    endpoint: str
    requests: int
    p50: float
    p95: float
    p99: float


class TopCola(ApiModel):
    cola_id: str
    views: int
    # Filled in from the database; absent if the record no longer resolves.
    brand_name: str | None = None
    origin: str | None = None


class DashboardPanels(ApiModel):
    """Every panel is optional: one failed query must not blank the page."""

    usage_over_time: list[TimePoint] | None = None
    zero_results_over_time: list[TimePoint] | None = None
    filter_usage: list[NamedCount] | None = None
    paging_depth: list[NamedCount] | None = None
    sort_usage: list[NamedCount] | None = None
    top_colas: list[TopCola] | None = None
    commodity_usage: list[NamedCount] | None = None
    origin_usage: list[NamedCount] | None = None
    latency: list[LatencyRow] | None = None
    reliability: list[TimePoint] | None = None
    status_codes: list[NamedCount] | None = None
    image_search_over_time: list[TimePoint] | None = None
    upload_sizes: list[NamedCount] | None = None


class DashboardTotals(ApiModel):
    searches: int = 0
    detail_views: int = 0
    similar_requests: int = 0
    image_searches: int = 0
    sessions: int = 0
    zero_result_rate: float = 0.0
    failure_rate: float = 0.0
    p95_ms: float = 0.0


class DashboardData(ApiModel):
    range: str
    generated_at: datetime
    # True when this response came from the server-side cache rather than a
    # fresh Log Analytics query.
    cached: bool = False
    totals: DashboardTotals = DashboardTotals()
    panels: DashboardPanels = DashboardPanels()
    # Panels whose query failed, so the UI can say so instead of showing zero.
    unavailable: list[str] = []
