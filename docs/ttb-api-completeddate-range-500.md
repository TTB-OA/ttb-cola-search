# Public COLA Registry API: `completedDate` range filters return HTTP 500

**Reported:** 2026-10-28
**First observed:** 2026-10-27, between 16:22Z and 18:21Z. The last successful request was at 16:22Z; every request since 18:21Z has failed.
**API:** `https://my.ttb.gov/api/public-cola-registry`

## Summary

Every range operator on `completedDate` now returns **HTTP 500 "Specification must not be null"**. This affects both `GET /colas` and `GET /colas/count`. The same requests returned 200 until 2026-10-27. The published OpenAPI spec (`/v3/api-docs`) still lists these parameters as optional `date` filters, and no parameter has been renamed or made required.

## Affected requests

| Request | Result |
|---|---|
| `completedDate.greaterThanOrEqual=2026-10-22&completedDate.lessThanOrEqual=2026-10-22` | **500** |
| `completedDate.greaterThanOrEqual=2026-10-22` (alone) | **500** |
| `completedDate.lessThanOrEqual=2026-10-22` (alone) | **500** |
| `completedDate.greaterThan=...&completedDate.lessThan=...` | **500** |
| Range filter + `ttbId.equals` or `brandName.contains` | **500** |
| Same requests on `/colas/count` | **500** |

The result does not depend on the `sort` parameter (the request fails with or without it) or on the date requested (older dates such as 2026-10-01 also fail).

## Requests that still work

| Request | Result |
|---|---|
| `/colas?page=0&size=10` (no filter) | 200 |
| `completedDate.equals=2026-10-22` | 200 (518 rows) |
| `completedDate.in=2026-10-21,2026-10-22` | 200 (1,110 rows) |
| `ttbId.equals=...`, `brandName.contains=...` | 200 |
| `/colas/{ttbId}` | 200 |

## Example

```
GET /api/public-cola-registry/colas?completedDate.greaterThanOrEqual=2026-10-22&completedDate.lessThanOrEqual=2026-10-22&page=0&size=10
X-API-KEY: <key>
Accept: application/json
```

Response (truncated):

```json
HTTP 500
{"cause":null,"detail":"Specification must not be null","instance":null,
 "localizedMessage":"Internal Server Error: Specification must not be null",
 "message":"Internal Server Error: Specification must not be null",
 "parameters":{"path":"/api/public-cola-registry/colas","message":"error.http.500"},
 "stackTrace":[...]}
```

## Possible cause

The message comes from Spring Data JPA when a `null` `Specification` is passed to `findAll` or `count`. The likely cause is that the range-filter branch of the query or criteria service (for `LocalDate` range filters) now returns `null` instead of a specification. A recent deployment or dependency upgrade may have introduced this. Equality and `in` filters go through a different path and are unaffected.

## Impact

Clients that collect COLAs by date window can no longer use date ranges. Our nightly ingestion failed from 2026-10-27 18:21Z until we switched to `completedDate.equals` and `completedDate.in`. Other consumers that use ranges are probably affected too.

## Related observation

`completedDate.in` returns an HTTP 400 (Tomcat HTML error page) when given a full year of dates (365 values). A list of 183 values works. This is most likely the request-line length limit. It only matters while range filters are broken, because clients then have to list every date.

## Requested action

1. Restore `completedDate` range operators (`greaterThan`, `greaterThanOrEqual`, `lessThan`, `lessThanOrEqual`) on `/colas` and `/colas/count`.
2. If the operators were removed on purpose, update `/v3/api-docs` to match and return a 400 with a clear message rather than a 500.
