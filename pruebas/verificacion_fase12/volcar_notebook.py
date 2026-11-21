"""Vuelca un notebook a texto: indice de celda, tipo, fuente y (opcional) salidas de texto."""
import json, sys
ruta = sys.argv[1]; con_salidas = len(sys.argv) > 2 and sys.argv[2] == "salidas"
nb = json.load(open(ruta, encoding="utf-8"))
for i, c in enumerate(nb["cells"]):
    print(f"\n##### CELDA {i} [{c['cell_type']}] #####")
    print("".join(c["source"]))
    if con_salidas and c["cell_type"] == "code":
        for o in c.get("outputs", []):
            if o["output_type"] == "stream":
                print("--- salida:\n" + "".join(o["text"])[:3000])
            elif o["output_type"] in ("execute_result", "display_data"):
                t = o.get("data", {}).get("text/plain")
                if t: print("--- resultado:\n" + "".join(t)[:3000])
            elif o["output_type"] == "error":
                print("--- ERROR:", o.get("ename"), o.get("evalue"))
