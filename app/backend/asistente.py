"""Asistente de consultas SQL con la API de Claude (IA generativa, Fase 5).

Flujo de cada pregunta del Administrador:
  (a) Claude recibe la pregunta y el esquema de la LISTA BLANCA (solo vistas de lectura, sin
      hashes ni identificadores de pacientes) y devuelve, con salida estructurada,
      {puede_responder, sql, explicacion, motivo}.
  (b) La consulta se valida con sqlglot SIN excepciones: una sola sentencia SELECT (o WITH ...
      SELECT), sin DML/DDL en ningún nodo, solo tablas de la lista blanca (también en subconsultas
      y CTE), sin funciones peligrosas, sin comentarios, y con límite de filas forzado.
  (c) Se ejecuta en una conexión de SOLO LECTURA (SQLite: mode=ro + query_only) con tiempo máximo.
  (d) Claude recibe la pregunta, la consulta y como máximo 50 filas (sin columnas que identifiquen
      a pacientes) y redacta la respuesta en lenguaje sencillo.

Si la "pregunta" ya es una consulta SQL escrita por el administrador, pasa por el mismo
validador (no se manda a Claude para generarla). Todo se registra en la bitácora:
CONSULTA_IA (pregunta y consulta, sin datos de pacientes) o CONSULTA_IA_BLOQUEADA (con el motivo).

La clave ANTHROPIC_API_KEY solo se usa para crear el cliente; nunca se escribe en registros,
respuestas, errores ni en la base.
"""
import json
import logging
import re
import sqlite3
import time
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import quote

import sqlglot
from sqlglot import exp

from . import config, db
from .tablas import LISTA_BLANCA_ASISTENTE

log = logging.getLogger("tumores.asistente")

MAX_TOKENS = 4000
ESFUERZO = "medium"
BETA_RESPALDO = "server-side-fallback-2026-07-01"
FILAS_A_CLAUDE = 50
MAX_PREGUNTA = 1000

