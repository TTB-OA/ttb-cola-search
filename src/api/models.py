"""API response models. Field names serialize to camelCase to match the UI."""
from __future__ import annotations

from datetime import date
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


class ColaSummary(ApiModel):
    id: int
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
    application_type: str | None = None
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
