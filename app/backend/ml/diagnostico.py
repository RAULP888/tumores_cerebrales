"""Diagnóstico automático de convergencia y gráfica de las curvas de entrenamiento."""
import numpy as np

ETIQUETAS = ["convergió", "se detuvo antes de converger", "sobreajuste", "no aprende"]
ETIQUETA_CANCELADO = "cancelado"   # etiqueta aparte: el entrenamiento no terminó

# Umbrales de las reglas (explícitos para poder explicarlos y cambiarlos).
BAJA_MINIMA_PERDIDA = 0.05     # "no aprende": la pérdida de entrenamiento bajó menos de 5 %
MARGEN_MAYORITARIA = 0.01      # "no aprende": la exactitud de validación no supera a la clase mayoritaria + 1 punto
SUBIDA_VALIDACION = 0.10       # "sobreajuste": la pérdida de validación sube más de 10 % tras la mejor época
BRECHA_RELATIVA = 0.30         # "sobreajuste": (val - entrenamiento) / val al final mayor de 30 %
ULTIMAS_EPOCAS = 2             # "se detuvo antes": la mejor época está entre las 2 últimas
RAZON_MEMORIZACION = 0.25      # advertencia: pérdida de entrenamiento menor que 25 % de la de validación
EXACTITUD_MEMORIZACION = 0.995  # advertencia: exactitud de entrenamiento casi perfecta...
BRECHA_EXACTITUD = 0.01        # ...y al menos 1 punto por encima de la de validación


