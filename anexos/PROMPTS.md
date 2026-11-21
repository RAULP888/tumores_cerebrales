# Anexo: prompts del asistente de consultas (IA generativa)

Fuente única de verdad: `app/backend/asistente.py`. Este anexo se generó importando ese módulo, igual que
`notebooks/05_ia_generativa.ipynb`, así que los textos son exactamente los que usa la aplicación.

## Propósito
El Administrador escribe una pregunta en español sobre el uso del sistema. El asistente la convierte en **una consulta
SQL de solo lectura** sobre una lista blanca de vistas, la valida, la ejecuta y redacta la respuesta en lenguaje sencillo.
Son dos llamadas a la API de Claude por pregunta:

| Llamada | Propósito | Salida |
|---|---|---|
| 1. Generar la consulta | Traducir la pregunta a SQL sobre la lista blanca | JSON con `puede_responder`, `sql`, `explicacion`, `motivo` (salida estructurada con JSON Schema) |
| 2. Redactar la respuesta | Explicar en español los resultados (máximo 50 filas) | Texto |

## Modelo y parámetros
- Modelo: `ANTHROPIC_MODELO` del archivo `.env`; por omisión `claude-opus-5-5`.
- Endpoint: `client.beta.messages.create(...)` (SDK `anthropic` 2.12).
- `max_tokens = 4000`; `output_config = {"effort": "medium"}` (y en la llamada 1 además
  `"format": {"type": "json_schema", "schema": ...}`).
- No se envía `thinking` (en este modelo siempre está activo; desactivarlo da error 400). No se usa prefill del asistente ni
  `tool_choice` forzado.
- Respaldo del servidor ante rechazos: `betas=["server-side-fallback-2026-07-01"]` y `fallbacks="default"` (se puede apagar con
  `ASISTENTE_RESPALDO=false`). En la prueba real la API lo aceptó junto con la salida estructurada.
- Se revisa `stop_reason` antes de leer el contenido: `refusal` → `estado="error"` ("El modelo se negó a responder"),
  `max_tokens` → `estado="error"` ("respuesta incompleta").
- Errores del SDK (de más específico a más general): `AuthenticationError`, `PermissionDeniedError`, `RateLimitError`,
  `APIStatusError`, `APIConnectionError`. Al usuario solo llega un mensaje fijo en español; nunca el texto del error ni la clave.

## Llamada 1: generar la consulta
### Prompt del sistema
Variables que se sustituyen: `{motor}` (SQLite o Microsoft Fabric), `{dialecto}` (`sqlite` o `tsql`), `{esquema}`
(la lista blanca con columnas y significado) y `{limite}` (`ASISTENTE_LIMITE_FILAS`).

Plantilla:
```text
Eres el asistente de consultas de un tablero hospitalario académico que apoya la detección de tumores cerebrales en resonancias. Ayudas al Administrador a obtener datos con UNA consulta SQL de solo lectura.

Motor: {motor} (dialecto {dialecto}).

Reglas obligatorias:
1. Escribe UNA sola sentencia SELECT (se permite WITH ... SELECT). Nunca INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, PRAGMA, ATTACH, EXEC ni nada que cambie datos.
2. Usa solo estas vistas y columnas. No existen otras tablas para ti:
{esquema}
3. No escribas comentarios (-- o /* */) ni punto y coma intermedio.
4. Prefiere resultados agregados (conteos, promedios, porcentajes) en lugar de listas largas. El sistema limita la respuesta a {limite} filas.
5. Los valores booleanos son 1 y 0. Para porcentajes multiplica por 100.0 para evitar división entera, y usa NULLIF para no dividir entre cero.
6. "Esta semana", "hoy", etc. se refieren a la fecha que viene en el mensaje. Usa las columnas anio y semana (semana ISO) para semanas.
7. No hay datos que identifiquen pacientes; no intentes obtenerlos.
8. Si la pregunta pide modificar o borrar datos, pide información que no está en estas vistas, o no es sobre estos datos, responde puede_responder=false, sql vacío y explica el motivo en español.

Responde solo con el objeto JSON pedido: puede_responder (booleano), sql (la consulta, o "" si no se puede), explicacion (una oración en español sobre qué calcula la consulta) y motivo (por qué no se puede responder, o "").
```

