/* Gráficas propias en SVG: curvas de aprendizaje y matriz de confusión.
   Sin bibliotecas externas. Todo texto se inserta con textContent. */
"use strict";

(function (TC) {
  const { el, svg } = TC;

  const NOMBRES_ETAPA = { cabeza: "Cabeza densa", ajuste_fino: "Ajuste fino" };
  function nombreEtapa(e) {
    if (NOMBRES_ETAPA[e]) return NOMBRES_ETAPA[e];
    const m = /^pliegue[_\s-]?(\d+)$/i.exec(String(e || ""));
    if (m) return "Pliegue " + m[1];
    return e ? String(e).replace(/_/g, " ") : "Entrenamiento";
  }
  const esPliegue = (e) => /^pliegue/i.test(String(e || ""));

  const COLOR_ENTRENAMIENTO = "#0b5cad";
  const COLOR_VALIDACION = "#c2410c";
  const COLOR_MEJOR = "#0f766e";

  function valorNumerico(v) {
    return typeof v === "number" && Number.isFinite(v) ? v : null;
  }

  function marcasBonitas(minimo, maximo, cantidad = 5) {
    if (minimo === maximo) { minimo -= 0.5; maximo += 0.5; }
    const rango = maximo - minimo;
    const paso0 = rango / cantidad;
    const potencia = Math.pow(10, Math.floor(Math.log10(paso0)));
    const fraccion = paso0 / potencia;
    const paso = (fraccion < 1.5 ? 1 : fraccion < 3 ? 2 : fraccion < 7 ? 5 : 10) * potencia;
    const inicio = Math.floor(minimo / paso) * paso;
    const fin = Math.ceil(maximo / paso) * paso;
    const marcas = [];
    for (let v = inicio; v <= fin + paso / 2; v += paso) marcas.push(Number(v.toFixed(10)));
    return { marcas, minimo: inicio, maximo: fin, paso };
  }

  /**
   * Dibuja una gráfica de líneas.
   * puntos: [{etapa, epoca}], series: [{nombre, valores, color, guion}]
   */
  function graficaLineas({ titulo, puntos, series, indiceMejor, etiquetaMejor, formatoY, limiteY }) {
    const ANCHO = 560, ALTO = 300;
    const M = { izq: 58, der: 18, arr: 26, aba: 46 };
    const ancho = ANCHO - M.izq - M.der;
    const alto = ALTO - M.arr - M.aba;
    const n = puntos.length;

    const todos = [];
    series.forEach((s) => s.valores.forEach((v) => { if (v !== null) todos.push(v); }));
    let minimo = todos.length ? Math.min(...todos) : 0;
    let maximo = todos.length ? Math.max(...todos) : 1;
    if (limiteY) { minimo = Math.max(limiteY[0], minimo); maximo = Math.min(limiteY[1], maximo); }
    const escala = marcasBonitas(minimo, maximo, 5);
    let yMin = escala.minimo, yMax = escala.maximo;
    if (limiteY) { yMin = Math.max(limiteY[0], yMin); yMax = Math.min(limiteY[1], yMax); if (yMax <= yMin) yMax = yMin + escala.paso; }

    const x = (i) => M.izq + (n <= 1 ? ancho / 2 : (i / (n - 1)) * ancho);
    const y = (v) => M.arr + alto - ((v - yMin) / (yMax - yMin)) * alto;

    const resumen = titulo + ". " + n + " épocas registradas" + (indiceMejor !== null && indiceMejor !== undefined ? ". " + etiquetaMejor : "") + ".";
    const raiz = svg("svg", { viewBox: "0 0 " + ANCHO + " " + ALTO, role: "img", "aria-label": resumen });

    // Rejilla y eje Y
    const grupoRejilla = svg("g", null);
    escala.marcas.filter((v) => v >= yMin - 1e-9 && v <= yMax + 1e-9).forEach((v) => {
      grupoRejilla.appendChild(svg("line", { x1: M.izq, x2: M.izq + ancho, y1: y(v), y2: y(v), stroke: "#e2e8f0", "stroke-width": 1 }));
      grupoRejilla.appendChild(svg("text", { x: M.izq - 8, y: y(v) + 4, "text-anchor": "end", "font-size": 11, fill: "#475569", texto: formatoY(v) }));
    });
    raiz.appendChild(grupoRejilla);

    // Separadores de etapa
    for (let i = 0; i < n; i++) {
      const cambio = i === 0 || puntos[i].etapa !== puntos[i - 1].etapa;
      if (!cambio) continue;
      const xs = i === 0 ? M.izq : (x(i - 1) + x(i)) / 2;
      if (i > 0) raiz.appendChild(svg("line", { x1: xs, x2: xs, y1: M.arr, y2: M.arr + alto, stroke: "#94a3b8", "stroke-width": 1, "stroke-dasharray": "2 3" }));
      const etapasDistintas = new Set(puntos.map((p) => p.etapa)).size;
      if (etapasDistintas > 1) {
        raiz.appendChild(svg("text", { x: xs + 4, y: M.arr - 8, "font-size": 11, fill: "#334155", "font-weight": 600, texto: nombreEtapa(puntos[i].etapa) }));
      }
    }

    // Ejes
    raiz.appendChild(svg("line", { x1: M.izq, x2: M.izq + ancho, y1: M.arr + alto, y2: M.arr + alto, stroke: "#64748b", "stroke-width": 1.2 }));
    raiz.appendChild(svg("line", { x1: M.izq, x2: M.izq, y1: M.arr, y2: M.arr + alto, stroke: "#64748b", "stroke-width": 1.2 }));

    // Marcas del eje X (número de época dentro de su etapa)
    const pasoX = Math.max(1, Math.ceil(n / 10));
    for (let i = 0; i < n; i += pasoX) {
      raiz.appendChild(svg("line", { x1: x(i), x2: x(i), y1: M.arr + alto, y2: M.arr + alto + 5, stroke: "#64748b" }));
      raiz.appendChild(svg("text", { x: x(i), y: M.arr + alto + 18, "text-anchor": "middle", "font-size": 11, fill: "#475569", texto: String(puntos[i].epoca) }));
    }
    raiz.appendChild(svg("text", { x: M.izq + ancho / 2, y: ALTO - 6, "text-anchor": "middle", "font-size": 12, fill: "#334155", texto: "Época" }));

    // Mejor época
    if (indiceMejor !== null && indiceMejor !== undefined && indiceMejor >= 0 && indiceMejor < n) {
      const xm = x(indiceMejor);
      raiz.appendChild(svg("line", { x1: xm, x2: xm, y1: M.arr, y2: M.arr + alto, stroke: COLOR_MEJOR, "stroke-width": 2, "stroke-dasharray": "6 4" }));
      const derecha = xm > M.izq + ancho * 0.7;
      raiz.appendChild(svg("text", {
        x: derecha ? xm - 6 : xm + 6, y: M.arr + 14, "text-anchor": derecha ? "end" : "start",
        "font-size": 11.5, "font-weight": 700, fill: COLOR_MEJOR, stroke: "#fff", "stroke-width": 4,
        "paint-order": "stroke", "stroke-linejoin": "round", texto: etiquetaMejor
      }));
    }

    // Series
    series.forEach((s) => {
      let tramo = [];
      const tramos = [];
      s.valores.forEach((v, i) => {
        if (v === null) { if (tramo.length) tramos.push(tramo); tramo = []; }
        else tramo.push([x(i), y(Math.min(Math.max(v, yMin), yMax))]);
      });
      if (tramo.length) tramos.push(tramo);
      tramos.forEach((t) => {
        raiz.appendChild(svg("polyline", {
          points: t.map((p) => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" "),
          fill: "none", stroke: s.color, "stroke-width": 2.4, "stroke-linejoin": "round", "stroke-linecap": "round",
          "stroke-dasharray": s.guion || null
        }));
      });
      s.valores.forEach((v, i) => {
        if (v === null) return;
        const punto = svg("circle", { cx: x(i), cy: y(Math.min(Math.max(v, yMin), yMax)), r: n > 40 ? 2 : 3.2, fill: "#fff", stroke: s.color, "stroke-width": 1.8 });
        punto.appendChild(svg("title", { texto: s.nombre + " · " + nombreEtapa(puntos[i].etapa) + ", época " + puntos[i].epoca + ": " + formatoY(v, true) }));
        raiz.appendChild(punto);
      });
    });

    const leyenda = el("div", { clase: "leyenda" }, series.map((s) => {
      const muestra = svg("svg", { viewBox: "0 0 28 10", "aria-hidden": "true" },
        svg("line", { x1: 1, x2: 27, y1: 5, y2: 5, stroke: s.color, "stroke-width": 3, "stroke-dasharray": s.guion || null }));
      return el("span", null, muestra, s.nombre);
    }), indiceMejor !== null && indiceMejor !== undefined && indiceMejor >= 0 ? el("span", null,
      svg("svg", { viewBox: "0 0 28 10", "aria-hidden": "true" }, svg("line", { x1: 14, x2: 14, y1: 0, y2: 10, stroke: COLOR_MEJOR, "stroke-width": 3, "stroke-dasharray": "3 2" })),
      "Mejor época") : null);

    return el("figure", { clase: "grafica" }, el("h4", null, titulo), raiz, leyenda);
  }

  /**
   * Curvas de aprendizaje (pérdida y exactitud) a partir del historial.
   * La mejor época se marca dentro de la última etapa registrada (el modelo final).
   */
  /**
   * Curvas de aprendizaje con selector de vista cuando hay pliegues de K-fold:
   * «Modelo final» (cabeza y ajuste fino) o cada pliegue por separado.
   */
  function curvasAprendizaje(historial, mejorEpoca, vistaInicial) {
    const datos = (historial || []).filter((h) => h && typeof h === "object");
    if (datos.length === 0) return el("p", { clase: "vacio" }, "Este entrenamiento no tiene historial de épocas.");
    const finales = datos.filter((h) => !esPliegue(h.etapa));
    const pliegues = [];
    datos.forEach((h) => { if (esPliegue(h.etapa) && !pliegues.includes(h.etapa)) pliegues.push(h.etapa); });
    if (pliegues.length === 0) return curvasDeGrupo(datos, mejorEpoca, false);

    const vistas = [];
    if (finales.length) vistas.push({ clave: "final", nombre: "Modelo final (cabeza y ajuste fino)", datos: finales, mejor: mejorEpoca, calcular: false });
    pliegues.forEach((p) => vistas.push({ clave: p, nombre: nombreEtapa(p) + " de la validación cruzada", datos: datos.filter((h) => h.etapa === p), mejor: null, calcular: true }));

    const idSelector = "vista-curvas-" + Math.random().toString(36).slice(2, 8);
    const selector = el("select", { id: idSelector }, vistas.map((v) => el("option", { value: v.clave }, v.nombre)));
    const destino = el("div");
    const pintar = () => {
      const vista = vistas.find((v) => v.clave === selector.value) || vistas[0];
      TC.vaciar(destino).appendChild(curvasDeGrupo(vista.datos, vista.mejor, vista.calcular));
    };
    selector.addEventListener("change", pintar);
    if (vistaInicial && vistas.some((v) => v.clave === vistaInicial)) selector.value = vistaInicial;
    pintar();
    return el("div", null,
      el("div", { clase: "campo", style: "max-width:360px;margin-bottom:.6rem" }, el("label", { for: idSelector }, "Curvas que se muestran"), selector),
      destino);
  }

  function curvasDeGrupo(datos, mejorEpoca, calcularMejor) {
    const puntos = datos.map((h) => ({ etapa: h.etapa || "", epoca: h.epoca }));

    if (calcularMejor) {
      // Para un pliegue: la mejor época es la de menor pérdida de validación registrada.
      let menor = Infinity;
      datos.forEach((h) => { if (typeof h.perdida_val === "number" && h.perdida_val < menor) { menor = h.perdida_val; mejorEpoca = Number(h.epoca); } });
    }
    let indiceMejor = null;
    let etiquetaMejor = "";
    if (typeof mejorEpoca === "number" && mejorEpoca > 0) {
      // La mejor época se busca en la etapa (de la última a la primera) cuyo mínimo de pérdida
      // de validación cae justo en esa época; si ninguna coincide, en la última etapa que la tenga.
      const etapas = [];
      puntos.forEach((p) => { if (!etapas.includes(p.etapa)) etapas.push(p.etapa); });
      let etapaMejor = null;
      for (let k = etapas.length - 1; k >= 0 && etapaMejor === null; k--) {
        let menor = Infinity, epocaMenor = null;
        datos.forEach((h) => { if ((h.etapa || "") === etapas[k] && typeof h.perdida_val === "number" && h.perdida_val < menor) { menor = h.perdida_val; epocaMenor = Number(h.epoca); } });
        if (epocaMenor === mejorEpoca) etapaMejor = etapas[k];
      }
      for (let i = puntos.length - 1; i >= 0; i--) {
        if (Number(puntos[i].epoca) === mejorEpoca && (etapaMejor === null || puntos[i].etapa === etapaMejor)) { indiceMejor = i; break; }
      }
      const variasEtapas = etapas.length > 1;
      etiquetaMejor = "Mejor época: " + mejorEpoca + (variasEtapas && indiceMejor !== null ? " (" + nombreEtapa(puntos[indiceMejor].etapa).toLowerCase() + ")" : "");
    }

    const decimales = (v, largo) => (largo ? v.toFixed(4) : v.toFixed(v < 1 ? 2 : 1));
    const porcentaje = (v, largo) => (v * 100).toFixed(largo ? 2 : 0) + " %";

    const perdida = graficaLineas({
      titulo: "Pérdida por época",
      puntos,
      series: [
        { nombre: "Entrenamiento", valores: datos.map((h) => valorNumerico(h.perdida)), color: COLOR_ENTRENAMIENTO },
        { nombre: "Validación", valores: datos.map((h) => valorNumerico(h.perdida_val)), color: COLOR_VALIDACION, guion: "7 4" }
      ],
      indiceMejor, etiquetaMejor, formatoY: decimales, limiteY: [0, Infinity]
    });
    const exactitud = graficaLineas({
      titulo: "Exactitud por época",
      puntos,
      series: [
        { nombre: "Entrenamiento", valores: datos.map((h) => valorNumerico(h.exactitud)), color: COLOR_ENTRENAMIENTO },
        { nombre: "Validación", valores: datos.map((h) => valorNumerico(h.exactitud_val)), color: COLOR_VALIDACION, guion: "7 4" }
      ],
      indiceMejor, etiquetaMejor, formatoY: porcentaje, limiteY: [0, 1]
    });

    const tablaDatos = TC.tabla([
      { titulo: "Etapa", celda: (h) => nombreEtapa(h.etapa) },
      { titulo: "Época", clase: "num", celda: (h) => String(h.epoca) },
      { titulo: "Pérdida", clase: "num", celda: (h) => TC.decimal(h.perdida, 4) },
      { titulo: "Pérdida val.", clase: "num", celda: (h) => TC.decimal(h.perdida_val, 4) },
      { titulo: "Exactitud", clase: "num", celda: (h) => TC.pct(h.exactitud, 2) },
      { titulo: "Exactitud val.", clase: "num", celda: (h) => TC.pct(h.exactitud_val, 2) },
      { titulo: "Tasa de aprendizaje", clase: "num", celda: (h) => (TC.esNumero(h.tasa_aprendizaje) ? h.tasa_aprendizaje.toExponential(1) : "—") }
    ], datos);

    return el("div", null,
      el("div", { clase: "graficas" }, perdida, exactitud),
      el("details", { style: "margin-top:.6rem" }, el("summary", null, "Ver los datos de las curvas en tabla"), el("div", { clase: "tabla-contenedor" }, tablaDatos))
    );
  }

  /** Matriz de confusión 2×2 rotulada: [[vn, fp], [fn, vp]]. */
  function matrizConfusion(matriz) {
    if (!Array.isArray(matriz) || matriz.length !== 2 || !Array.isArray(matriz[0]) || !Array.isArray(matriz[1])) {
      return el("p", { clase: "vacio" }, "No hay matriz de confusión disponible.");
    }
    const [[vn, fp], [fn, vp]] = matriz;
    const celda = (valor, sigla, descripcion, clase) =>
      el("td", { clase }, el("strong", null, TC.num(Number(valor))), sigla + " · " + descripcion);
    return el("table", { clase: "matriz" },
      el("caption", null, "Filas: diagnóstico real · Columnas: predicción del modelo"),
      el("thead", null,
        el("tr", null, el("td", null), el("th", { scope: "colgroup", colspan: 2, clase: "matriz__eje" }, "Predicho")),
        el("tr", null, el("td", null), el("th", { scope: "col" }, "Sin tumor"), el("th", { scope: "col" }, "Tumor"))),
      el("tbody", null,
        el("tr", null, el("th", { scope: "row" }, "Real: Sin tumor"),
          celda(vn, "VN", "verdaderos negativos", "matriz__acierto"),
          celda(fp, "FP", "falsas alarmas", "matriz__error")),
        el("tr", null, el("th", { scope: "row" }, "Real: Tumor"),
          celda(fn, "FN", "tumores no detectados", "matriz__fn"),
          celda(vp, "VP", "verdaderos positivos", "matriz__acierto")))
    );
  }

  Object.assign(TC, { curvasAprendizaje, matrizConfusion, nombreEtapa });
})(window.TC);
