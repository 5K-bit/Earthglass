"""Bounded public-feed verification. Fixtures and inaccessible feeds are never reported as live."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from earthglass.spatial.engine import default_feeds
from earthglass.spatial.models import Viewport
from earthglass.spatial.network import PublicHTTP

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--providers",nargs="*")
    parser.add_argument("--output",type=Path,default=Path("artifacts/live-provider-verification.json"))
    args=parser.parse_args()
    now=datetime.now(timezone.utc)
    http=PublicHTTP(timeout=16)
    ny=Viewport(west=-74.2,south=40.5,east=-73.7,north=40.9)
    london=Viewport(west=-.4,south=51.3,east=.2,north=51.7)
    sf=Viewport(west=-122.6,south=37.5,east=-122.1,north=37.9)
    feeds=[feed for feed in default_feeds(http,lambda _:None) if not args.providers or feed.spec.id in args.providers]
    def verify(feed):
        if feed.spec.credential or feed.spec.transport=="websocket":
            return {"provider":feed.spec.id,"status":"unavailable","reason":"credential_not_configured","live_verified":False}
        viewport=Viewport(west=-180,south=-90,east=180,north=90) if feed.spec.layer=="satellites" else london if feed.spec.id=="tfl" else sf if feed.spec.id.startswith("caltrans") else ny
        try:
            records=feed.fetch(viewport,now)
            return {"provider":feed.spec.id,"status":"received" if records else "empty_coverage","records":len(records),
                    "rejected":feed.rejected,"live_verified":True,
                    "measurement_kinds":sorted({r.measurement_kind for r in records}),"attribution":feed.spec.attribution,
                    "notes":"Road catalog only; live congestion not verified" if feed.spec.layer=="traffic" else None}
        except Exception as exc:
            return {"provider":feed.spec.id,"status":"unavailable","reason":getattr(exc,"code",type(exc).__name__),"live_verified":False}
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            result={"checked_at":now.isoformat(),"credentials_used":False,"results":list(pool.map(verify,feeds))}
    finally:http.close()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))
if __name__=="__main__":main()