Valor de `{esquema}` (lista blanca):
```text
- vw_predicciones: Una fila por predicción. origen='uso' son estudios reales subidos por doctores; origen='prueba' son los resultados de los 5 modelos sobre el conjunto de prueba.
    * prediccion_id: número de la predicción
    * origen: 'uso' o 'prueba'
    * creado_en: fecha y hora en que se registró
    * fecha: fecha del estudio
    * anio: año de la fecha del estudio
    * mes: mes (1-12)
    * nombre_mes: nombre del mes en español
    * semana: semana ISO del año
    * dia_semana: día de la semana en español
    * edad: edad del paciente ficticio (NULL en prueba)
    * grupo_edad: '0-17', '18-39', '40-59' o '60+'
    * sexo: 'F', 'M' u 'Otro'
    * doctor: usuario del doctor que subió el estudio (NULL en prueba)
    * modelo: nombre del modelo
    * tipo_modelo: 'clasico' o 'red_keras'
    * modelo_version: versión del modelo (v001, v002... para la red)
    * estado_modelo: 'referencia', 'candidato', 'produccion' o 'retirado'
    * diagnostico_predicho: 'tumor' o 'sin_tumor' (decisión del modelo)
    * predicho_tumor: 1 si el modelo dijo tumor, 0 si no
    * diagnostico_confirmado: diagnóstico real confirmado: sin_tumor, tumor, glioma, meningioma o pituitary (NULL si está pendiente)
    * confirmado_tumor: 1 si el diagnóstico confirmado es tumor, 0 si no, NULL si pendiente
    * probabilidad_tumor: probabilidad de tumor (0 a 1)
    * umbral: umbral de decisión usado
    * tipo_probable: tipo de tumor más probable (NULL si no hay tumor)
    * probabilidad_tipo: probabilidad del tipo
    * de_acuerdo: 1 si el doctor estuvo de acuerdo, 0 si no, NULL si no ha confirmado
    * tiempo_respuesta_ms: tiempo de respuesta del modelo en milisegundos (solo uso)
    * acierto: 1 si la predicción coincide con lo confirmado, 0 si no, NULL si pendiente
    * falso_negativo: 1 si el modelo dijo sin tumor y sí había tumor
    * falso_positivo: 1 si el modelo dijo tumor y no había
- vw_estudios_semana: Estudios de uso por semana ISO (de la fecha del estudio) y doctor.
    * anio: año
    * semana: semana ISO
    * primer_dia: primera fecha con estudios en esa semana
    * doctor: usuario del doctor
    * estudios: número de estudios
    * con_posible_tumor: estudios en que el modelo dijo tumor
    * confirmados: estudios ya confirmados por el doctor
    * desacuerdos: estudios en que el doctor no estuvo de acuerdo
- vw_metricas_modelo: Matriz de confusión por versión de modelo y origen, solo con casos confirmados.
    * modelo_id: id del modelo
    * modelo: nombre
    * tipo_modelo: 'clasico' o 'red_keras'
    * modelo_version: versión
    * estado_modelo: estado del modelo
    * origen: 'uso' o 'prueba'
    * casos: casos confirmados
    * vp: verdaderos positivos
    * vn: verdaderos negativos
    * fp: falsos positivos
    * fn: falsos negativos
    * tiempo_promedio_ms: tiempo promedio de respuesta de esos casos (NULL en prueba)
- vw_modelos: Catálogo de modelos.
    * modelo_id: id
    * nombre: nombre
    * tipo: 'clasico' o 'red_keras'
    * version: versión
    * estado: 'referencia', 'candidato', 'produccion' o 'retirado'
    * umbral: umbral de decisión
    * sensibilidad: sensibilidad registrada
    * especificidad: especificidad registrada
    * f1: F1
    * auc: AUC
    * origen_metricas: 'prueba' o 'validacion' (de dónde salen las métricas)
    * entrenamiento_id: entrenamiento que lo generó
    * aprobado_en: última vez que pasó a producción
    * creado_en: fecha de registro
- vw_entrenamientos: Entrenamientos y reentrenamientos de la red.
    * entrenamiento_id: id
    * estado: 'en_cola', 'corriendo', 'terminado', 'cancelado' o 'error'
    * epocas_max: épocas máximas
    * epoca_actual: última época
    * mejor_epoca: época de menor pérdida de validación
    * diagnostico: 'convergió', 'se detuvo antes de converger', 'sobreajuste', 'no aprende' o 'cancelado'
    * iniciado_en: inicio
    * terminado_en: fin
    * version: versión del modelo generado
    * solicitado_por: usuario que lo pidió
- vw_metricas_pliegue: Métricas por pliegue de la validación cruzada.
    * entrenamiento_id: entrenamiento (NULL para los clásicos)
    * modelo: nombre del modelo
    * modelo_version: versión
    * pliegue: número de pliegue (1-5)
    * sensibilidad: sensibilidad
    * especificidad: especificidad
    * precision: precisión
    * f1: F1
    * auc: AUC
    * vp: verdaderos positivos
    * vn: verdaderos negativos
    * fp: falsos positivos
    * fn: falsos negativos
- vw_historial_epocas: Historial por época de cada entrenamiento.
    * entrenamiento_id: entrenamiento
    * etapa: 'pliegue_1'..'pliegue_5', 'cabeza' o 'ajuste_fino'
    * epoca: época (desde 1)
    * perdida: pérdida de entrenamiento
    * exactitud: exactitud de entrenamiento
    * perdida_val: pérdida de validación
    * exactitud_val: exactitud de validación
    * tasa_aprendizaje: tasa de aprendizaje
- vw_bitacora: Bitácora de acciones del sistema.
    * evento_id: id
    * fecha_hora: fecha y hora
    * usuario: usuario
    * rol: 'doctor' o 'administrador'
    * accion: LOGIN_OK, LOGIN_FALLIDO, LOGOUT, ACCESO_DENEGADO, ESTUDIO_CREADO, ESTUDIO_CONFIRMADO, ENTRENAMIENTO_*, MODELO_APROBADO, MODELO_REVERTIDO, UMBRAL_ACTUALIZADO, USUARIO_*, CONSULTA_IA, CONSULTA_IA_BLOQUEADA o CARGA_DATOS
    * detalle: detalle en texto
    * exito: 1 si la acción tuvo éxito, 0 si no
- dim_fecha: Calendario.
    * fecha_id: AAAAMMDD
    * fecha: fecha
    * anio: año
    * mes: mes
    * nombre_mes: nombre del mes
    * semana: semana ISO
    * dia_semana: día de la semana
- dim_diagnostico: Catálogo de diagnósticos.
    * diagnostico_id: id
    * clave: sin_tumor, tumor, glioma, meningioma o pituitary
    * nombre: nombre en español
    * es_tumor: 1 si es tumor
- dim_usuario: Usuarios del sistema (sin contraseñas).
    * usuario_id: id
    * usuario: nombre de usuario
    * rol: 'doctor' o 'administrador'
    * activo: 1 si está activo
```

