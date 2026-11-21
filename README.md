# Sistema de apoyo para detección de tumores cerebrales en resonancia magnética

Proyecto final del Diplomado en IA Generativa, BI y Ciencia de Datos (Universidad Anáhuac Querétaro). Es un tablero web de hospital: el doctor sube una imagen de
resonancia magnética y el sistema indica si **se detecta o no un posible tumor**, con su nivel de
confianza y un mapa de la **zona que más influyó** en la respuesta (Grad-CAM). Cada estudio se
registra en SQL Server (Microsoft Fabric), con respaldo local en SQLite, y se analiza en Power BI.

> **Resultado de apoyo. No sustituye el diagnóstico de un médico especialista.**
>
> Es un proyecto académico de apoyo a la decisión. **No es un dispositivo médico** y no se ha
> validado con pacientes reales.

> Versión del 21 de noviembre de 2026. Las cifras salen de los archivos de `resultados/` y de
> `app/modelos/v001/info.json`.

## Contenido
- [Problema](#problema)
- [Integrantes](#integrantes)
- [Fuente de datos](#fuente-de-datos)
- [Requisitos](#requisitos)
- [Cómo correr el proyecto desde cero](#cómo-correr-el-proyecto-desde-cero)
- [Usuarios de demostración](#usuarios-de-demostración)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Cómo pasar a Microsoft Fabric](#cómo-pasar-a-microsoft-fabric)
- [Resultados](#resultados)
- [Limpieza de datos](#limpieza-de-datos)
- [Convergencia de la red](#convergencia-de-la-red)
- [Limitaciones](#limitaciones)
- [Seguridad](#seguridad)
- [Uso de IA generativa](#uso-de-ia-generativa)
- [Correspondencia con la rúbrica](#correspondencia-con-la-rúbrica)
- [Licencia y créditos](#licencia-y-créditos)

## Problema

Clasificación binaria de imágenes de resonancia magnética de cerebro: **tumor** (glioma,
meningioma o tumor hipofisario) contra **sin tumor**. Como dato secundario, el sistema indica el
tipo de tumor más probable.

El error más costoso es el **falso negativo** (un tumor que se pasa por alto). Por eso la métrica
principal es la **sensibilidad**, con un objetivo de **0.98**, y el umbral de decisión se elige
para priorizarla. También se reportan especificidad, precisión, F1 y AUC.

## Integrantes

| Nombre | Institución |
|---|---|
| Raúl Pichardo Manzano | Universidad Anáhuac Querétaro |

## Fuente de datos

"Brain Tumor MRI Dataset", de Masoud Nickparvar, en Kaggle:
https://www.kaggle.com/datasets/masoudnickparvar/brain-tumor-mri-dataset. Licencia
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

La ficha completa está en [`datos/FUENTE.md`](datos/FUENTE.md): atribución, cambios hechos a los
datos, estructura de carpetas, conteo por clase, cómo descargarlo y por qué la copia local tiene
7,200 imágenes y no 7,023. El significado de cada columna de los archivos y de la base está en
[`datos/diccionario_datos.md`](datos/diccionario_datos.md).

Las imágenes **no se redistribuyen**: no se suben a GitHub.

## Requisitos

- **Windows** 10 u 11 (se desarrolló en Windows 11).
- **Python 3.12** (se usó 3.12.10).
- **ODBC Driver 18 for SQL Server**, solo para conectarse a Fabric (`DB_MODO=fabric`).
- **No se necesita GPU:** todo entrena en CPU.
- Para Power BI: Power BI Desktop (no está en el equipo de desarrollo; ver
  [`tablero/GUIA_POWER_BI.md`](tablero/GUIA_POWER_BI.md)).

## Cómo correr el proyecto desde cero

Todos los comandos se escriben en PowerShell, desde la raíz del proyecto.

1. **Crear el entorno virtual e instalar las dependencias:**
   ```powershell
   py -3.12 -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
2. **Registrar el kernel de Jupyter `tumores`** (lo usan los notebooks):
   ```powershell
   .venv\Scripts\python.exe -m ipykernel install --user --name tumores --display-name "Python (tumores)"
   ```
3. **Colocar el dataset** en `datos\Training` y `datos\Testing`, cada una con las carpetas
   `glioma`, `meningioma`, `notumor` y `pituitary` (ver [`datos/FUENTE.md`](datos/FUENTE.md)).
4. **Ejecutar el análisis.** Hay dos formas equivalentes (ejecutan el mismo código y dan los mismos
   resultados); generan `datos/manifiesto.csv`, `resultados/` y el modelo `app/modelos/v001/`. Tarda
   de 10 a 20 minutos en CPU.
   - **Todo en uno (recomendado para revisar):** abrir
     [`notebooks/00_proyecto_completo.ipynb`](notebooks/00_proyecto_completo.ipynb) con el kernel
     *Python (tumores)* y ejecutar *Run All*. Está ordenado como el flujo de trabajo: datos →
     limpieza → exploración → preparación del dataset (entrenamiento / prueba, CV = 5) → creación de
     rasgos → modelos clásicos → red de Keras → IA generativa → conclusiones.
     ```powershell
     .venv\Scripts\python.exe -m jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=3600 notebooks\00_proyecto_completo.ipynb
     ```
   - **Por etapas:** los mismos pasos separados en los notebooks 01 a 04.
     ```powershell
     .venv\Scripts\python.exe scripts\correr_notebooks.py
     ```
     Para correr solo algunos: `.venv\Scripts\python.exe scripts\correr_notebooks.py 03_modelos_ml 04_red_keras`.
5. **Crear el archivo `.env`** a partir de la plantilla (y revisar sus valores; ver
   [`datos/diccionario_datos.md`](datos/diccionario_datos.md#9-variables-de-envexample)):
   ```powershell
   Copy-Item .env.example .env
   ```
6. **Crear el esquema y cargar la base** (dimensiones, modelos, resultados de prueba y la corrida
   original de v001). Usa el `DB_MODO` del `.env` y se puede correr varias veces sin duplicar:
   ```powershell
   .venv\Scripts\python.exe sql\02_cargar_datos.py
   ```
7. **Crear los usuarios de demostración:**
   ```powershell
   .venv\Scripts\python.exe scripts\crear_usuarios_demo.py
   ```
8. **Arrancar el servidor:**
   ```powershell
   .venv\Scripts\python.exe -m uvicorn app.backend.main:app --port 8000
   ```
9. **Abrir** http://localhost:8000 en el navegador.
10. **Opcional: notebook de IA generativa y pruebas automáticas.** El notebook 05 hace llamadas
    reales solo si hay `ANTHROPIC_API_KEY` en `.env`; sin clave corre igual y lo indica.
    ```powershell
    .venv\Scripts\python.exe -m jupyter nbconvert --to notebook --execute --inplace notebooks\05_ia_generativa.ipynb
    .venv\Scripts\python.exe -m pytest pruebas -q --ignore=pruebas/verificacion_fase12 --ignore=pruebas/verificacion_fase34
    ```

> Si ya existe en el equipo un kernel de Jupyter llamado `tumores`, el paso 2 lo reemplaza por el
> del nuevo entorno.

## Usuarios de demostración

Los crea `scripts/crear_usuarios_demo.py`. **Son solo para la demostración:** cámbielos o
desactívelos antes de usar el sistema con cualquier otro fin.

| Usuario | Contraseña | Rol |
|---|---|---|
| `doctor1` | `Doctor2026!` | Doctor |
| `doctor2` | `Doctor2026!` | Doctor |
| `admin1` | `Admin2026!` | Administrador |

## Estructura del repositorio

```
.
├── README.md                 este archivo
├── CLAUDE.md                 reglas, modelo de datos y contrato de la API
├── requirements.txt          dependencias con versión fija
├── .env.example              plantilla de configuración (el .env real no se sube)
├── datos/
│   ├── FUENTE.md             ficha del dataset
│   ├── diccionario_datos.md  columnas de archivos, tablas, vistas y variables
│   ├── manifiesto.csv        3,600 imágenes limpias con partición y pliegue
│   ├── duplicados.csv        3,600 imágenes eliminadas y su causa
│   ├── pares_casi_duplicados.csv
│   ├── Training/, Testing/   dataset (no se sube)
│   └── rasgos/               rasgos de MobileNetV2 (no se sube)
├── notebooks/
│   ├── 00_proyecto_completo.ipynb  TODO EN UNO: limpieza → exploración → preparación → rasgos → modelos → red → IA generativa
│   ├── 01_eda.ipynb          exploración, limpieza, estadística y división
│   ├── 02_rasgos.ipynb       rasgos de MobileNetV2, PCA y K-Means
│   ├── 03_modelos_ml.ipynb   modelos clásicos con validación cruzada
│   ├── 04_red_keras.ipynb    red de Keras, convergencia, comparación, Grad-CAM y exportación
│   └── 05_ia_generativa.ipynb asistente de consultas SQL con Claude: prompts y validador
├── resultados/               tablas, figuras y predicciones que generan los notebooks
├── sql/
│   ├── 01_crear_tablas.sql   esquema T-SQL para Fabric (modelo estrella y vistas)
│   ├── 02_cargar_datos.py    carga inicial (local o Fabric)
│   ├── 03_consultas.sql      11 consultas comentadas con filtros, uniones y agregados
│   └── README.md             inicio de sesión en Fabric y diferencias SQLite / T-SQL
├── tablero/
│   ├── GUIA_POWER_BI.md      conexión, relaciones, medidas DAX y páginas
│   ├── comprobar_medidas.py  valores esperados de las medidas, con SQL y pandas
│   ├── exportar_csv.py       exporta el modelo estrella a CSV (plan B)
│   └── csv/                  exportación generada
├── app/
│   ├── backend/              FastAPI; ml/ es el único lugar con preprocesamiento y modelo
│   ├── frontend/             HTML, CSS y JavaScript sin frameworks ni CDN
│   ├── modelos/              vNNN/modelo.keras + info.json (no se sube)
│   └── almacen/              imágenes subidas y SQLite local (no se sube)
├── scripts/                  correr_notebooks.py, crear_usuarios_demo.py, probar_fabric.py
├── pruebas/                  pruebas automáticas y evidencias de verificación
├── anexos/                   PROMPTS.md: prompts del asistente, parámetros y ejemplos
└── referencia/               material anterior, intacto
```

## Cómo pasar a Microsoft Fabric

> **Probado contra Fabric el 21 de noviembre de 2026:** `scripts/probar_fabric.py` creó el esquema,
> cargó las 3,600 predicciones de prueba, los 5 modelos y los usuarios, y las consultas de
> `sql/03_consultas.sql` dieron en Fabric los mismos números que `resultados/prueba_resumen.csv`.
> El inicio de sesión se hace con **Microsoft Entra ID en una pestaña del navegador**
> (`azure-identity`); la sesión queda guardada en caché para el servidor, el reentrenamiento y la carga.

1. Instale el **ODBC Driver 18 for SQL Server**.
2. En Fabric, dentro de un área de trabajo con capacidad de Fabric (o de prueba), cree una
   **SQL database** (no un Warehouse ni un Lakehouse).
3. En la base, abra **Configuración → Cadenas de conexión → ODBC** y copie a `.env` el servidor (lo
   que va después de `Server=tcp:` y antes de la coma) y el nombre de la base (lo que va después de
   `Database=`):
   ```
   DB_MODO=fabric
   FABRIC_SERVIDOR=<servidor>.database.fabric.microsoft.com
   FABRIC_BASE=<nombre de la base con su código>
   FABRIC_USUARIO=<cuenta de Microsoft Entra ID, opcional: solo rellena el inicio de sesión>
   ```
   No hay contraseñas de base de datos en `.env`.
4. Cree el esquema, cargue los datos y los usuarios, y compruebe con consultas (se abrirá el
   navegador para iniciar sesión la primera vez):
   ```powershell
   .venv\Scripts\python.exe scripts\probar_fabric.py
   ```
   El esquema lo crea `sql/01_crear_tablas.sql` (re-ejecutable). Para cargar sin las
   comprobaciones, use `sql\02_cargar_datos.py` y `scripts\crear_usuarios_demo.py` con
   `DB_MODO=fabric`.
5. Arranque el servidor como en el paso 8. `GET /api/estado` debe responder `"base_datos": "fabric"`.
   Si falla internet o el inicio de sesión, cambie a `DB_MODO=local` y la aplicación sigue igual
   con SQLite.

## Resultados

Tabla tomada de `resultados/tabla_comparativa.md` (generada por `notebooks/04_red_keras.ipynb`).

| Modelo | CV Sensibilidad | CV Especificidad | CV Precisión | CV F1 | CV AUC | Umbral | Prueba Sensibilidad (IC 95 %) | Prueba Especificidad (IC 95 %) | Prueba Precisión | Prueba F1 | Prueba AUC | FN | FP |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Logística (rasgos básicos) | 0.9803 ± 0.0034 | 0.2689 ± 0.0651 | 0.9219 ± 0.0067 | 0.9502 ± 0.0038 | 0.9040 ± 0.0462 | 0.0225 | 0.9768 (0.962 a 0.986) | 0.3014 (0.208 a 0.414) | 0.9253 | 0.9504 | 0.9389 | 15 | 51 |
| Logística (MobileNetV2) | 0.9803 ± 0.0079 | 0.8843 ± 0.0187 | 0.9868 ± 0.0021 | 0.9835 ± 0.0038 | 0.9868 ± 0.0115 | 0.6276 | 0.9784 (0.964 a 0.987) | 0.8630 (0.766 a 0.924) | 0.9844 | 0.9814 | 0.9813 | 14 | 10 |
| Random Forest (MobileNetV2) | 0.9803 ± 0.0060 | 0.7822 ± 0.0359 | 0.9754 ± 0.0037 | 0.9778 ± 0.0016 | 0.9855 ± 0.0057 | 0.6367 | 0.9830 (0.970 a 0.990) | 0.7945 (0.688 a 0.871) | 0.9770 | 0.9800 | 0.9870 | 11 | 15 |
| SVM RBF (MobileNetV2) | 0.9803 ± 0.0088 | 0.9150 ± 0.0205 | 0.9902 ± 0.0024 | 0.9852 ± 0.0047 | 0.9913 ± 0.0033 | 0.7493 | 0.9784 (0.964 a 0.987) | 0.8630 (0.766 a 0.924) | 0.9844 | 0.9814 | 0.9782 | 14 | 10 |
| Red Keras (MobileNetV2) | 0.9803 ± 0.0075 | 0.9048 ± 0.0307 | 0.9891 ± 0.0035 | 0.9846 ± 0.0038 | 0.9856 ± 0.0074 | 0.5205 | 0.9675 (0.951 a 0.979) | 0.8904 (0.798 a 0.943) | 0.9874 | 0.9774 | 0.9825 | 21 | 8 |

- **CV:** validación cruzada de 5 pliegues estratificados por grupos de similitud sobre las 2,880
  imágenes de entrenamiento (media ± desviación estándar). El umbral de cada modelo se elige con las
  predicciones fuera de pliegue para sensibilidad ≥ 0.98, así que la sensibilidad de CV queda cerca
  de 0.98 **por construcción**.
- **Prueba:** 720 imágenes, una sola evaluación por modelo. Intervalos de Wilson al 95 %.
  FN = falsos negativos; FP = falsos positivos.
- **Red Keras:** la validación cruzada es de la cabeza con los rasgos de MobileNetV2 congelados. El
  ajuste fino se entrenó una sola vez y **no mejoró** la pérdida de validación (0.3956 contra
  0.3411), así que el modelo exportado (`v001`) es la cabeza sola.

**Lectura honesta:**
- La red de Keras, que es el modelo que usa la aplicación, **no alcanza la sensibilidad objetivo de
  0.98 en prueba: logra 0.9675** (21 tumores no detectados de 647).
- **Solo Random Forest alcanza el objetivo en prueba** (0.9830, 11 falsos negativos).
- Frente al SVM (el mejor clásico según la validación cruzada), **no hay diferencia significativa
  en McNemar global** (p = 0.227; la red acierta y el SVM falla en 3 imágenes, y al revés en 8).
  Pero **en los tumores**, la red falla 7 que el SVM detecta y el SVM no falla ninguno que la red
  detecte (p exacta = 0.016). Es decir, en la decisión que más importa, el SVM fue mejor en esta
  prueba. Lo mismo ocurre, solo en tumores, contra Random Forest (1 contra 11, p = 0.006) y contra la
  logística con rasgos de MobileNetV2 (1 contra 8, p = 0.039); contra la logística con rasgos básicos
  no hay diferencia (8 contra 14, p = 0.286). Son pruebas sin corregir por comparaciones múltiples.
  (Todas las cifras, globales y solo en tumores, están en `resultados/mcnemar.csv`.)
- **Por qué la app usa de todos modos la red:** el encargo pide que la red de Keras sea el modelo
  en uso (Módulo 4) y que el resultado incluya el mapa Grad-CAM, que solo existe para la red. El
  administrador puede bajar el umbral desde su panel para ganar sensibilidad a costa de más falsos
  positivos, y la vista previa muestra el efecto antes de guardarlo.
- La red tiene la mayor especificidad en prueba (0.8904), pero la especificidad se mide con
  **solo 73 imágenes "sin tumor"**: cada falso positivo la mueve 1.4 puntos porcentuales y los
  intervalos de los modelos se traslapan. No se puede afirmar qué modelo tiene mejor especificidad.
- La solución más simple (solo brillo, contraste e histograma) llega a AUC 0.939 en prueba: esa es
  la parte del problema que se resuelve sin mirar la anatomía.

## Limpieza de datos

La carpeta local tiene **7,200 imágenes** (1,800 por clase). Después de la limpieza quedan
**3,600**: el dataset traía muchas repeticiones.

| Causa | Imágenes quitadas |
|---|---|
| Copias en espejo o giradas (`espejo_o_giro`) | 2,739 |
| Copias recomprimidas o casi idénticas (`casi_identica`) | 409 |
| Copias exactas (mismo SHA-256 de pixeles) | 215 |
| Aumentos sintéticos que ya traía el dataset (archivos `aug`) | 203 |
| Etiquetas contradictorias (27 pares; se quitan las dos imágenes) | 34 |
| **Total** | **3,600** |

- Se juntaron las 8 carpetas (Training y Testing) antes de limpiar: 1,078 copias eliminadas tenían
  su pareja conservada en la **otra** carpeta, así que la división original del dataset tenía fuga.
- Dos imágenes se consideran la misma toma si la correlación de sus miniaturas de 64 × 64 es mayor
  de 0.98 en alguna de 8 orientaciones.
- Las imágenes que quedan y se parecen mucho (correlación > 0.95 o mismo hash perceptual) forman
  **grupos de similitud**. La división en entrenamiento (2,880) y prueba (720) y los 5 pliegues se
  hicieron **por grupos**: ningún grupo queda repartido.
- Queda un desbalance fuerte: 367 imágenes sin tumor (10.2 %) contra 3,233 con tumor. Se trata con
  pesos de clase.

## Convergencia de la red

- `EarlyStopping(monitor="val_loss", restore_best_weights=True)`, `ReduceLROnPlateau` y
  `ModelCheckpoint`.
- **Mejor época: 12** (pérdida de validación 0.3411). La detención temprana actuó en la época 20
  de 60 tras 8 épocas sin mejorar.
- **Diagnóstico automático: "convergió".**
- Es **un mínimo de la pérdida de validación** observado en esta corrida, **no una garantía de
  mínimo global**: con otra semilla, tasa o división el resultado puede cambiar un poco.
- El ajuste fino (8 épocas, tasa 1e-5) también se diagnosticó como "convergió", pero no mejoró al
  modelo de partida; se conservó la cabeza sola.

## Limitaciones

- **Sin identificador de paciente puede quedar fuga por estudio.** El dataset no dice qué cortes
  son del mismo paciente. En la prueba, **318 de 720 imágenes (44.17 %)** tienen en entrenamiento
  una imagen con correlación entre 0.90 y 0.95, sobre todo cortes vecinos del mismo estudio
  (`resultados/eda_fuga_gemelas.csv`). Ninguna supera 0.95. Las métricas de prueba pueden estar algo
  optimistas para pacientes nuevos.
- **El brillo por sí solo separa buena parte de las clases.** Las imágenes sin tumor son más
  brillantes (brillo medio 0.338 contra 0.242; Mann-Whitney p = 2.4e-108). Eso refleja cómo se
  obtuvieron las imágenes, no la enfermedad, y un modelo podría apoyarse en ello. El modelo de solo
  brillo, contraste e histograma llega a AUC 0.939 en prueba.
- **No es un dispositivo médico.** No se ha validado con imágenes de otro hospital ni con
  pacientes reales. Los resultados describen este dataset.
- **Grad-CAM muestra la "zona que más influyó"** en la respuesta, **no la ubicación del tumor** ni
  una segmentación.
- La especificidad se mide con solo 73 imágenes sin tumor en prueba.
- La validación cruzada de la red es de la cabeza con rasgos congelados; el ajuste fino se entrenó
  una sola vez.
- La aplicación completa en modo Fabric (subir estudios, reentrenar) se probó en SQLite; contra
  Fabric se probaron la creación del esquema, la carga, las consultas y el asistente de solo
  lectura. En Fabric el asistente usa la misma identidad que la aplicación; en producción debería
  usar un usuario con solo `db_datareader`.

## Seguridad

- **Contraseñas con bcrypt** (12 rondas); nunca se guardan ni se devuelven en claro.
- **Sesión en cookie httpOnly** `ts_sesion` (SameSite=Lax; `Secure` si `COOKIE_SEGURA=true`). En la
  base solo se guarda el hash del token.
- **Permisos validados en el backend:** un doctor recibe 403 en las rutas de administrador y el
  intento queda en la bitácora como `ACCESO_DENEGADO`. Un doctor solo ve y confirma sus estudios.
- **Consultas SQL parametrizadas** (SQLAlchemy Core).
- **Asistente de consultas de solo lectura:** solo `SELECT`, sobre una lista blanca de vistas sin
  hashes ni identificadores de paciente, con límite de filas; lo demás se rechaza y se registra.
- **La API key de Claude solo vive en `.env`**; no llega al frontend, al repositorio ni a los
  registros.
- El frontend inserta los datos con `textContent` y no usa CDN.
- Cada inicio de sesión, cierre y acción importante queda en la bitácora.

## Uso de IA generativa

- El asistente de consultas SQL con la API de Claude y sus prompts se documentan en
  [`notebooks/05_ia_generativa.ipynb`](notebooks/05_ia_generativa.ipynb) y
  [`anexos/PROMPTS.md`](anexos/PROMPTS.md). Se probó contra la API real: respondió con una consulta
  de lectura a "¿cuántos estudios con posible tumor hubo hoy por doctor?" y bloqueó un `DROP`, un
  `UPDATE`, la lectura de hashes de contraseña y la de identificadores de pacientes.
- No se envían a la API datos que identifiquen a pacientes.

## Correspondencia con la rúbrica


| Módulo | Requisito | Archivo |
|---|---|---|
| 1 | Exploración, limpieza, estadística descriptiva, intervalos de confianza y pruebas de hipótesis | `notebooks/01_eda.ipynb`, `datos/manifiesto.csv`, `datos/duplicados.csv`, `resultados/eda_*.csv` |
| 1 | Fuente y diccionario de datos | `datos/FUENTE.md`, `datos/diccionario_datos.md` |
| 3 | Rasgos de MobileNetV2, PCA y K-Means | `notebooks/02_rasgos.ipynb`, `resultados/pca_varianza.csv`, `resultados/kmeans_*.csv` |
| 3 | Modelos clásicos con validación cruzada K-fold y métricas | `notebooks/03_modelos_ml.ipynb`, `resultados/cv_resumen.csv`, `resultados/cv_pliegues.csv` |
| 4 | Red neuronal en Keras, convergencia, comparación y McNemar | `notebooks/04_red_keras.ipynb`, `resultados/tabla_comparativa.md`, `resultados/mcnemar.csv`, `app/modelos/v001/info.json` |
| 4 | IA generativa: asistente de consultas SQL y prompts | `notebooks/05_ia_generativa.ipynb`, `anexos/PROMPTS.md`, `app/backend/asistente.py` |
| 2 | Datos en SQL Server (Fabric), modelo estrella y consultas con filtros, uniones y agregados | `sql/01_crear_tablas.sql`, `sql/02_cargar_datos.py`, `sql/03_consultas.sql` |
| 2 | Power BI: relaciones y medidas DAX | `tablero/GUIA_POWER_BI.md`, `tablero/comprobar_medidas.py` |
| Comparación | Resultados contra la solución más simple | `resultados/tabla_comparativa.md` (logística con rasgos básicos) |
| Proyecto | Aplicación web con roles, bitácora y reentrenamiento | `app/backend/`, `app/frontend/`, `pruebas/` |

## Licencia y créditos

### Atribución y cambios (dataset, CC BY 4.0)

- **Autor:** Masoud Nickparvar.
- **Título:** "Brain Tumor MRI Dataset".
- **Fuente:** Kaggle, https://www.kaggle.com/datasets/masoudnickparvar/brain-tumor-mri-dataset
- **Licencia:** Creative Commons Attribution 4.0 International (CC BY 4.0),
  https://creativecommons.org/licenses/by/4.0/
- **Cambios que hizo este proyecto:**
  1. Se quitaron copias exactas, espejos, giros, recompresiones y aumentos (`aug`). De 7,200
     imágenes quedaron 3,600.
  2. Se descartaron las imágenes con etiquetas contradictorias (34 imágenes de 27 pares).
  3. Se hizo una nueva división 80/20 por grupos de similitud (2,880 de entrenamiento y 720 de prueba).
  4. Se recortó el contorno del cerebro y se redimensionó cada imagen a 160 × 160.
  5. Las clases se agruparon en tumor (glioma, meningioma y pituitary) contra sin tumor (notumor).
- Las imágenes **no se redistribuyen** en este repositorio. Detalle en [`datos/FUENTE.md`](datos/FUENTE.md).

### Créditos

- **Dataset:** ver la atribución de arriba. Según fuentes secundarias, reúne imágenes de
  figshare, SARTAJ y Br35H.
- **MobileNetV2** preentrenada con ImageNet, a través de Keras/TensorFlow.
- Bibliotecas principales: TensorFlow/Keras, scikit-learn, OpenCV, pandas, FastAPI, SQLAlchemy y
  bcrypt (versiones en `requirements.txt`).
- **Código del proyecto:** <!-- PENDIENTE: elegir licencia del código (p. ej. MIT) con el equipo --> por definir.
- Proyecto final del Diplomado en IA Generativa, BI y Ciencia de Datos, Universidad Anáhuac Querétaro. Autor: Raúl Pichardo Manzano.
