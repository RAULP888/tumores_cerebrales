"""Rutas con '..' en /media enviadas por socket crudo (httpx normaliza los '..' y no sirve para esto)."""
import json
import socket
import sys

import httpx

BASE = ("127.0.0.1", 8765)
c = httpx.Client(base_url="http://127.0.0.1:8765")
c.post("/api/login", json={"usuario": "doctor1", "password": "Doctor2026!", "rol": "doctor"})
token = c.cookies.get("ts_sesion")

RUTAS = ["/media/../entorno/verif.db", "/media/../../../CLAUDE.md", "/media/..%2F..%2F..%2FCLAUDE.md",
         "/media/..%5C..%5Cverif.db", "/media/%2e%2e/%2e%2e/%2e%2e/CLAUDE.md", "/media/%2e%2e%2f%2e%2e%2fverif.db",
         "/media/....//....//CLAUDE.md", "/media/..", "/media/..\\..\\verif.db",
         "/media/" + "a" * 32 + "_img.png/../../../CLAUDE.md", "/media/C:%5CWindows%5Cwin.ini",
         "/media/%252e%252e%252fCLAUDE.md", "/../../CLAUDE.md", "/..%2F..%2FCLAUDE.md", "/%2e%2e/%2e%2e/CLAUDE.md",
         "/..%5C..%5C.env", "/js/../../../CLAUDE.md", "/js/..%2F..%2F..%2FCLAUDE.md"]
salida = []
for ruta in RUTAS:
    s = socket.create_connection(BASE, timeout=10)
    s.sendall(f"GET {ruta} HTTP/1.1\r\nHost: 127.0.0.1\r\nCookie: ts_sesion={token}\r\nConnection: close\r\n\r\n".encode("latin-1"))
    datos = b""
    while True:
        b = s.recv(65536)
        if not b:
            break
        datos += b
    s.close()
    estado = datos.split(b"\r\n", 1)[0].decode("latin-1", "replace")
    cuerpo = datos.split(b"\r\n\r\n", 1)[-1]
    fuga = any(m in cuerpo for m in (b"SQLite format", b"Reglas que no se negocian", b"[fonts]", b"ANTHROPIC_API_KEY="))
    salida.append({"ruta": ruta, "estado": estado, "fuga": fuga, "inicio": cuerpo[:70].decode("utf-8", "replace")})
    print(("FUGA " if fuga else "ok   ") + f"{ruta} -> {estado} {cuerpo[:60]!r}")
open(sys.argv[1] if len(sys.argv) > 1 else "traversal.json", "w", encoding="utf-8").write(json.dumps(salida, ensure_ascii=False, indent=2))
print("FUGAS:", sum(x["fuga"] for x in salida))