### Mensaje del usuario
Variables: `{hoy}`, `{anio}`, `{semana}` (semana ISO) y `{pregunta}`. Antes de sustituir la pregunta se ocultan los
identificadores de paciente que contenga (patrón `AAA-123` → `[identificador]`).
```text
Fecha de hoy: {hoy} (año {anio}, semana ISO {semana}).

<pregunta>
{pregunta}
</pregunta>
```

### Esquema de la salida estructurada
```json
{
  "type": "object",
  "properties": {
    "puede_responder": {
      "type": "boolean"
    },
    "sql": {
      "type": "string"
    },
    "explicacion": {
      "type": "string"
    },
    "motivo": {
      "type": "string"
    }
  },
  "required": [
    "puede_responder",
    "sql",
    "explicacion",
    "motivo"
  ],
  "additionalProperties": false
}
```

## Llamada 2: redactar la respuesta
### Prompt del sistema
```text
Eres el asistente de consultas de un tablero hospitalario académico de apoyo a la detección de tumores cerebrales. Recibes la pregunta del Administrador, la consulta SQL que se ejecutó y sus resultados. Redacta la respuesta en español de México, formal, sencillo y claro, en 1 a 4 oraciones o una lista corta.

Reglas:
- Usa solo los números que aparecen en los resultados; no inventes ni extrapoles. Si no hay filas, dilo.
- Si los resultados vienen recortados, indícalo.
- No des diagnósticos médicos ni recomendaciones clínicas; es información de apoyo sobre el uso del sistema.
- No menciones detalles técnicos de SQL salvo que ayuden a entender el resultado.
```

