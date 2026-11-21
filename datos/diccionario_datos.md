# Diccionario de datos

Documenta las columnas **reales** de los archivos y de la base, tomadas de `notebooks/01_eda.ipynb`,
`app/backend/tablas.py` (dueño del esquema), `sql/01_crear_tablas.sql` (equivalente en T-SQL para
Fabric) y `app/backend/DESVIACIONES_CONTRATO.md`. Los conteos son de la corrida del
21 de noviembre de 2026.

Tipos: en SQLite se usan los tipos de SQLAlchemy; en Fabric (SQL Server), `Unicode` = `NVARCHAR`,
`UnicodeText` = `NVARCHAR(MAX)`, `Boolean` = `BIT`, `DateTime` = `DATETIME2(0)`, `Float` = `FLOAT`.
Las fechas y horas son la **hora local** del servidor, sin zona horaria.

## Contenido
1. [`datos/manifiesto.csv`](#1-datosmanifiestocsv)
2. [`datos/duplicados.csv`](#2-datosduplicadoscsv)
3. [`datos/pares_casi_duplicados.csv`](#3-datospares_casi_duplicadoscsv)
4. [Base de datos: modelo estrella](#4-base-de-datos-modelo-estrella)
5. [Base de datos: operación](#5-base-de-datos-operación)
6. [Vistas](#6-vistas)
7. [Valores permitidos](#7-valores-permitidos)
8. [Acciones de la bitácora](#8-acciones-de-la-bitácora)
9. [Variables de `.env.example`](#9-variables-de-envexample)

---

## 1. `datos/manifiesto.csv`

Lista única de las **3,600 imágenes limpias** que usan todos los notebooks y la aplicación
(2,880 de entrenamiento y 720 de prueba). Lo genera `notebooks/01_eda.ipynb`. Una fila por imagen.

| Columna | Tipo | Significado |
|---|---|---|
| `ruta` | texto | Ruta relativa a la raíz del proyecto, p. ej. `datos/Training/glioma/Tr-gl_1.jpg`. Identifica la imagen. |
| `carpeta_origen` | texto | Carpeta original del dataset: `Training` (3,259) o `Testing` (341). No define la partición. |
| `clase` | texto | Clase original: `glioma`, `meningioma`, `notumor`, `pituitary`. |
| `es_tumor` | entero (0/1) | 1 si la clase es glioma, meningioma o pituitary; 0 si es notumor. Es la etiqueta del problema binario. |
| `sha256` | texto (64 hex) | SHA-256 de los **pixeles decodificados** de la imagen original (detecta copias exactas aunque cambie el nombre o el archivo). |
| `hash_perceptual` | texto (64 hex) | Hash perceptual de 256 bits: imagen en grises a 16 × 16, cada pixel comparado con el promedio. Resume la silueta. |
| `particion` | texto | `entrenamiento` (2,880) o `prueba` (720). La prueba es una de 5 partes de `StratifiedGroupKFold(5, shuffle=True, random_state=42)` estratificada por las 4 clases y **por grupos de similitud**. |
| `pliegue` | entero | **0 = prueba**; **1 a 5** = pliegue de la validación cruzada (576 imágenes cada uno), también por grupos. Todos los modelos usan estos mismos pliegues. |
| `grupo_similitud` | entero | Grupo de imágenes muy parecidas (componentes conexas de pares con correlación de miniaturas > 0.95 en 8 orientaciones, o con el mismo hash perceptual). Un grupo nunca queda repartido entre particiones ni entre pliegues. Hay 3,258 grupos; el más grande tiene 10 imágenes. |
| `grupo` | entero | **Mismo valor que `grupo_similitud`**; se conserva por compatibilidad con el nombre anterior de la columna. |
| `sha256_preparada` | texto (64 hex) | SHA-256 de la imagen **ya preparada** (recorte del cerebro, 160 × 160, RGB). Atrapa copias que solo difieren en el marco negro o el tamaño. Es única en el manifiesto. |
| `hash_perceptual_preparada` | texto (64 hex) | Hash perceptual de la imagen preparada. |
| `ancho` | entero | Ancho original en pixeles. |
| `alto` | entero | Alto original en pixeles. |
| `brillo` | decimal (0 a 1) | Media de los grises de la imagen preparada (0 = negro, 1 = blanco). |
| `contraste` | decimal | Desviación estándar de los grises de la imagen preparada. |

Conteo por clase y partición:

| Clase | Entrenamiento | Prueba | Total |
|---|---|---|---|
| glioma | 1,166 | 291 | 1,457 |
| meningioma | 655 | 164 | 819 |
| notumor | 294 | 73 | 367 |
| pituitary | 765 | 192 | 957 |
| **Total** | **2,880** | **720** | **3,600** |

## 2. `datos/duplicados.csv`

Las **3,600 imágenes eliminadas** de las 7,200 originales, con su causa y la imagen conservada a la
que se parecen. Lo genera `notebooks/01_eda.ipynb`. Una fila por imagen eliminada.

| Columna | Tipo | Significado |
|---|---|---|
| `ruta` | texto | Ruta de la imagen eliminada. |
| `carpeta_origen` | texto | `Training` o `Testing`. |
| `clase` | texto | Clase original de la imagen eliminada. |
| `es_tumor` | entero (0/1) | Etiqueta binaria de la imagen eliminada. |
| `sha256` | texto | SHA-256 de los pixeles decodificados. |
| `hash_perceptual` | texto | Hash perceptual de 16 × 16. |
| `accion` | texto | Siempre `quitada`. |
| `causa` | texto | Por qué se quitó (ver tabla de abajo). |
| `ruta_referencia` | texto | Imagen **conservada** con la que se comparó (vacía para `aumento_del_dataset`). |
| `clase_referencia` | texto | Clase de la imagen de referencia. Si difiere de `clase`, es una etiqueta contradictoria. |
| `variante` | texto | Orientación en la que coincidió con la referencia: `directa`, `espejo_horizontal`, `espejo_vertical`, `giro_180` (vacía para los aumentos). |
| `correlacion` | decimal | Correlación entre las miniaturas de 64 × 64 de las dos imágenes en esa orientación (todas > 0.98; vacía para los aumentos). |

Valores de `causa`:

| `causa` | Imágenes | Significado |
|---|---|---|
| `espejo_o_giro` | 2,739 | Copia volteada o girada de una imagen conservada (correlación > 0.98 solo al voltear o girar). |
| `casi_identica` | 409 | Copia recomprimida o con cambios mínimos (correlación > 0.98 sin voltear). |
| `copia_exacta` | 215 | Mismo SHA-256 (pixeles idénticos) que una imagen conservada. |
| `aumento_del_dataset` | 203 | Archivo con `aug` en el nombre: giro o zoom sintético que ya traía el dataset (solo meningioma). |
| `etiqueta_contradictoria` | 34 | Imagen de uno de 27 pares con correlación > 0.98 y **clases distintas**; se descartan las dos (glioma + meningioma: 14 pares; meningioma + pituitary: 13). |
| **Total** | **3,600** | |

## 3. `datos/pares_casi_duplicados.csv`

Archivo auxiliar del notebook 01: **24,591 pares** de imágenes con correlación de miniaturas
> 0.95 (antes de limpiar). Sirve para auditar la limpieza.

| Columna | Tipo | Significado |
|---|---|---|
| `ruta_a`, `ruta_b` | texto | Las dos imágenes del par. |
| `clase_a`, `clase_b` | texto | Sus clases. |
| `variante` | texto | Orientación con la mayor correlación (`directa`, espejos, giros). |
| `miniatura` | texto | Miniatura en la que se midió: `original` o la preparada. |
| `correlacion` | decimal | Correlación entre miniaturas de 64 × 64. |

---

## 4. Base de datos: modelo estrella

Base local: `app/almacen/tumores.db` (SQLite). Base principal: SQL database de Microsoft Fabric.
PK = llave primaria; FK = llave foránea; UQ = valor único.

### `hecho_prediccion`
Una fila por **imagen clasificada**. Filas al 21/11/2026: 3,603 (3,600 de prueba + 3 de uso).

| Columna | Tipo | Llave | Nulo | Significado |
|---|---|---|---|---|
| `prediccion_id` | Integer | PK (autonumérica) | no | Identificador de la predicción. |
| `paciente_id` | Integer | FK → `dim_paciente` | sí | Paciente ficticio. Vacío en las filas de prueba. |
| `fecha_id` | Integer (AAAAMMDD) | FK → `dim_fecha` | no | **Fecha del estudio** que captura el doctor. En prueba, fecha de la corrida que generó los resultados. |
| `usuario_id` | Integer | FK → `usuarios` | sí | Doctor que subió el estudio. Vacío en prueba. |
| `modelo_id` | Integer | FK → `dim_modelo` | no | Modelo y versión que clasificó. |
| `diagnostico_predicho_id` | Integer | FK → `dim_diagnostico` | no | Decisión binaria del modelo: solo `tumor` (2) o `sin_tumor` (1). |
| `diagnostico_confirmado_id` | Integer | FK → `dim_diagnostico` | sí | Diagnóstico confirmado: cualquiera de las 5 claves. En prueba, la clase real; en uso, la que captura el doctor (vacío si está pendiente). |
| `origen` | Unicode(10) | | no | `uso` o `prueba`. |
| `probabilidad_tumor` | Float | | no | Probabilidad de tumor que dio el modelo (0 a 1). |
| `umbral` | Float | | no | Umbral vigente al clasificar: "tumor" si `probabilidad_tumor` ≥ umbral. |
| `tipo_probable` | Unicode(20) | | sí | Tipo de tumor más probable (`glioma`, `meningioma`, `pituitary`); vacío si el modelo dijo "sin tumor". |
| `probabilidad_tipo` | Float | | sí | Probabilidad del tipo más probable. |
| `de_acuerdo` | Boolean | | sí | En **uso**: si el doctor está de acuerdo con el resultado (vacío si no ha confirmado). En **prueba**: la carga lo llena con el **acierto del modelo**; no es la opinión de un doctor. |
| `tiempo_respuesta_ms` | Float | | sí | Milisegundos de la clasificación en el servidor. Vacío en prueba. |
| `archivo_imagen` | Unicode(300) | | sí | Nombre del archivo guardado en `app/almacen/media/`. No se publica en Power BI. |
| `archivo_gradcam` | Unicode(300) | | sí | Nombre del mapa Grad-CAM ("zona que más influyó"). No se publica en Power BI. |
| `creado_en` | DateTime | | no | Cuándo se registró (cuándo se subió el estudio). |

Índices: `usuario_id`, `fecha_id`, `modelo_id`, `origen`, `creado_en`, `paciente_id`.
En Fabric hay además `CHECK (origen IN ('uso','prueba'))`.

### `dim_paciente`
Pacientes **ficticios**. Sin nombres ni datos personales.

| Columna | Tipo | Llave | Significado |
|---|---|---|---|
| `paciente_id` | Integer | PK (autonumérica) | Identificador interno. |
| `identificador` | Unicode(20) | UQ | Identificador ficticio, en mayúsculas, con el patrón `^[A-Z]{2,5}-\d{1,6}$` (p. ej. `PAC-0001`). **No se publica** en Power BI ni lo ve el asistente. |
| `edad` | Integer | | Edad, de 0 a 120. |
| `grupo_edad` | Unicode(10) | | `0-17`, `18-39`, `40-59` o `60+` (calculado por el backend). |
| `sexo` | Unicode(10) | | `F`, `M` u `Otro`. |

### `dim_fecha`
Calendario del 2025-01-01 al 2027-12-31 (1,095 días).

| Columna | Tipo | Llave | Significado |
|---|---|---|---|
| `fecha_id` | Integer | PK (no autonumérica) | Fecha como entero AAAAMMDD, p. ej. 20261121. |
| `fecha` | Date | | La fecha. |
| `anio` | Integer | | Año. |
| `mes` | Integer | | Mes, 1 a 12. |
| `nombre_mes` | Unicode(15) | | `enero` … `diciembre`. |
| `semana` | Integer | | Semana ISO. |
| `dia_semana` | Unicode(15) | | `lunes` … `domingo`. |

### `dim_diagnostico`
Datos fijos (5 filas).

| Columna | Tipo | Llave | Significado |
|---|---|---|---|
| `diagnostico_id` | Integer | PK (no autonumérica) | 1 a 5. |
| `clave` | Unicode(20) | UQ | Clave usada en la API (ver sección 7). |
| `nombre` | Unicode(60) | | Nombre para mostrar. |
| `es_tumor` | Boolean | | Verdadero si la clave es un tumor. |

| `diagnostico_id` | `clave` | `nombre` | `es_tumor` |
|---|---|---|---|
| 1 | `sin_tumor` | Sin tumor | falso |
| 2 | `tumor` | Tumor (tipo no especificado) | verdadero |
| 3 | `glioma` | Glioma | verdadero |
| 4 | `meningioma` | Meningioma | verdadero |
| 5 | `pituitary` | Tumor hipofisario | verdadero |

Tiene **dos roles** en el hecho: diagnóstico predicho y diagnóstico confirmado.

### `dim_modelo`
Un registro por modelo y versión. Al 21/11/2026: 4 clásicos (`referencia`) y la red `v001` (`produccion`).

| Columna | Tipo | Llave | Significado |
|---|---|---|---|
| `modelo_id` | Integer | PK (autonumérica) | Identificador. |
| `nombre` | Unicode(100) | | Nombre para mostrar, p. ej. "Red Keras (MobileNetV2)". |
| `tipo` | Unicode(20) | UQ (`tipo`, `version`) | `clasico` o `red_keras`. |
| `version` | Unicode(40) | UQ (`tipo`, `version`) | Clásicos: `logistica_basica`, `logistica_mobilenet`, `random_forest`, `svm_rbf`. Red: `v001`, `v002`… |
| `estado` | Unicode(20) | | `referencia`, `candidato`, `produccion` o `retirado`. |
| `umbral` | Float | | Umbral de decisión del modelo. |
| `entrenamiento_id` | Integer | (sin FK, para evitar referencia circular) | Entrenamiento que produjo la versión. |
| `sensibilidad`, `especificidad`, `f1`, `auc` | Float | | Métricas resumen (columnas adicionales al plan). |
| `origen_metricas` | Unicode(20) | | `prueba` (clásicos) o `validacion` (red; un candidato **nunca** se evalúa en prueba). |
| `aprobado_en` | DateTime | | Última vez que pasó a producción (sirve para revertir). |
| `creado_en` | DateTime | | Alta del registro. |

### `dim_usuario` (vista)
Ver [sección 6](#6-vistas). Es `usuarios` sin `hash_password` ni `creado_en`.

---

## 5. Base de datos: operación

### `usuarios`
| Columna | Tipo | Llave | Significado |
|---|---|---|---|
| `usuario_id` | Integer | PK (autonumérica) | Identificador. |
| `usuario` | Unicode(50) | UQ | Nombre de inicio de sesión. |
| `hash_password` | Unicode(100) | | Hash **bcrypt** (12 rondas). Nunca se expone en la API, en las vistas ni en Power BI. |
| `rol` | Unicode(20) | | `doctor` o `administrador`. |
| `activo` | Boolean | | Si puede iniciar sesión. |
| `creado_en` | DateTime | | Alta del usuario. |

### `sesiones`
| Columna | Tipo | Llave | Significado |
|---|---|---|---|
| `token_hash` | Unicode(64) | PK | Hash del token de la cookie `ts_sesion` (el token en claro no se guarda). |
| `usuario_id` | Integer | FK → `usuarios` | Dueño de la sesión. |
| `creada_en` | DateTime | | Inicio. |
| `expira_en` | DateTime | | Vencimiento (`SESION_MINUTOS` después). |

### `bitacora`
| Columna | Tipo | Llave | Significado |
|---|---|---|---|
| `evento_id` | Integer | PK (autonumérica) | Identificador. |
| `fecha_hora` | DateTime | índice | Momento del evento. |
| `usuario_id` | Integer | (sin FK) | Usuario, si se conoce. |
| `usuario` | Unicode(50) | | Nombre de usuario (también el que se escribió en un inicio fallido). |
| `rol` | Unicode(20) | | Rol del usuario. |
| `accion` | Unicode(40) | índice | Ver [sección 8](#8-acciones-de-la-bitácora). |
| `detalle` | Unicode(1000) | | Texto libre del evento (sin contraseñas ni la API key). |
| `ip` | Unicode(45) | | Dirección IP del cliente. No se publica en `vw_bitacora`. |
| `exito` | Boolean | | Si la acción tuvo éxito. |

### `entrenamientos`
| Columna | Tipo | Llave | Significado |
|---|---|---|---|
| `entrenamiento_id` | Integer | PK (autonumérica) | Identificador. |
| `modelo_id` | Integer | FK → `dim_modelo` | Versión que produjo. |
| `estado` | Unicode(20) | índice | `en_cola`, `corriendo`, `terminado`, `cancelado` o `error`. |
| `parametros` | UnicodeText (JSON) | | `epocas_max`, `tasa`, `lote`, `kfold`, `ajuste_fino`, `paciencia`, `origen`. |
| `etapa` | Unicode(30) | | Etapa en curso (p. ej. `pliegue_3`, `cabeza`, `ajuste_fino`, `terminado`, `cancelado`). |
| `epoca_actual`, `epocas_max` | Integer | | Avance. |
| `progreso` | Float | | 0 a 1. |
| `mensaje` | Unicode(500) | | Texto de avance para la pantalla. |
| `mejor_epoca` | Integer | | Época con menor pérdida de validación. |
| `diagnostico` | Unicode(40) | | `convergió`, `se detuvo antes de converger`, `sobreajuste`, `no aprende` o `cancelado`. |
| `explicacion` | UnicodeText | | Explicación del diagnóstico. |
| `advertencias` | UnicodeText (JSON, lista) | | Advertencias en palabras simples. |
| `metricas` | UnicodeText (JSON) | | Métricas en validación. |
| `matriz_confusion` | Unicode(200) (JSON) | | `[[vn, fp], [fn, vp]]`. |
| `curvas` | Unicode(100) | | Archivo PNG de las curvas. |
| `pid` | Integer | | Proceso del reentrenamiento (para cancelar). |
| `iniciado_en`, `terminado_en` | DateTime | | Tiempos. |
| `solicitado_por` | Integer | FK → `usuarios` | Administrador que lo pidió (vacío para la corrida del notebook). |

### `historial_epocas`
PK compuesta (`entrenamiento_id`, `etapa`, `epoca`).

| Columna | Tipo | Significado |
|---|---|---|
| `entrenamiento_id` | Integer (FK → `entrenamientos`) | Entrenamiento. |
| `etapa` | Unicode(30) | `pliegue_1` … `pliegue_5`, `cabeza` o `ajuste_fino`. |
| `epoca` | Integer | Número de época. |
| `perdida`, `exactitud` | Float | En entrenamiento. |
| `perdida_val`, `exactitud_val` | Float | En validación. |
| `tasa_aprendizaje` | Float | Tasa de aprendizaje de la época. |

### `metricas_pliegue`
| Columna | Tipo | Llave | Significado |
|---|---|---|---|
| `metrica_id` | Integer | PK (autonumérica) | Identificador (columna adicional al plan). |
| `entrenamiento_id` | Integer | FK → `entrenamientos` | Vacío para los modelos clásicos. |
| `modelo_id` | Integer | FK → `dim_modelo` | Modelo. |
| `pliegue` | Integer | | 1 a 5. |
| `sensibilidad`, `especificidad`, `precision`, `f1`, `auc` | Float | | Métricas del pliegue. (`precision` va entre corchetes en T-SQL.) |
| `vp`, `vn`, `fp`, `fn` | Integer | | Matriz de confusión del pliegue. |

---

## 6. Vistas

Mismo texto en SQLite y en SQL Server. **No incluyen hashes, IP ni identificadores de paciente.**
Las usan Power BI y el asistente de consultas (lista blanca: todas las `vw_*`, `dim_fecha`,
`dim_diagnostico` y `dim_usuario`).

| Vista | Columnas | Notas |
|---|---|---|
| `dim_usuario` | `usuario_id`, `usuario`, `rol`, `activo` | `usuarios` sin el hash. |
| `vw_predicciones` | `prediccion_id`, `origen`, `creado_en`, `fecha`, `anio`, `mes`, `nombre_mes`, `semana`, `dia_semana`, `edad`, `grupo_edad`, `sexo`, `doctor`, `modelo`, `tipo_modelo`, `modelo_version`, `estado_modelo`, `diagnostico_predicho`, `predicho_tumor`, `diagnostico_confirmado`, `confirmado_tumor`, `probabilidad_tumor`, `umbral`, `tipo_probable`, `probabilidad_tipo`, `de_acuerdo`, `tiempo_respuesta_ms`, `acierto`, `falso_negativo`, `falso_positivo` | Hecho plano. `acierto`, `falso_negativo` y `falso_positivo` son 1/0 y quedan vacíos si no hay diagnóstico confirmado. No trae llaves ni identificador del paciente. |
| `vw_bitacora` | `evento_id`, `fecha_hora`, `usuario`, `rol`, `accion`, `detalle`, `exito` | Sin `usuario_id` ni `ip`. |
| `vw_modelos` | `modelo_id`, `nombre`, `tipo`, `version`, `estado`, `umbral`, `sensibilidad`, `especificidad`, `f1`, `auc`, `origen_metricas`, `entrenamiento_id`, `aprobado_en`, `creado_en` | Igual a `dim_modelo`. |
| `vw_entrenamientos` | `entrenamiento_id`, `estado`, `epocas_max`, `epoca_actual`, `mejor_epoca`, `diagnostico`, `iniciado_en`, `terminado_en`, `version`, `solicitado_por` | `version` y `solicitado_por` (nombre de usuario) vienen de uniones. |
| `vw_metricas_pliegue` | `entrenamiento_id`, `modelo`, `modelo_version`, `pliegue`, `sensibilidad`, `especificidad`, `precision`, `f1`, `auc`, `vp`, `vn`, `fp`, `fn` | 25 filas: 5 modelos × 5 pliegues. |
| `vw_historial_epocas` | `entrenamiento_id`, `etapa`, `epoca`, `perdida`, `exactitud`, `perdida_val`, `exactitud_val`, `tasa_aprendizaje` | 28 filas (20 de `cabeza` y 8 de `ajuste_fino` de v001). |

---

## 7. Valores permitidos

| Campo | Valores |
|---|---|
| `usuarios.rol` | `doctor`, `administrador` |
| `dim_modelo.tipo` | `clasico`, `red_keras` |
| `dim_modelo.estado` | `referencia` (clásicos de comparación), `candidato` (reentrenado, sin aprobar), `produccion` (el que usa la app; uno a la vez), `retirado` |
| `dim_modelo.origen_metricas` | `prueba`, `validacion` |
| `hecho_prediccion.origen` | `uso` (estudios reales de la aplicación), `prueba` (resultados de los 5 modelos en las 720 imágenes de prueba) |
| Claves de diagnóstico | `sin_tumor`, `tumor`, `glioma`, `meningioma`, `pituitary` |
| `hecho_prediccion.diagnostico_predicho_id` | solo `tumor` o `sin_tumor` |
| `hecho_prediccion.tipo_probable` | `glioma`, `meningioma`, `pituitary` o vacío |
| `entrenamientos.estado` | `en_cola`, `corriendo`, `terminado`, `cancelado`, `error` |
| `entrenamientos.diagnostico` | `convergió`, `se detuvo antes de converger`, `sobreajuste`, `no aprende`, `cancelado` |
| `historial_epocas.etapa` | `pliegue_1` … `pliegue_5`, `cabeza`, `ajuste_fino` |
| `dim_paciente.sexo` | `F`, `M`, `Otro` |
| `dim_paciente.grupo_edad` | `0-17`, `18-39`, `40-59`, `60+` |
| `dim_paciente.edad` | 0 a 120 |
| `dim_paciente.identificador` | `^[A-Z]{2,5}-\d{1,6}$` (ficticio) |

En Fabric, `rol`, `tipo`, `estado` (modelo y entrenamiento) y `origen` tienen restricciones `CHECK`.

## 8. Acciones de la bitácora

| Acción | Cuándo se registra |
|---|---|
| `LOGIN_OK` | Inicio de sesión correcto. |
| `LOGIN_FALLIDO` | Credenciales incorrectas o rol elegido distinto al del usuario. |
| `LOGOUT` | Cierre de sesión. |
| `ACCESO_DENEGADO` | Un usuario sin permiso intenta una ruta (p. ej. un doctor en `/api/admin/*`). |
| `ESTUDIO_CREADO` | Se sube y clasifica un estudio. |
| `ESTUDIO_CONFIRMADO` | El doctor confirma o corrige el resultado. |
| `ENTRENAMIENTO_INICIADO` | El administrador inicia un reentrenamiento. |
| `ENTRENAMIENTO_TERMINADO` | El reentrenamiento termina. |
| `ENTRENAMIENTO_CANCELADO` | Se pide la cancelación y cuando el proceso se detiene (se registra dos veces). |
| `ENTRENAMIENTO_ERROR` | El reentrenamiento falla. |
| `MODELO_APROBADO` | Un candidato pasa a producción. |
| `MODELO_REVERTIDO` | Se regresa a la versión de producción anterior. |
| `UMBRAL_ACTUALIZADO` | Se cambia el umbral del modelo en producción. |
| `USUARIO_CREADO` | Alta de usuario. |
| `USUARIO_ACTUALIZADO` | Cambio de rol, contraseña o estado activo. |
| `CONSULTA_IA` | Consulta del asistente ejecutada (Fase 5). |
| `CONSULTA_IA_BLOQUEADA` | Consulta del asistente rechazada (Fase 5). |
| `CARGA_DATOS` | Carga inicial con `sql/02_cargar_datos.py`. |

Al 21/11/2026, las acciones `CONSULTA_IA` y `CONSULTA_IA_BLOQUEADA` están en el contrato
(`CLAUDE.md`) pero **todavía no aparecen en el código del backend** (el asistente es de la Fase 5,
en desarrollo).

## 9. Variables de `.env.example`

Se copia como `.env` en la raíz. `.env` **no se sube a GitHub**.

| Variable | Valor en la plantilla | Significado |
|---|---|---|
| `DB_MODO` | `local` | `local` = SQLite en `app/almacen/tumores.db`; `fabric` = SQL database de Microsoft Fabric. Cualquier otro valor se trata como `local`. |
| `FABRIC_SERVIDOR` | (vacío) | Servidor de la SQL database de Fabric (solo con `DB_MODO=fabric`). Lo da el usuario. |
| `FABRIC_BASE` | (vacío) | Nombre de la base en Fabric. |
| `FABRIC_AUTENTICACION` | `ActiveDirectoryInteractive` | Modo de Microsoft Entra ID: al conectar se abre una ventana para iniciar sesión. |
| `FABRIC_USUARIO` | (vacío) | Cuenta de Entra ID que se sugiere en la ventana de inicio de sesión (opcional). |
| `SESION_MINUTOS` | `480` | Duración de una sesión. |
| `COOKIE_SEGURA` | `false` | `true` solo si la app se sirve por HTTPS (marca la cookie como `Secure`). |
| `ANTHROPIC_API_KEY` | **debe quedar vacía** | Clave de la API de Claude para el asistente. Solo va en `.env`; nunca en el repositorio, el frontend ni los registros. |
| `ANTHROPIC_MODELO` | `claude-sonnet-5-5` | Modelo de Claude que usa el asistente. |
| `ASISTENTE_LIMITE_FILAS` | `200` | Máximo de filas que devuelve una consulta del asistente. |
| `POWERBI_URL` | (vacío) | Liga del tablero publicado (debe empezar con `https://`). Ver `tablero/GUIA_POWER_BI.md`. |

Variables solo para pruebas (no están en `.env.example`): `TS_DB_RUTA`, `TS_MEDIA_DIR`,
`TS_MODELOS_DIR`, `TS_REGISTROS_DIR`.
