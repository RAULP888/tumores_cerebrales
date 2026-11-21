"""Latencia de /api/estado con un cliente persistente, separando muestras con y sin entrenamiento activo."""
import json
import sqlite3
import statistics
import sys
import time
from pathlib import Path

import httpx

AQUI = Path(__file__).resolve().parent
DB = AQUI / "entorno" / "verif.db"
dur = float(sys.argv[1]) if len(sys.argv) > 1 else 90
c = httpx.Client(base_url="http://127.0.0.1:8765", timeout=30)
con, sin = [], []
fin = time.time() + dur
while time.time() < fin:
    db = sqlite3.connect(DB)
    activo = db.execute("SELECT COUNT(*) FROM entrenamientos WHERE estado IN ('en_cola','corriendo')").fetchone()[0] > 0
    db.close()
    t = time.perf_counter()
    c.get("/api/estado")
    ms = (time.perf_counter() - t) * 1000
    (con if activo else sin).append(ms)
    time.sleep(0.25)
r = {k: ({"n": len(v), "mediana_ms": round(statistics.median(v), 1), "max_ms": round(max(v), 1)} if v else None)
     for k, v in (("durante_entrenamiento", con), ("sin_entrenamiento", sin))}
print(json.dumps(r))
(AQUI / "evidencia_latencia_estado.json").write_text(json.dumps(r, indent=2), encoding="utf-8")