### Mensaje del usuario
Variables: `{pregunta}`, `{sql}` (la consulta ya validada), `{n_filas}`, `{n_mostradas}`, `{columnas}` y `{filas}`
(como máximo 50, una por línea en JSON, sin columnas sensibles).
```text
<pregunta>
{pregunta}
</pregunta>

<consulta_sql>
{sql}
</consulta_sql>

<resultados filas_totales="{n_filas}" filas_mostradas="{n_mostradas}">
columnas: {columnas}
{filas}
</resultados>
```

## Reglas de seguridad (las aplica el código, no solo el prompt)
1. **Una sola sentencia** `SELECT` o `WITH ... SELECT`; sin comentarios; sin `;` intermedio.
2. **Sin DML ni DDL en ningún nodo** del árbol de sqlglot (`INSERT`, `UPDATE`, `DELETE`, `MERGE`, `DROP`, `ALTER`, `CREATE`,
   `TRUNCATE`, `GRANT`, `EXEC`, `SELECT ... INTO`, `PRAGMA`, `ATTACH`...), y además una revisión por palabras clave fuera de
   las cadenas de texto.
3. **Solo tablas de la lista blanca**, también en subconsultas y CTE; sin otros esquemas ni bases; sin funciones de tabla
   (p. ej. `pragma_table_info`).
4. **Sin funciones peligrosas** (`load_extension`, `readfile`, `writefile`, `OPENROWSET`, `OPENQUERY`, `xp_*`, `sp_*`...).
5. **Límite de filas forzado** a `ASISTENTE_LIMITE_FILAS` (`LIMIT` en SQLite, `TOP` en T-SQL); la consulta que se ejecuta es la
   regenerada por sqlglot, no el texto original.
6. **Conexión de solo lectura** con tiempo máximo (`ASISTENTE_SEGUNDOS_SQL`): SQLite `mode=ro` + `PRAGMA query_only`; en Fabric
   `ApplicationIntent=ReadOnly`, transacción revertida y un usuario con solo lectura (`db_datareader`).
7. **Sin datos de pacientes**: la lista blanca no tiene identificadores; se ocultan los que vengan en la pregunta y se quitan
   columnas sensibles (identificador, hash, contraseña, token, ip) antes de devolver o enviar filas.
8. Si la "pregunta" ya es SQL escrito por el administrador, pasa por el mismo validador y no se manda a Claude para generar.
9. Bitácora: `CONSULTA_IA` (pregunta y consulta) o `CONSULTA_IA_BLOQUEADA` (con el motivo).
10. La clave `ANTHROPIC_API_KEY` vive solo en `.env`; nunca se devuelve, ni se registra, ni aparece en errores.

## Ejemplos reales (API de Claude, modelo `claude-opus-5-5`, 21 de noviembre de 2026, base local)
Ejecutados con la clave de `.env` contra la base local de demostración. Son salidas reales, copiadas sin editar.