def diagnosticar(historial, epocas_max, paciencia, proporcion_mayoritaria=0.75, cancelado=None):
    """Clasifica cómo terminó un entrenamiento a partir de su historial por época.

    Parámetros
    - historial: dict con listas "loss", "val_loss" y, si existen, "accuracy" y "val_accuracy".
      Si trae "cancelado" (bool) y "val_loss_inicial" (pérdida de validación del modelo de
      partida, como en el ajuste fino), también se usan.
    - epocas_max: tope de épocas que se permitió.
    - paciencia: paciencia de la detención temprana.
    - proporcion_mayoritaria: fracción de la clase más frecuente (tumor). Conviene pasar la real
      del conjunto de entrenamiento; 0.75 es solo el valor por omisión.
    - cancelado: True si el entrenamiento se canceló. Si es None se lee historial["cancelado"].

    La mejor época es la de menor pérdida de validación (se cuenta desde 1). Es un mínimo
    de la pérdida de validación observado en esta corrida, no una garantía de mínimo global.

    Reglas, evaluadas en este orden (gana la primera que se cumple):
    0. "cancelado": el entrenamiento se canceló antes de terminar. No se afirma nada sobre
       la convergencia. (Es una quinta etiqueta, aparte de las cuatro de ETIQUETAS.)
    1. "no aprende": la pérdida de entrenamiento bajó menos de 5 % entre la primera época y
       su mínimo, Y la mejor exactitud de validación no supera a la clase mayoritaria en más
       de 1 punto porcentual.
    2. "sobreajuste": hay al menos 2 épocas después de la mejor, la pérdida de validación
       final es más de 10 % mayor que la de la mejor época, la pérdida de entrenamiento
       siguió bajando después de la mejor época, Y la brecha final
       (validación - entrenamiento) / validación es mayor de 30 %.
    3. "se detuvo antes de converger": se agotaron las épocas máximas (la detención temprana
       no actuó) Y la mejor época está entre las 2 últimas: la pérdida de validación todavía
       estaba bajando.
    4. "convergió": cualquier otro caso; es decir, la detención temprana actuó (se corrieron
       menos épocas que el máximo) o la pérdida de validación se aplanó.

    Advertencias (no cambian la etiqueta; se añaden a la explicación y al campo "advertencias"):
    - No mejoró el punto de partida: el historial trae "val_loss_inicial" y ninguna época
      logró una pérdida de validación menor. La explicación dice que el entrenamiento (por
      ejemplo, el ajuste fino) no mejoró el modelo de partida.
    - Señales de memorización: en la mejor época la pérdida de entrenamiento es menor que
      25 % de la de validación, o la exactitud de entrenamiento es >= 99.5 % y supera a la de
      validación por 1 punto o más.

    Devuelve un dict con: etiqueta, mejor_epoca, explicacion, advertencias (lista de textos),
    epocas_corridas, detencion_temprana (bool), cancelado (bool), mejoro_punto_de_partida
    (bool, o None si no hay punto de partida), perdida_val_inicial, perdida_val_mejor,
    perdida_val_final, perdida_final, exactitud_val_mejor.
    """
    perdida = [float(v) for v in historial.get("loss", [])]
    perdida_val = [float(v) for v in historial.get("val_loss", [])]
    exactitud = [float(v) for v in historial.get("accuracy", [])]
    exactitud_val = [float(v) for v in historial.get("val_accuracy", [])]
    if cancelado is None:
        cancelado = bool(historial.get("cancelado", False))
    inicial = historial.get("val_loss_inicial")
    inicial = None if inicial is None else float(inicial)
    n = min(len(perdida), len(perdida_val))
    base = {"advertencias": [], "cancelado": bool(cancelado), "mejoro_punto_de_partida": None,
            "perdida_val_inicial": inicial}
    if n == 0:
        if cancelado:
            etiqueta = ETIQUETA_CANCELADO
            texto = "El entrenamiento se canceló antes de terminar la primera época. No hay nada que evaluar."
        else:
            etiqueta = "no aprende"
            texto = "No hay ninguna época registrada, así que no se puede evaluar el entrenamiento."
        return {"etiqueta": etiqueta, "mejor_epoca": 0, "explicacion": texto, "epocas_corridas": 0,
                "detencion_temprana": False, "perdida_val_mejor": None, "perdida_val_final": None,
                "perdida_final": None, "exactitud_val_mejor": None, **base}
    perdida, perdida_val = perdida[:n], perdida_val[:n]
    i_mejor = int(np.argmin(perdida_val))
    mejor_epoca = i_mejor + 1
    detencion_temprana = (n < int(epocas_max)) and not cancelado
    val_mejor, val_final = perdida_val[i_mejor], perdida_val[-1]
    ent_mejor, ent_final = perdida[i_mejor], perdida[-1]
    exa_mejor = max(exactitud_val) if exactitud_val else None

    baja = (perdida[0] - min(perdida)) / perdida[0] if perdida[0] > 0 else 0.0
    no_supera = exa_mejor is not None and exa_mejor <= proporcion_mayoritaria + MARGEN_MAYORITARIA
    subida = (val_final - val_mejor) / val_mejor if val_mejor > 0 else 0.0
    brecha = (val_final - ent_final) / val_final if val_final > 0 else 0.0
    epocas_despues = n - mejor_epoca

    if cancelado:
        etiqueta = ETIQUETA_CANCELADO
        explicacion = (f"El entrenamiento se canceló en la época {n} de {epocas_max}, antes de terminar. "
                       "No se puede decir si convergió. Los pesos que quedan son los de la mejor época "
                       f"hasta ese momento (la {mejor_epoca}, pérdida de validación {val_mejor:.4f}).")
    elif baja < BAJA_MINIMA_PERDIDA and no_supera:
        etiqueta = "no aprende"
        explicacion = (f"La pérdida de entrenamiento casi no bajó ({baja:.1%}) y la exactitud de validación "
                       f"({exa_mejor:.1%}) no supera a decir siempre la clase más frecuente "
                       f"({proporcion_mayoritaria:.0%}). El modelo no está aprendiendo.")
    elif (epocas_despues >= 2 and subida > SUBIDA_VALIDACION and ent_final < ent_mejor
          and brecha > BRECHA_RELATIVA):
        etiqueta = "sobreajuste"
        explicacion = (f"Después de la época {mejor_epoca} la pérdida de validación subió {subida:.0%} "
                       f"(de {val_mejor:.4f} a {val_final:.4f}) mientras la de entrenamiento siguió bajando "
                       f"(a {ent_final:.4f}). El modelo empezó a memorizar. Se conservan los pesos de la "
                       f"época {mejor_epoca}.")
    elif not detencion_temprana and epocas_despues < ULTIMAS_EPOCAS:
        etiqueta = "se detuvo antes de converger"
        explicacion = (f"Se agotaron las {epocas_max} épocas permitidas y la mejor fue la {mejor_epoca}, "
                       f"de las últimas: la pérdida de validación todavía estaba bajando ({val_mejor:.4f}). "
                       "Con más épocas podría mejorar un poco.")
    else:
        etiqueta = "convergió"
        if detencion_temprana:
            motivo = (f"la detención temprana actuó en la época {n} de {epocas_max} tras {paciencia} "
                      "épocas sin mejorar")
        else:
            motivo = f"la pérdida de validación se aplanó antes de terminar las {epocas_max} épocas"
        explicacion = (f"La pérdida de validación llegó a su mínimo en la época {mejor_epoca} "
                       f"({val_mejor:.4f}) y {motivo}. Se conservan los pesos de esa época. "
                       "Es un mínimo de la pérdida de validación, no una garantía de mínimo global.")

    advertencias = []
    mejoro = None
    if inicial is not None:
        mejoro = bool(val_mejor < inicial)
        if not mejoro:
            aviso = ("El entrenamiento no mejoró el modelo de partida: la pérdida de validación antes de "
                     f"empezar era {inicial:.4f} y la mejor que se logró fue {val_mejor:.4f} (época "
                     f"{mejor_epoca}). Conviene quedarse con el modelo de partida.")
            advertencias.append(aviso)
            if not cancelado:
                explicacion = aviso + " " + explicacion
    ent_exa = exactitud[i_mejor] if len(exactitud) > i_mejor else None
    val_exa = exactitud_val[i_mejor] if len(exactitud_val) > i_mejor else None
    por_perdida = val_mejor > 0 and ent_mejor < RAZON_MEMORIZACION * val_mejor
    por_exactitud = (ent_exa is not None and val_exa is not None and ent_exa >= EXACTITUD_MEMORIZACION
                     and ent_exa - val_exa >= BRECHA_EXACTITUD)
    if por_perdida or por_exactitud:
        detalle = (f"en la época {mejor_epoca} la pérdida de entrenamiento ({ent_mejor:.4f}) quedó muy por "
                   f"debajo de la de validación ({val_mejor:.4f})")
        if ent_exa is not None and val_exa is not None:
            detalle += f" y la exactitud fue de {ent_exa:.1%} en entrenamiento contra {val_exa:.1%} en validación"
        aviso = (f"Señales de memorización: {detalle}. El modelo se sabe casi de memoria los datos de "
                 "entrenamiento; lo que cuenta es cómo le va en validación y en prueba.")
        advertencias.append(aviso)
        if etiqueta == "convergió":
            explicacion = "Convergió, con señales de memorización. " + explicacion + " " + aviso
        elif etiqueta != ETIQUETA_CANCELADO:
            explicacion = explicacion + " " + aviso
    base.update({"advertencias": advertencias, "mejoro_punto_de_partida": mejoro})
    return {"etiqueta": etiqueta, "mejor_epoca": mejor_epoca, "explicacion": explicacion,
            "epocas_corridas": n, "detencion_temprana": bool(detencion_temprana),
            "perdida_val_mejor": val_mejor, "perdida_val_final": val_final,
            "perdida_final": ent_final, "exactitud_val_mejor": exa_mejor, **base}