# ------------------------------------------------------------------ lista blanca (esquema)
# Cada vista: (descripción, {columna: significado}). Una prueba verifica que las columnas
# coincidan exactamente con las de la vista real.
ESQUEMA = {
    "vw_predicciones": (
        "Una fila por predicción. origen='uso' son estudios reales subidos por doctores; "
        "origen='prueba' son los resultados de los 5 modelos sobre el conjunto de prueba.",
        {"prediccion_id": "número de la predicción", "origen": "'uso' o 'prueba'",
         "creado_en": "fecha y hora en que se registró", "fecha": "fecha del estudio",
         "anio": "año de la fecha del estudio", "mes": "mes (1-12)", "nombre_mes": "nombre del mes en español",
         "semana": "semana ISO del año", "dia_semana": "día de la semana en español",
         "edad": "edad del paciente ficticio (NULL en prueba)", "grupo_edad": "'0-17', '18-39', '40-59' o '60+'",
         "sexo": "'F', 'M' u 'Otro'", "doctor": "usuario del doctor que subió el estudio (NULL en prueba)",
         "modelo": "nombre del modelo", "tipo_modelo": "'clasico' o 'red_keras'",
         "modelo_version": "versión del modelo (v001, v002... para la red)",
         "estado_modelo": "'referencia', 'candidato', 'produccion' o 'retirado'",
         "diagnostico_predicho": "'tumor' o 'sin_tumor' (decisión del modelo)",
         "predicho_tumor": "1 si el modelo dijo tumor, 0 si no",
         "diagnostico_confirmado": "diagnóstico real confirmado: sin_tumor, tumor, glioma, meningioma o pituitary (NULL si está pendiente)",
         "confirmado_tumor": "1 si el diagnóstico confirmado es tumor, 0 si no, NULL si pendiente",
         "probabilidad_tumor": "probabilidad de tumor (0 a 1)", "umbral": "umbral de decisión usado",
         "tipo_probable": "tipo de tumor más probable (NULL si no hay tumor)",
         "probabilidad_tipo": "probabilidad del tipo", "de_acuerdo": "1 si el doctor estuvo de acuerdo, 0 si no, NULL si no ha confirmado",
         "tiempo_respuesta_ms": "tiempo de respuesta del modelo en milisegundos (solo uso)",
         "acierto": "1 si la predicción coincide con lo confirmado, 0 si no, NULL si pendiente",
         "falso_negativo": "1 si el modelo dijo sin tumor y sí había tumor", "falso_positivo": "1 si el modelo dijo tumor y no había"}),
    "vw_estudios_semana": (
        "Estudios de uso por semana ISO (de la fecha del estudio) y doctor.",
        {"anio": "año", "semana": "semana ISO", "primer_dia": "primera fecha con estudios en esa semana",
         "doctor": "usuario del doctor", "estudios": "número de estudios", "con_posible_tumor": "estudios en que el modelo dijo tumor",
         "confirmados": "estudios ya confirmados por el doctor", "desacuerdos": "estudios en que el doctor no estuvo de acuerdo"}),
    "vw_metricas_modelo": (
        "Matriz de confusión por versión de modelo y origen, solo con casos confirmados.",
        {"modelo_id": "id del modelo", "modelo": "nombre", "tipo_modelo": "'clasico' o 'red_keras'",
         "modelo_version": "versión", "estado_modelo": "estado del modelo", "origen": "'uso' o 'prueba'",
         "casos": "casos confirmados", "vp": "verdaderos positivos", "vn": "verdaderos negativos",
         "fp": "falsos positivos", "fn": "falsos negativos",
         "tiempo_promedio_ms": "tiempo promedio de respuesta de esos casos (NULL en prueba)"}),
    "vw_modelos": (
        "Catálogo de modelos.",
        {"modelo_id": "id", "nombre": "nombre", "tipo": "'clasico' o 'red_keras'", "version": "versión",
         "estado": "'referencia', 'candidato', 'produccion' o 'retirado'", "umbral": "umbral de decisión",
         "sensibilidad": "sensibilidad registrada", "especificidad": "especificidad registrada", "f1": "F1", "auc": "AUC",
         "origen_metricas": "'prueba' o 'validacion' (de dónde salen las métricas)",
         "entrenamiento_id": "entrenamiento que lo generó", "aprobado_en": "última vez que pasó a producción",
         "creado_en": "fecha de registro"}),
    "vw_entrenamientos": (
        "Entrenamientos y reentrenamientos de la red.",
        {"entrenamiento_id": "id", "estado": "'en_cola', 'corriendo', 'terminado', 'cancelado' o 'error'",
         "epocas_max": "épocas máximas", "epoca_actual": "última época", "mejor_epoca": "época de menor pérdida de validación",
         "diagnostico": "'convergió', 'se detuvo antes de converger', 'sobreajuste', 'no aprende' o 'cancelado'",
         "iniciado_en": "inicio", "terminado_en": "fin", "version": "versión del modelo generado",
         "solicitado_por": "usuario que lo pidió"}),
    "vw_metricas_pliegue": (
        "Métricas por pliegue de la validación cruzada.",
        {"entrenamiento_id": "entrenamiento (NULL para los clásicos)", "modelo": "nombre del modelo",
         "modelo_version": "versión", "pliegue": "número de pliegue (1-5)", "sensibilidad": "sensibilidad",
         "especificidad": "especificidad", "precision": "precisión", "f1": "F1", "auc": "AUC",
         "vp": "verdaderos positivos", "vn": "verdaderos negativos", "fp": "falsos positivos", "fn": "falsos negativos"}),
    "vw_historial_epocas": (
        "Historial por época de cada entrenamiento.",
        {"entrenamiento_id": "entrenamiento", "etapa": "'pliegue_1'..'pliegue_5', 'cabeza' o 'ajuste_fino'",
         "epoca": "época (desde 1)", "perdida": "pérdida de entrenamiento", "exactitud": "exactitud de entrenamiento",
         "perdida_val": "pérdida de validación", "exactitud_val": "exactitud de validación",
         "tasa_aprendizaje": "tasa de aprendizaje"}),
    "vw_bitacora": (
        "Bitácora de acciones del sistema.",
        {"evento_id": "id", "fecha_hora": "fecha y hora", "usuario": "usuario", "rol": "'doctor' o 'administrador'",
         "accion": "LOGIN_OK, LOGIN_FALLIDO, LOGOUT, ACCESO_DENEGADO, ESTUDIO_CREADO, ESTUDIO_CONFIRMADO, "
                   "ENTRENAMIENTO_*, MODELO_APROBADO, MODELO_REVERTIDO, UMBRAL_ACTUALIZADO, USUARIO_*, CONSULTA_IA, "
                   "CONSULTA_IA_BLOQUEADA o CARGA_DATOS",
         "detalle": "detalle en texto", "exito": "1 si la acción tuvo éxito, 0 si no"}),
    "dim_fecha": (
        "Calendario.",
        {"fecha_id": "AAAAMMDD", "fecha": "fecha", "anio": "año", "mes": "mes", "nombre_mes": "nombre del mes",
         "semana": "semana ISO", "dia_semana": "día de la semana"}),
    "dim_diagnostico": (
        "Catálogo de diagnósticos.",
        {"diagnostico_id": "id", "clave": "sin_tumor, tumor, glioma, meningioma o pituitary", "nombre": "nombre en español",
         "es_tumor": "1 si es tumor"}),
    "dim_usuario": (
        "Usuarios del sistema (sin contraseñas).",
        {"usuario_id": "id", "usuario": "nombre de usuario", "rol": "'doctor' o 'administrador'", "activo": "1 si está activo"}),
}
assert list(ESQUEMA) == list(LISTA_BLANCA_ASISTENTE), "ESQUEMA y LISTA_BLANCA_ASISTENTE deben coincidir"
PERMITIDAS = frozenset(LISTA_BLANCA_ASISTENTE)