### Pregunta: "¿Cuántos estudios con posible tumor hubo esta semana por doctor?"
- Estado: `ok` (6.1 s en total)
- Consulta generada y validada:
```sql
SELECT doctor, SUM(con_posible_tumor) AS estudios_con_posible_tumor, SUM(estudios) AS estudios_totales FROM vw_estudios_semana WHERE anio = 2026 AND semana = 47 GROUP BY doctor ORDER BY estudios_con_posible_tumor DESC LIMIT 200
```
- Columnas: doctor, estudios_con_posible_tumor, estudios_totales
- Filas: [["doctor1", 2, 3]]
- Respuesta:

> En la semana 47 de 2026 solo **doctor1** registró estudios: **2 de sus 3 estudios** fueron marcados por el sistema con posible tumor. No hubo registros de otros doctores en esa semana.
> 
> Este dato refleja únicamente lo que señaló el sistema y no constituye un diagnóstico.

### Pregunta: "¿Cuál es la sensibilidad y la especificidad de cada modelo en el conjunto de prueba?"
- Estado: `ok` (7.4 s en total)
- Consulta generada y validada:
```sql
SELECT modelo, tipo_modelo, modelo_version, estado_modelo, casos, ROUND(vp * 100.0 / NULLIF(vp + fn, 0), 2) AS sensibilidad_pct, ROUND(vn * 100.0 / NULLIF(vn + fp, 0), 2) AS especificidad_pct FROM vw_metricas_modelo WHERE origen = 'prueba' ORDER BY modelo, modelo_version LIMIT 200
```
- Columnas: modelo, tipo_modelo, modelo_version, estado_modelo, casos, sensibilidad_pct, especificidad_pct
- Filas: [["Logística (MobileNetV2)", "clasico", "logistica_mobilenet", "referencia", 720, 97.84, 86.3], ["Logística (rasgos básicos)", "clasico", "logistica_basica", "referencia", 720, 97.68, 30.14], ["Random Forest (MobileNetV2)", "clasico", "random_forest", "referencia", 720, 98.3, 79.45], ["Red Keras (MobileNetV2)", "red_keras", "v001", "produccion", 720, 96.75, 89.04], ["SVM RBF (MobileNetV2)", "clasico", "svm_rbf", "referencia", 720, 97.84, 86.3]]
- Respuesta:

> En el conjunto de prueba (720 casos por modelo), estos son los resultados de los 5 modelos:
> 
> - **Red Keras (MobileNetV2)**, en producción: sensibilidad 96.75 % y especificidad 89.04 %.
> - **Logística (MobileNetV2)**, de referencia: sensibilidad 97.84 % y especificidad 86.3 %.
> - **SVM RBF (MobileNetV2)**, de referencia: sensibilidad 97.84 % y especificidad 86.3 %.
> - **Random Forest (MobileNetV2)**, de referencia: sensibilidad 98.3 % y especificidad 79.45 %.
> - **Logística (rasgos básicos)**, de referencia: sensibilidad 97.68 % y especificidad 30.14 %.
> 
> Todos los modelos tienen una sensibilidad similar, entre 96.75 % y 98.3 %. La especificidad varía mucho más: el modelo en producción tiene la más alta y la Logística con rasgos básicos, la más baja.

### Pregunta: "Borra la tabla de usuarios"
- Estado: `bloqueada` (2.2 s en total)
- Consulta generada y validada:
```sql
(ninguna)
```
- Columnas: (ninguna)
- Filas: []
- Respuesta:

> La solicitud pide borrar datos (eliminar la tabla de usuarios). Este asistente solo puede ejecutar consultas de lectura (SELECT) y no puede modificar ni eliminar información.

## Ejemplo de rechazo por el validador (simulado en pytest)
En `pruebas/test_asistente.py` un cliente **simulado** devuelve `DROP TABLE usuarios` como si fuera la consulta del modelo; el
validador la bloquea (`estado="bloqueada"`, motivo "La consulta contiene una instrucción no permitida: DROP.") y queda
`CONSULTA_IA_BLOQUEADA` en la bitácora, sin ejecutar nada ni hacer la segunda llamada.
