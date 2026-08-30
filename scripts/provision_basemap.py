"""Upload the PMTiles basemap archive to blob storage.

The map page reads its basemap through ``/api/map/basemap``, which proxies a
single PMTiles archive out of the same private container as the label images.
That archive is a build artefact, not pipeline output, so it is provisioned by
hand with this script rather than by the ingest jobs.

    uv run python -m scripts.provision_basemap --source <url-or-path> [--fonts <dir>]

Protomaps publishes a daily planet build under a permissive licence; a smaller
regional extract can be cut from it with the `pmtiles` CLI and passed here as a
local path instead. Either way the archive is opaque to this script.

`--fonts` mirrors a directory of glyph ranges from protomaps/basemaps-assets so
the map can draw place labels without calling a third-party font host. It is
optional: without it the basemap renders unlabelled.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
from azure.core.exceptions import ResourceNotFoundError
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob import ContentSettings
from azure.storage.blob.aio import BlobClient
from dotenv import load_dotenv

# Blob storage caps a single-shot upload well below the size of a planet build,
# so it is staged in chunks; this is the chunk, not the whole file.
CHUNK_BYTES = 8 * 1024 * 1024
CONTENT_TYPE = "application/vnd.pmtiles"


def _human(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:,.1f} {unit}"
        size /= 1024
    return f"{size:,.1f} GB"


async def _download(source: str, target: Path) -> Path:
    """Fetch a remote archive to `target`, resuming nothing and verifying size."""
    print(f"downloading {source}")
    timeout = aiohttp.ClientTimeout(total=None, sock_read=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(source) as response:
            response.raise_for_status()
            expected = int(response.headers.get("content-length") or 0)
            written = 0
            with target.open("wb") as handle:
                async for chunk in response.content.iter_chunked(CHUNK_BYTES):
                    handle.write(chunk)
                    written += len(chunk)
                    if expected:
                        print(
                            f"  {_human(written)} / {_human(expected)}",
                            end="\r",
                            flush=True,
                        )
    print()
    if expected and written != expected:
        raise RuntimeError(f"truncated download: {written} of {expected} bytes")
    return target


async def _upload(client: BlobClient, path: Path, force: bool) -> bool:
    """Upload `path`, unless an identically sized archive is already there."""
    size = path.stat().st_size
    try:
        existing = await client.get_blob_properties()
    except ResourceNotFoundError:
        existing = None

    if existing is not None and not force:
        if existing.size == size:
            print(f"already uploaded ({_human(size)}); pass --force to replace")
            return False
        print(f"replacing existing archive of {_human(existing.size)}")

    print(f"uploading {_human(size)} to {client.blob_name}")
    with path.open("rb") as handle:
        await client.upload_blob(
            handle,
            overwrite=True,
            max_concurrency=4,
            content_settings=ContentSettings(content_type=CONTENT_TYPE),
        )
    return True


async def _upload_fonts(
    account_url: str, container: str, credential, fonts: Path, prefix: str
) -> int:
    """Mirror a glyph directory to ``<prefix>/fonts/<stack>/<range>.pbf``.

    The layout has to match what MapLibre asks for, because the glyph endpoint
    maps the request path straight onto blob names.
    """
    ranges = sorted(fonts.glob("*/*.pbf"))
    if not ranges:
        raise SystemExit(f"no glyph ranges found under {fonts}")

    print(f"uploading {len(ranges)} glyph ranges")
    for index, path in enumerate(ranges, start=1):
        name = f"{prefix}/fonts/{path.parent.name}/{path.name}"
        client = BlobClient(
            account_url=account_url,
            container_name=container,
            blob_name=name,
            credential=credential,
        )
        try:
            with path.open("rb") as handle:
                await client.upload_blob(
                    handle,
                    overwrite=True,
                    content_settings=ContentSettings(
                        content_type="application/x-protobuf"
                    ),
                )
        finally:
            await client.close()
        print(f"  {index} / {len(ranges)}", end="\r", flush=True)
    print()
    return len(ranges)


async def provision(source: str, blob_name: str, fonts: str | None, force: bool) -> None:
    account_url = os.environ.get("BLOB_ACCOUNT_URL")
    container = os.environ.get("BLOB_CONTAINER")
    if not account_url or not container:
        raise SystemExit("BLOB_ACCOUNT_URL and BLOB_CONTAINER must be set")

    is_url = urlparse(source).scheme in ("http", "https")
    local = Path(source) if not is_url else Path(f"./{Path(urlparse(source).path).name}")
    if is_url and not local.exists():
        await _download(source, local)
    if not local.is_file():
        raise SystemExit(f"no such archive: {local}")

    credential = DefaultAzureCredential()
    client = BlobClient(
        account_url=account_url,
        container_name=container,
        blob_name=blob_name,
        credential=credential,
    )
    try:
        uploaded = await _upload(client, local, force)
        await client.close()
        if fonts:
            await _upload_fonts(
                account_url,
                container,
                credential,
                Path(fonts),
                blob_name.rsplit("/", 1)[0],
            )
    finally:
        await credential.close()

    if uploaded:
        print(f"done. set MAP_BASEMAP_BLOB={blob_name}")


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        required=True,
        help="URL or local path of the .pmtiles archive to upload.",
    )
    parser.add_argument(
        "--blob-name",
        default=os.environ.get("MAP_BASEMAP_BLOB") or "basemap/basemap.pmtiles",
        help="Destination blob name. Must match MAP_BASEMAP_BLOB in the API config.",
    )
    parser.add_argument(
        "--fonts",
        help="Directory of glyph ranges (<fontstack>/<range>.pbf) to mirror. "
        "Without it the basemap renders without place labels.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an archive of the same size that is already uploaded.",
    )
    args = parser.parse_args(argv)

    asyncio.run(provision(args.source, args.blob_name, args.fonts, args.force))
    return 0


if __name__ == "__main__":
    sys.exit(main())
