# Fuente de datos

## Dataset

| Campo | Valor |
|---|---|
| Título | **Brain Tumor MRI Dataset** |
| Autor | Masoud Nickparvar |
| Fuente | Kaggle: https://www.kaggle.com/datasets/masoudnickparvar/brain-tumor-mri-dataset |
| Identificador para descargar | `masoudnickparvar/brain-tumor-mri-dataset` |
| Licencia | **Creative Commons Attribution 4.0 International (CC BY 4.0)**: https://creativecommons.org/licenses/by/4.0/ |
| Última actualización | La página de Kaggle muestra "Updated 9 months ago" (captura del usuario del 21 de noviembre de 2026). |
| Clases | `glioma`, `meningioma`, `notumor`, `pituitary` (4 clases) |
| Uso en este proyecto | Clasificación binaria: **tumor** (glioma + meningioma + pituitary) contra **sin tumor** (notumor). El tipo de tumor es un dato secundario. |
| Formato | Imágenes JPG de cortes de resonancia magnética, divididas en `Training/` y `Testing/` |

Es la misma fuente que cita el script anterior `referencia/tumores_cerebrales.py`. La licencia es
la que muestra la ficha de Kaggle, según confirmó el usuario.

Según fuentes secundarias (IEEE DataPort y otros trabajos que lo usan), el dataset es una
**recopilación** de tres conjuntos públicos: figshare, SARTAJ y Br35H.

## Atribución y cambios

Esta sección cumple con lo que pide la licencia CC BY 4.0: dar crédito, enlazar la licencia e
indicar si se hicieron cambios.

- **Autor:** Masoud Nickparvar.
- **Título:** "Brain Tumor MRI Dataset".
- **Fuente:** Kaggle, https://www.kaggle.com/datasets/masoudnickparvar/brain-tumor-mri-dataset
- **Licencia:** Creative Commons Attribution 4.0 International (CC BY 4.0),
  https://creativecommons.org/licenses/by/4.0/
- **Cambios que hizo este proyecto** (en `notebooks/01_eda.ipynb` y `app/backend/ml/preprocesar.py`):
  1. Se quitaron copias exactas, copias en espejo y giradas, copias recomprimidas o casi idénticas
     y los aumentos sintéticos que traía el dataset (archivos con `aug` en el nombre). De
     **7,200** imágenes quedaron **3,600**.
  2. Se descartaron las imágenes con etiquetas contradictorias: 27 pares, es decir 34 imágenes,
     en los que la misma toma aparecía con dos clases distintas.
  3. Se hizo una **nueva división 80/20** (2,880 de entrenamiento y 720 de prueba) **por grupos
     de similitud**, estratificada por clase y con semilla 42. La división original
     `Training/`/`Testing/` no se usa para evaluar.
  4. Para el modelo, cada imagen se **recorta al contorno del cerebro** y se **redimensiona a
     160 × 160** pixeles (RGB). Los archivos originales no se modifican.
  5. Las cuatro clases se **agruparon en dos**: tumor (glioma, meningioma y pituitary) contra sin
     tumor (notumor).
- **Las imágenes no se redistribuyen:** el repositorio no incluye las imágenes originales ni las
  procesadas (`.gitignore` excluye `datos/Training/`, `datos/Testing/` y `datos/rasgos/`). Solo
  incluye listas derivadas con rutas, huellas y particiones (`manifiesto.csv`, `duplicados.csv` y
  `pares_casi_duplicados.csv`).

## 7,200 imágenes locales contra 7,023 en la ficha

`referencia/tumores_cerebrales.py` y las descripciones del dataset que citan otras fuentes (por
ejemplo, IEEE DataPort) hablan de **7,023 imágenes**, pero la
carpeta local tiene **7,200**. El conteo se hizo en `datos/` el 21 de noviembre de 2026 y lo
confirma el notebook `01_eda.ipynb` ("Imágenes encontradas: 7,200"):

