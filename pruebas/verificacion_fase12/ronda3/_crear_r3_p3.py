"""Genera r3_p3_metricas.py a partir del guion de la ronda 2 (cambia las comprobaciones de pliegues a la división por grupos)."""
import io
from pathlib import Path

aqui = Path(__file__).resolve().parent
s = io.open(aqui.parent / "ronda2" / "r2_p4_metricas.py", encoding="utf-8").read()


def rep(a, b):
    global s
    assert s.count(a) == 1, (a, s.count(a))
    s = s.replace(a, b)


rep('"""Ronda 2 · Punto 4 ·', '"""Ronda 3 · Punto 3 ·')
rep('''from sklearn.model_selection import StratifiedKFold
me = man_ent.reset_index(drop=True)
mis = np.zeros(len(me), dtype=int)
for k, (_, iv) in enumerate(StratifiedKFold(5, shuffle=True, random_state=42).split(np.zeros(len(me)), me.clase), 1):
    mis[iv] = k
print("Imágenes cuyo pliegue difiere de StratifiedKFold(5, shuffle=True, random_state=42) por clase:",''',
    '''from sklearn.model_selection import StratifiedGroupKFold
me = man_ent.reset_index(drop=True)
mis = np.zeros(len(me), dtype=int)
for k, (_, iv) in enumerate(StratifiedGroupKFold(5, shuffle=True, random_state=42).split(np.zeros(len(me)), me.clase, me.grupo_similitud), 1):
    mis[iv] = k
print("Imágenes cuyo pliegue difiere de StratifiedGroupKFold(5, shuffle=True, random_state=42) por clase y grupo_similitud:",''')
rep('''from sklearn.model_selection import train_test_split
_, iv = train_test_split(np.arange(len(me)), test_size=0.15, stratify=me.clase, random_state=42)
print("rutas_val es exactamente la división 15 % esperada:", bool((me.ruta.to_numpy()[iv] == rutas_v).all()))''',
    '''_, iv = list(StratifiedGroupKFold(7, shuffle=True, random_state=42).split(np.zeros(len(me)), me.clase, me.grupo_similitud))[0]
print("rutas_val es exactamente 1 de 7 partes por grupos:", set(me.ruta.to_numpy()[iv]) == set(rutas_v), "· n =", len(rutas_v))''')
io.open(aqui / "r3_p3_metricas.py", "w", encoding="utf-8", newline="\n").write(s)
compile(s, "r3_p3_metricas.py", "exec")
print("ok")