# Columnas que nunca se devuelven ni se envían a la API (por si alguna vista llegara a tenerlas).
PATRON_COLUMNA_SENSIBLE = re.compile(r"(identificador|paciente_id|hash|password|contrase|token|^ip$)", re.I)
# Identificadores de paciente escritos dentro de la pregunta (p. ej. PAC-0001): se ocultan.
PATRON_ID_EN_TEXTO = re.compile(r"\b[A-Za-z]{2,5}-\d{1,6}\b")

NODOS_PROHIBIDOS = tuple(c for c in (getattr(exp, n, None) for n in (
    "Insert", "Update", "Delete", "Merge", "Drop", "Alter", "AlterTable", "AlterColumn", "Create", "TruncateTable",
    "Grant", "Revoke", "Command", "Into", "Pragma", "Attach", "Detach", "Execute", "ExecuteSql", "Use", "Set",
    "Transaction", "Commit", "Rollback", "LoadData", "Copy", "Cache", "Uncache", "Refresh", "Analyze", "Kill",
    "Declare")) if isinstance(c, type))
FUNCIONES_PROHIBIDAS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer", "fts5", "zeroblob",
                        "randomblob", "sqlite_offset", "openrowset", "opendatasource", "openquery", "openxml",
                        "sleep", "pg_sleep", "waitfor", "benchmark", "shell", "system"}
PREFIJOS_PROHIBIDOS = ("xp_", "sp_", "fn_", "sqlite_", "pragma_", "sys.")
PALABRAS_PROHIBIDAS = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|exec|execute|into|pragma|attach|"
    r"detach|vacuum|reindex|load_extension|readfile|writefile|openrowset|opendatasource|openquery|"
    r"xp_\w+|sp_\w+|waitfor|shutdown|backup|restore|dbcc|bulk)\b", re.I)
INICIO_SQL = re.compile(r"^\s*(\(|select|with|insert|update|delete|drop|alter|create|pragma|attach|detach|exec|"
                        r"execute|merge|truncate|grant|revoke|replace|vacuum|reindex|declare|use)\b", re.I)


def dialecto():
    """Dialecto de sqlglot del motor en uso."""
    return "tsql" if config.DB_MODO == "fabric" else "sqlite"


def esquema_texto():
    """Descripción textual de la lista blanca que recibe Claude."""
    partes = []
    for vista, (descripcion, columnas) in ESQUEMA.items():
        partes.append(f"- {vista}: {descripcion}")
        for col, significado in columnas.items():
            partes.append(f"    * {col}: {significado}")
    return "\n".join(partes)


# ------------------------------------------------------------------ prompts
PLANTILLA_SISTEMA_SQL = """Eres el asistente de consultas de un tablero hospitalario académico que apoya la detección de tumores cerebrales en resonancias. Ayudas al Administrador a obtener datos con UNA consulta SQL de solo lectura.

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

Responde solo con el objeto JSON pedido: puede_responder (booleano), sql (la consulta, o "" si no se puede), explicacion (una oración en español sobre qué calcula la consulta) y motivo (por qué no se puede responder, o "")."""

PLANTILLA_USUARIO_SQL = """Fecha de hoy: {hoy} (año {anio}, semana ISO {semana}).

<pregunta>
{pregunta}
</pregunta>"""