def graficar_curvas(historial, mejor_epoca, ruta_png, titulo=None):
    """Guarda un PNG con pérdida, exactitud y tasa de aprendizaje por época.

    Marca la mejor época con una línea vertical. Si el historial trae "val_loss_inicial"
    (ajuste fino) dibuja también ese punto de partida. No usa pyplot (no cambia el estado
    global de Matplotlib), así que se puede llamar desde el backend. Devuelve la ruta del PNG.
    """
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    n = len(historial.get("loss", []))
    epocas = list(range(1, n + 1))
    fig = Figure(figsize=(13, 3.8))
    FigureCanvasAgg(fig)
    ejes = fig.subplots(1, 3)
    paneles = [("loss", "val_loss", "Pérdida"), ("accuracy", "val_accuracy", "Exactitud (salida tumor)")]
    for ax, (k, kv, nombre) in zip(ejes[:2], paneles):
        if historial.get(k):
            ax.plot(epocas, historial[k][:n], marker="o", ms=3, label="entrenamiento")
        if historial.get(kv):
            ax.plot(epocas, historial[kv][:n], marker="o", ms=3, label="validación")
        if k == "loss" and historial.get("val_loss_inicial") is not None:
            ax.axhline(float(historial["val_loss_inicial"]), ls=":", color="tab:red",
                       label="validación antes de empezar")
        if mejor_epoca:
            ax.axvline(mejor_epoca, ls="--", color="gray", label=f"mejor época ({mejor_epoca})")
        ax.set_title(nombre)
        ax.set_xlabel("Época")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
    ax = ejes[2]
    if historial.get("learning_rate"):
        ax.step(epocas, historial["learning_rate"][:n], where="mid", color="tab:green")
        ax.set_yscale("log")
    if mejor_epoca:
        ax.axvline(mejor_epoca, ls="--", color="gray")
    ax.set_title("Tasa de aprendizaje")
    ax.set_xlabel("Época")
    ax.grid(alpha=0.3)
    if titulo:
        fig.suptitle(titulo, fontsize=11)
    fig.tight_layout()
    fig.savefig(str(ruta_png), dpi=130)
    return str(ruta_png)
