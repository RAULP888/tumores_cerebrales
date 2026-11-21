# Desviaciones y precisiones del contrato de la API (Fases 3, 4 y 5)

Ninguna ruta del contrato de `CLAUDE.md` cambió de nombre, método ni forma de respuesta. Lo que
sigue son **agregados** (campos o rutas extra que no rompen el contrato) y **precisiones** sobre
puntos que el contrato no fijaba.

## Agregados
1. `GET /api/admin/entrenamientos/{id}/curvas` (solo administrador): devuelve el PNG de las curvas.
   Es el destino de `curvas_url` en `GET /api/admin/entrenamientos/{id}`; `curvas_url` es `null` si
   no hay curvas (por ejemplo, si se canceló).
2. `POST /api/admin/entrenamientos` acepta un campo opcional `paciencia` (1 a 300; por omisión 8).
   Límites: `epocas_max` 1 a 300, `tasa` 0.000001 a 0.1, `lote` 8 a 512.
3. `GET /api/admin/modelos`: cada modelo trae además `origen_metricas` (`"prueba"` para los clásicos,
   `"validacion"` para la red). Las métricas de la red v001 son las de su validación apartada y las de
   un candidato son de su validación: **un candidato nunca se evalúa en prueba**.
4. `GET /api/admin/umbral` trae además `version` (la del modelo en producción).
5. `PUT /api/admin/umbral` responde `{ok, valor, anterior, version}`.
6. `POST /api/admin/modelos/{id}/aprobar` y `POST /api/admin/modelos/revertir` responden
   `{ok, version, modelo_id}`.
7. `GET /api/admin/resumen`: `modelo_produccion` es un objeto `{modelo_id, version, nombre, umbral}`
   (o `null`). `pct_tumor` va en porcentaje de 0 a 100 con un decimal. Solo cuenta `origen='uso'`.
8. `GET /api/admin/usuarios` → `{usuarios:[{usuario_id, usuario, rol, activo, creado_en}]}`;
   `POST` y `PUT` devuelven el usuario con ese mismo formato (nunca el hash).

## Precisiones
- **Fecha del estudio:** `hecho_prediccion.fecha_id` es la **fecha del estudio** (`fecha_estudio`) y
  `creado_en` es cuándo se subió. Los filtros `desde`/`hasta` de `GET /api/estudios` usan `creado_en`.
  Para las filas de prueba, `fecha_id` es la fecha de la corrida que generó los resultados.
- **Diagnóstico predicho:** `diagnostico_predicho_id` es `tumor` o `sin_tumor` (la decisión binaria);
  el tipo más probable va en `tipo_probable` (y es `null` si no hay tumor). El confirmado puede ser
  cualquiera de las 5 claves.
- **Confirmación:** si `de_acuerdo` es `true` pero `diagnostico_real` contradice el resultado
  (p. ej. el sistema dijo "tumor" y el real es `sin_tumor`), se responde 422.
- **Identificador:** se pasa a mayúsculas y debe cumplir `^[A-Z]{2,5}-\d{1,6}$` (p. ej. `PAC-0001`).
- **Errores de validación** (422) devuelven `{"detail": "texto en español"}`, no la lista de Pydantic.
- **Historial de épocas:** `etapa` puede ser `pliegue_1` … `pliegue_5` (validación cruzada),
  `cabeza` o `ajuste_fino`. Para graficar la curva del modelo final, usar `cabeza`/`ajuste_fino`.
- **Estados del entrenamiento:** al pedir la cancelación el estado pasa de inmediato a `cancelado`
  (con `etapa` todavía en curso); cuando el proceso se detiene, `etapa` queda en `cancelado`.
  La bitácora registra `ENTRENAMIENTO_CANCELADO` dos veces: la solicitud y la detención del proceso.
  Los eventos que escribe el proceso de fondo (`ENTRENAMIENTO_TERMINADO`, la detención de
  `ENTRENAMIENTO_CANCELADO` y `ENTRENAMIENTO_ERROR`) llevan el usuario que pidió el entrenamiento y la
  IP desde la que lo pidió (guardada en `entrenamientos.parametros` como `ip_solicitud`).
- **Revertir:** regresa a la versión de la red que estuvo en producción más recientemente antes de
  la actual; la actual pasa a `retirado`. Si no hay ninguna, 409.
- **Usuarios:** un alta o un cambio rechazado (contraseña corta, usuario repetido, desactivarse a sí
  mismo...) responde el error y además queda en la bitácora como `USUARIO_CREADO`/`USUARIO_ACTUALIZADO`
  con `exito=0` y el motivo (nunca la contraseña).
- **Documentación de la API:** `/api/docs` y `/api/openapi.json` están apagados; se encienden solo con la
  variable de entorno `TS_DOCS=1`.

## Asistente de consultas (Fase 5)
`POST /api/admin/asistente` `{pregunta}` → `{estado, respuesta, sql, columnas, filas}`, como en el contrato.
- `estado`: `ok` (consulta ejecutada y respuesta redactada), `bloqueada` (el validador rechazó la consulta,
  o el modelo indicó que la pregunta no se puede responder con datos o pide modificar datos; `respuesta`
  trae el motivo), `error` (falla de la API, rechazo del modelo, consulta que no se pudo ejecutar o
  tiempo agotado) o `sin_configurar` (no hay `ANTHROPIC_API_KEY`).
- `sql`: la consulta **final** que se ejecutó (regenerada por sqlglot, con `LIMIT`/`TOP` forzado); en
  `bloqueada` puede traer la consulta rechazada; `null` si no hubo consulta.
- `columnas`: lista de nombres; `filas`: lista de listas (máximo `ASISTENTE_LIMITE_FILAS`).
- Salida estructurada de la primera llamada: `{puede_responder, sql, explicacion, motivo}` (equivale a
  `{sql, explicacion}` o `{sql: null, motivo}`: cuando no se puede responder, `puede_responder=false` y
  `sql=""`, porque el esquema estricto usa tipos simples).
- Si la pregunta empieza como una sentencia SQL (`SELECT`, `WITH`, `DROP`...), se trata como consulta
  escrita por el administrador: pasa por el mismo validador y no se manda a Claude para generarla.
- Los identificadores de paciente escritos en la pregunta (patrón `AAA-123`) se reemplazan por
  `[identificador]` antes de enviarla a la API y de registrarla.
- No se hizo el endpoint opcional de borrador de reporte (`/api/estudios/{id}/borrador`).

## Vistas nuevas para Power BI y el asistente
`vw_metricas_modelo` (matriz de confusión por versión de modelo y origen, casos confirmados) y
`vw_estudios_semana` (estudios de uso por semana ISO y doctor). Están en SQLite (`tablas.py`) y en
T-SQL (`sql/01_crear_tablas.sql`).

## Columnas adicionales a las de CLAUDE.md
- `dim_modelo`: `sensibilidad`, `especificidad`, `f1`, `auc`, `origen_metricas`, `aprobado_en`.
- `entrenamientos`: `etapa`, `progreso`, `mensaje`, `explicacion`, `advertencias` (JSON), `curvas`, `pid`.
- `metricas_pliegue`: `metrica_id` (llave primaria).