PROMPT_SISTEMA_RESPUESTA = """Eres el asistente de consultas de un tablero hospitalario académico de apoyo a la detección de tumores cerebrales. Recibes la pregunta del Administrador, la consulta SQL que se ejecutó y sus resultados. Redacta la respuesta en español de México, formal, sencillo y claro, en 1 a 4 oraciones o una lista corta.

Reglas:
- Usa solo los números que aparecen en los resultados; no inventes ni extrapoles. Si no hay filas, dilo.
- Si los resultados vienen recortados, indícalo.
- No des diagnósticos médicos ni recomendaciones clínicas; es información de apoyo sobre el uso del sistema.
- No menciones detalles técnicos de SQL salvo que ayuden a entender el resultado."""

PLANTILLA_USUARIO_RESPUESTA = """<pregunta>
{pregunta}
</pregunta>

<consulta_sql>
{sql}
</consulta_sql>

<resultados filas_totales="{n_filas}" filas_mostradas="{n_mostradas}">
columnas: {columnas}
{filas}
</resultados>"""

ESQUEMA_SALIDA_SQL = {
    "type": "object",
    "properties": {
        "puede_responder": {"type": "boolean"},
        "sql": {"type": "string"},
        "explicacion": {"type": "string"},
        "motivo": {"type": "string"},
    },
    "required": ["puede_responder", "sql", "explicacion", "motivo"],
    "additionalProperties": False,
}


def prompt_sistema_sql():
    motor = "Microsoft Fabric (SQL Server)" if dialecto() == "tsql" else "SQLite"
    return PLANTILLA_SISTEMA_SQL.format(motor=motor, dialecto=dialecto(), esquema=esquema_texto(),
                                        limite=config.ASISTENTE_LIMITE_FILAS)


def prompt_usuario_sql(pregunta, hoy=None):
    hoy = hoy or date.today()
    anio, semana, _ = hoy.isocalendar()
    return PLANTILLA_USUARIO_SQL.format(hoy=hoy.isoformat(), anio=anio, semana=semana, pregunta=pregunta)


def prompt_usuario_respuesta(pregunta, sql, columnas, filas):
    mostradas = filas[:FILAS_A_CLAUDE]
    texto = "\n".join(json.dumps(f, ensure_ascii=False, default=str) for f in mostradas) or "(sin filas)"
    return PLANTILLA_USUARIO_RESPUESTA.format(pregunta=pregunta, sql=sql, n_filas=len(filas),
                                              n_mostradas=len(mostradas), columnas=", ".join(columnas), filas=texto)


# ------------------------------------------------------------------ validación
class Bloqueada(Exception):
    """La consulta no pasa las reglas de seguridad. El mensaje es el motivo, en español."""


def _sin_cadenas(sql):
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def _valor_limite(ast):
    lim = ast.args.get("limit")
    if lim is None:
        return None
    valor = lim.args.get("expression") or lim.this
    try:
        return int(valor.name) if isinstance(valor, exp.Literal) else None
    except (TypeError, ValueError):
        return None


def _nombre_funcion(nodo):
    if isinstance(nodo, exp.Anonymous):
        return str(nodo.name or "").lower()
    try:
        return nodo.sql_name().lower()
    except Exception:  # noqa: BLE001
        return type(nodo).__name__.lower()