| Carpeta | glioma | meningioma | notumor | pituitary | Total |
|---|---|---|---|---|---|
| `Training/` | 1,400 | 1,400 | 1,400 | 1,400 | 5,600 |
| `Testing/` | 400 | 400 | 400 | 400 | 1,600 |
| **Total** | **1,800** | **1,800** | **1,800** | **1,800** | **7,200** |

**Explicación probable (no confirmada):** el dataset se actualizó en Kaggle. La página muestra
"Updated 9 months ago" y la versión descargada trae 1,400 imágenes por clase en `Training/` y 400
por clase en `Testing/`; la cifra de 7,023 correspondería a una versión anterior. No se pudo leer
el texto de la ficha de Kaggle para citar el total que reporta hoy.

La copia local incluye **203 archivos** de meningioma con `aug` en el nombre (100 en `Training/` y
103 en `Testing/`). Son aumentos sintéticos, y el proyecto los quita (ver "Atribución y cambios").

## Estructura de carpetas esperada

```
datos/
├── Training/
│   ├── glioma/        Tr-gl_*.jpg
│   ├── meningioma/    Tr-me_*.jpg   (incluye archivos con "aug")
│   ├── notumor/       Tr-no_*.jpg
│   └── pituitary/     Tr-pi_*.jpg
├── Testing/
│   ├── glioma/        Te-gl_*.jpg
│   ├── meningioma/    Te-me_*.jpg   (incluye archivos con "aug")
│   ├── notumor/       Te-no_*.jpg
│   └── pituitary/     Te-pi_*.jpg
├── manifiesto.csv            (lo genera notebooks/01_eda.ipynb)
├── duplicados.csv            (lo genera notebooks/01_eda.ipynb)
├── pares_casi_duplicados.csv (lo genera notebooks/01_eda.ipynb)
└── rasgos/                   (lo genera notebooks/02_rasgos.ipynb; no se sube a GitHub)
```

`datos/Training` y `datos/Testing` son de **solo lectura** para el proyecto: ningún código los
modifica. El significado de cada columna de los CSV está en `datos/diccionario_datos.md`.

## Cómo descargar las imágenes

Las imágenes no se suben a GitHub. Cada integrante debe descargar el dataset por su cuenta.

**Opción 1: desde el navegador.** Inicie sesión en Kaggle, abra
https://www.kaggle.com/datasets/masoudnickparvar/brain-tumor-mri-dataset, pulse **Download**,
descomprima el archivo y copie las carpetas `Training` y `Testing` dentro de `datos/`.

**Opción 2: con la herramienta de Kaggle.** Requiere una cuenta y el archivo de credenciales
`kaggle.json` en `%USERPROFILE%\.kaggle\`:

```powershell
.venv\Scripts\python.exe -m pip install kaggle
.venv\Scripts\kaggle.exe datasets download -d masoudnickparvar/brain-tumor-mri-dataset -p datos --unzip
```

El paquete `kaggle` no está en `requirements.txt`; solo hay que instalarlo si se usa esta opción.
Después de descargar, revise que queden exactamente `datos/Training/<clase>/` y
`datos/Testing/<clase>/`, sin una carpeta intermedia, y compare el conteo con la tabla de arriba.
Si Kaggle publica otra versión del dataset, los resultados de `resultados/` no se reproducirán igual.

## Fuentes consultadas

- Kaggle, página del dataset: https://www.kaggle.com/datasets/masoudnickparvar/brain-tumor-mri-dataset
  (la licencia y la fecha de actualización salen de la captura del usuario; desde el equipo de
  desarrollo no se pudo leer el contenido de la página).
- IEEE DataPort, "Brain Tumor MRI Dataset": https://ieee-dataport.org/documents/brain-tumor-mri-dataset
  (según el resumen de búsqueda, describe la composición figshare + SARTAJ + Br35H y 7,023 imágenes).
