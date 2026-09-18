"""Import a public GTFS archive into an existing Earth data directory without network access."""

import argparse, json
from pathlib import Path
from .static_gtfs import StaticGTFSFeed, import_gtfs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--agency", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--attribution", required=True)
    args = parser.parse_args()
    if args.archive.stat().st_size > 64 * 1024 * 1024:
        parser.error("Archive exceeds 64 MiB")
    document = import_gtfs(
        args.archive.read_bytes(),
        agency=args.agency,
        source_url=args.source_url,
        attribution=args.attribution,
    )
    feed = StaticGTFSFeed(None)
    feed.configure_cache(args.data_dir / "history" / "provider-cache")
    print(json.dumps(feed.install(document), indent=2))


if __name__ == "__main__":
    main()