def validar_sql(sql, dialecto_origen=None, limite=None):
    """Valida una consulta. Devuelve el SQL final (regenerado, con límite) o lanza Bloqueada."""
    dialecto_origen = dialecto_origen or dialecto()
    limite = int(limite or config.ASISTENTE_LIMITE_FILAS)
    texto = (sql or "").strip()
    if not texto:
        raise Bloqueada("No hay consulta.")
    if len(texto) > 5000:
        raise Bloqueada("La consulta es demasiado larga.")
    plano = _sin_cadenas(texto)
    if "--" in plano or "/*" in plano or "*/" in plano or "#" in plano:
        raise Bloqueada("La consulta no puede llevar comentarios.")
    if ";" in plano.rstrip().rstrip(";"):
        raise Bloqueada("Solo se permite una sentencia.")
    prohibida = PALABRAS_PROHIBIDAS.search(plano)
    if prohibida:
        raise Bloqueada(f"La consulta contiene una instrucción no permitida: {prohibida.group(1).upper()}.")
    try:
        sentencias = [s for s in sqlglot.parse(texto, read=dialecto_origen) if s is not None]
    except Exception:  # noqa: BLE001 - cualquier error de análisis bloquea
        raise Bloqueada("La consulta no se pudo analizar como SQL válido.") from None
    if len(sentencias) != 1:
        raise Bloqueada("Solo se permite una sentencia.")
    ast = sentencias[0]
    tipos_raiz = tuple(t for t in (exp.Select, getattr(exp, "Union", None), getattr(exp, "Intersect", None),
                                   getattr(exp, "Except", None)) if t is not None)
    if not isinstance(ast, tipos_raiz):
        raise Bloqueada("Solo se permiten consultas SELECT.")
    for nodo in ast.walk():
        nodo = nodo[0] if isinstance(nodo, tuple) else nodo
        if isinstance(nodo, NODOS_PROHIBIDOS):
            raise Bloqueada(f"La consulta contiene una operación no permitida ({type(nodo).__name__}).")
    ctes = {str(c.alias_or_name).lower() for c in ast.find_all(exp.CTE)}
    for tabla in ast.find_all(exp.Table):
        if isinstance(tabla.this, exp.Func):
            raise Bloqueada("No se permiten funciones que actúan como tabla.")
        nombre = str(tabla.name or "").lower()
        if not nombre:
            raise Bloqueada("Hay una tabla sin nombre en la consulta.")
        if tabla.args.get("catalog") is not None:
            raise Bloqueada("No se permite consultar otras bases de datos.")
        esquema = str(tabla.db or "").lower()
        if esquema and esquema not in ("dbo", "main"):
            raise Bloqueada(f"No se permite el esquema '{esquema}'.")
        if nombre in ctes and not esquema:
            continue
        if nombre not in PERMITIDAS:
            raise Bloqueada(f"La tabla o vista '{nombre}' no está en la lista blanca.")
    for funcion in ast.find_all(exp.Func):
        nombre = _nombre_funcion(funcion)
        if nombre in FUNCIONES_PROHIBIDAS or nombre.startswith(PREFIJOS_PROHIBIDOS):
            raise Bloqueada(f"La función '{nombre}' no está permitida.")
    for columna in ast.find_all(exp.Column):
        if PATRON_COLUMNA_SENSIBLE.search(str(columna.name or "")):
            raise Bloqueada(f"La columna '{columna.name}' no está permitida.")
    # Límite de filas forzado.
    if isinstance(ast, exp.Select):
        actual = _valor_limite(ast)
        n = limite if actual is None else max(0, min(actual, limite))
        ast = ast.limit(n, copy=True)
    else:
        ast = exp.select("*").from_(ast.subquery("resultado")).limit(limite)
    final = ast.sql(dialect=dialecto(), comments=False)
    if PALABRAS_PROHIBIDAS.search(_sin_cadenas(final)):
        raise Bloqueada("La consulta final contiene una instrucción no permitida.")
    return final


# ------------------------------------------------------------------ ejecución de solo lectura
class TiempoAgotado(Exception):
    pass


def _valor(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return None
    return v


def ejecutar(sql, limite=None, segundos=None):
    """Ejecuta una consulta YA VALIDADA en solo lectura. Devuelve (columnas, filas)."""
    limite = int(limite or config.ASISTENTE_LIMITE_FILAS)
    segundos = float(segundos or config.ASISTENTE_SEGUNDOS_SQL)
    if config.DB_MODO == "fabric":
        # Conexión con ApplicationIntent=ReadOnly y tiempo máximo; la transacción se revierte siempre.
        # En producción, el usuario de esta conexión debe tener solo db_datareader (sql/README.md).
        crudo = db.motor_lectura().raw_connection()
        try:
            crudo.dbapi_connection.timeout = int(segundos)
            cursor = crudo.cursor()
            try:
                cursor.execute(sql)
                columnas = [d[0] for d in cursor.description]
                filas = [[_valor(v) for v in fila] for fila in cursor.fetchmany(limite)]
            finally:
                cursor.close()
                crudo.rollback()
        finally:
            crudo.dbapi_connection.timeout = 0
            crudo.close()
        return _quitar_sensibles(columnas, filas)
    uri = f"file:{quote(config.DB_RUTA.as_posix(), safe='/:')}?mode=ro"
    conexion = sqlite3.connect(uri, uri=True, timeout=5)
    limite_tiempo = time.monotonic() + segundos
    conexion.set_progress_handler(lambda: 1 if time.monotonic() > limite_tiempo else 0, 10000)
    try:
        conexion.execute("PRAGMA query_only = ON")
        cursor = conexion.execute(sql)
        columnas = [d[0] for d in cursor.description]
        filas = [[_valor(v) for v in fila] for fila in cursor.fetchmany(limite)]
    except sqlite3.OperationalError as e:
        if "interrupt" in str(e).lower():
            raise TiempoAgotado() from None
        raise
    finally:
        conexion.close()
    return _quitar_sensibles(columnas, filas)


def _quitar_sensibles(columnas, filas):
    quedan = [i for i, c in enumerate(columnas) if not PATRON_COLUMNA_SENSIBLE.search(str(c))]
    if len(quedan) == len(columnas):
        return columnas, filas
    return [columnas[i] for i in quedan], [[f[i] for i in quedan] for f in filas]


# ------------------------------------------------------------------ llamadas a Claude
_cliente = None
_respaldo_aceptado = True


def obtener_cliente():
    """Dependencia de FastAPI: cliente de Anthropic, o None si no hay clave. Las pruebas la sustituyen."""
    global _cliente
    if not config.ANTHROPIC_API_KEY:
        return None
    if _cliente is None:
        import anthropic
        _cliente = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, timeout=120.0, max_retries=2)
    return _cliente


