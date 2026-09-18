"""Deterministic backend track benchmark; fixtures are explicitly simulated."""
import json
import statistics
import tempfile
import time
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from datetime import datetime,timezone,timedelta
from earthglass.spatial.history import SpatialHistory
from earthglass.spatial.models import Observation,Viewport

def tracks(count=10000):
    now=datetime.now(timezone.utc)
    return [Observation(entity_id=f"simulated:{index:05}",layer="aircraft",entity_type="aircraft",
        measurement_kind="simulated",observed_at=now,received_at=now,
        position={"latitude":40.3+(index%100)*.008,"longitude":-74.5+(index//100)*.012,"altitude_m":2000+(index%20)*100,"altitude_reference":"ellipsoid"},
        motion={"heading_deg":index%360,"speed_mps":100},
        properties={"name":f"SIM {index:05}","purpose":"Deterministic performance fixture"},
        provenance={"provider":"performance_fixture","source_id":str(index),"source_url":"https://example.org/","attribution":"OBEOS simulated benchmark"})
        for index in range(count)]

def run():
    with tempfile.TemporaryDirectory() as directory:
        history=SpatialHistory(Path(directory)/"history.sqlite3")
        values=tracks();started=time.perf_counter()
        for offset in range(0,len(values),1000):history.ingest(values[offset:offset+1000])
        ingestion=time.perf_counter()-started
        latencies=[]
        for _ in range(50):
            started=time.perf_counter()
            history.query(viewport=Viewport(west=-75,south=40,east=-73,north=42),limit=2000)
            latencies.append((time.perf_counter()-started)*1000)
        result={"tracks":len(values),"batch_ingestion_seconds":ingestion,"cached_query_limit":2000,
                "cached_query_p50_ms":statistics.median(latencies),"cached_query_p95_ms":sorted(latencies)[47],
                "target_p95_ms":250,"history":history.stats()}
        result["target_met"]=result["cached_query_p95_ms"]<250
        history.close()
    output=Path("artifacts/spatial-benchmark.json");output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2),encoding="utf-8");print(json.dumps(result,indent=2))
if __name__=="__main__":run()
