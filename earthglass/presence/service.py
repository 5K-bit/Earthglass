"""Optional local gateway process. Cloud/Tailscale setup is an explicit later operator step."""

import argparse
from pathlib import Path
import uvicorn
from .gateway import build_presence_gateway
from .store import PresenceStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--local-http",
        action="store_true",
        help="Allow loopback HTTP for local development only",
    )
    parser.add_argument(
        "--create-owner-token",
        action="store_true",
        help="Create a revocable one-time-displayed owner credential; does not enable tracking",
    )
    args = parser.parse_args()
    store = PresenceStore(args.data_dir / "presence.sqlite3")
    try:
        if args.create_owner_token:
            with store._lock, store._con:
                credential = store._credential(
                    "owner", "operator", "Gateway owner", {}, days=30
                )
            print(
                "Store this owner token securely; it is displayed only once. Tracking remains disabled."
            )
            print(credential["token"])
            return
        assets = Path(__file__).resolve().parents[1] / "desktop_assets"
        if not assets.exists():
            assets = Path(__file__).resolve().parents[2] / "obeos-earth" / "dist"
        app = build_presence_gateway(store, assets, require_tls=not args.local_http)
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=args.port,
            access_log=False,
            log_level="warning",
            proxy_headers=True,
            forwarded_allow_ips="127.0.0.1",
        )
    finally:
        store.close()


if __name__ == "__main__":
    main()