class RespuestaInvalida(Exception):
    """El modelo se negó, se cortó o no devolvió lo esperado. El mensaje va al usuario."""


def _llamar(cliente, sistema, mensaje, esquema=None):
    """Una llamada a Claude. Devuelve el texto de la respuesta (revisa stop_reason antes)."""
    global _respaldo_aceptado
    salida = {"effort": ESFUERZO}
    if esquema is not None:
        salida["format"] = {"type": "json_schema", "schema": esquema}
    kwargs = {"model": config.ANTHROPIC_MODELO, "max_tokens": MAX_TOKENS, "system": sistema,
              "messages": [{"role": "user", "content": mensaje}], "output_config": salida}
    respuesta = None
    if config.ASISTENTE_RESPALDO and _respaldo_aceptado:
        try:
            respuesta = cliente.beta.messages.create(betas=[BETA_RESPALDO], fallbacks="default", **kwargs)
        except Exception as e:  # noqa: BLE001
            import anthropic
            if isinstance(e, anthropic.BadRequestError) and "fallback" in str(getattr(e, "message", "")).lower():
                log.warning("La API no aceptó el respaldo del servidor; se sigue sin él.")
                _respaldo_aceptado = False
            else:
                raise
    if respuesta is None:
        respuesta = cliente.beta.messages.create(**kwargs)
    motivo = getattr(respuesta, "stop_reason", None)
    if motivo == "refusal":
        raise RespuestaInvalida("El modelo se negó a responder esta pregunta.")
    if motivo == "max_tokens":
        raise RespuestaInvalida("La respuesta del modelo quedó incompleta.")
    texto = next((b.text for b in getattr(respuesta, "content", []) or [] if getattr(b, "type", None) == "text"),
                 None)
    if not texto:
        raise RespuestaInvalida("El modelo no devolvió texto.")
    return texto


def generar_sql(cliente, pregunta, hoy=None):
    texto = _llamar(cliente, prompt_sistema_sql(), prompt_usuario_sql(pregunta, hoy), ESQUEMA_SALIDA_SQL)
    try:
        datos = json.loads(texto)
    except ValueError:
        raise RespuestaInvalida("El modelo no devolvió el formato esperado.") from None
    if not isinstance(datos, dict):
        raise RespuestaInvalida("El modelo no devolvió el formato esperado.")
    return datos


def redactar(cliente, pregunta, sql, columnas, filas):
    filas_dict = [dict(zip(columnas, f)) for f in filas]
    return _llamar(cliente, PROMPT_SISTEMA_RESPUESTA, prompt_usuario_respuesta(pregunta, sql, columnas, filas_dict))


# ------------------------------------------------------------------ flujo completo
def _resultado(estado, respuesta, sql=None, columnas=None, filas=None):
    return {"estado": estado, "respuesta": respuesta, "sql": sql, "columnas": columnas or [], "filas": filas or []}


def ocultar_identificadores(texto):
    return PATRON_ID_EN_TEXTO.sub("[identificador]", texto or "")


def _mensaje_error_api(e):
    """Mensaje en español para errores del SDK; nunca incluye la clave ni el texto del error."""
    import anthropic
    if isinstance(e, anthropic.AuthenticationError):
        return "La clave de la API de Claude no es válida."
    if isinstance(e, anthropic.PermissionDeniedError):
        return "La clave de la API de Claude no tiene permiso para este modelo."
    if isinstance(e, anthropic.RateLimitError):
        return "Se alcanzó el límite de uso de la API de Claude. Intenta de nuevo en unos minutos."
    if isinstance(e, anthropic.APIStatusError):
        return f"La API de Claude respondió con un error (código {e.status_code})."
    if isinstance(e, anthropic.APIConnectionError):
        return "No se pudo conectar con la API de Claude."
    return "Ocurrió un error inesperado en el asistente."


def responder(pregunta, usuario=None, ip=None, cliente=None, hoy=None):
    """Responde una pregunta en español. Devuelve el dict del contrato."""
    if cliente is None:
        return _resultado("sin_configurar", "El asistente no está configurado: falta ANTHROPIC_API_KEY en el "
                                            "archivo .env del servidor.")
    pregunta = (pregunta or "").strip()
    if not pregunta:
        return _resultado("error", "Escribe una pregunta.")
    if len(pregunta) > MAX_PREGUNTA:
        return _resultado("error", f"La pregunta es demasiado larga (máximo {MAX_PREGUNTA} caracteres).")
    pregunta = ocultar_identificadores(pregunta)
    resumen_pregunta = pregunta[:300]
    sql_propuesto = None
    try:
        if INICIO_SQL.match(pregunta):
            sql_propuesto = pregunta          # consulta escrita por el administrador
            origen = "escrita por el administrador"
        else:
            datos = generar_sql(cliente, pregunta, hoy)
            origen = "generada por Claude"
            if not datos.get("puede_responder") or not str(datos.get("sql") or "").strip():
                motivo = str(datos.get("motivo") or "La pregunta no se puede responder con los datos disponibles.")
                db.registrar("CONSULTA_IA_BLOQUEADA", f"Pregunta: {resumen_pregunta} | El modelo no generó consulta: "
                             f"{motivo[:300]}", usuario, ip, exito=False)
                return _resultado("bloqueada", motivo)
            sql_propuesto = str(datos["sql"])
        try:
            sql = validar_sql(sql_propuesto)
        except Bloqueada as b:
            db.registrar("CONSULTA_IA_BLOQUEADA", f"Pregunta: {resumen_pregunta} | Consulta {origen} rechazada: {b} | "
                         f"SQL: {sql_propuesto[:500]}", usuario, ip, exito=False)
            return _resultado("bloqueada", f"La consulta se bloqueó por seguridad: {b}", sql_propuesto)
        try:
            columnas, filas = ejecutar(sql)
        except TiempoAgotado:
            db.registrar("CONSULTA_IA", f"Pregunta: {resumen_pregunta} | SQL: {sql[:600]} | tiempo agotado",
                         usuario, ip, exito=False)
            return _resultado("error", "La consulta tardó demasiado y se detuvo.", sql)
        except Exception as e:  # noqa: BLE001 - error del motor (columna inexistente, etc.)
            db.registrar("CONSULTA_IA", f"Pregunta: {resumen_pregunta} | SQL: {sql[:600]} | error al ejecutar: "
                         f"{type(e).__name__}", usuario, ip, exito=False)
            return _resultado("error", "La consulta no se pudo ejecutar: " + str(e)[:200], sql)
        respuesta = redactar(cliente, pregunta, sql, columnas, filas)
        db.registrar("CONSULTA_IA", f"Pregunta: {resumen_pregunta} | SQL: {sql[:600]} | filas: {len(filas)}",
                     usuario, ip)
        return _resultado("ok", respuesta, sql, columnas, filas)
    except RespuestaInvalida as e:
        db.registrar("CONSULTA_IA", f"Pregunta: {resumen_pregunta} | {e}", usuario, ip, exito=False)
        return _resultado("error", str(e), sql_propuesto)
    except Exception as e:  # noqa: BLE001 - errores de la API o inesperados; sin detalles
        log.warning("Asistente: error %s", type(e).__name__)
        mensaje = _mensaje_error_api(e)
        db.registrar("CONSULTA_IA", f"Pregunta: {resumen_pregunta} | error de la API: {type(e).__name__}",
                     usuario, ip, exito=False)
        return _resultado("error", mensaje, sql_propuesto)
