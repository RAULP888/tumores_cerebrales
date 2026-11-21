# Base de datos (`sql/`)

| Archivo | Qué hace |
|---|---|
| `01_crear_tablas.sql` | Esquema en T-SQL para Microsoft Fabric (tablas con `DATETIME2(0)`, llaves, CHECK, índices, `dim_fecha`, `dim_diagnostico` y vistas). Re-ejecutable: solo crea lo que falta y recrea las vistas con `CREATE OR ALTER`. |
| `02_cargar_datos.py` | Carga inicial idempotente (dimensiones, modelos, resultados de prueba de los 5 modelos y la corrida original de v001). Funciona con `DB_MODO=local` y `DB_MODO=fabric`. |
| `03_consultas.sql` | 11 consultas de análisis comentadas, escritas para correr igual en SQLite y en T-SQL. `pruebas/test_consultas_sql.py` las ejecuta y compara algunas con pandas. |

## Modo local (SQLite)
`DB_MODO=local` (por omisión): `app/almacen/tumores.db`. El esquema lo crea `app/backend/tablas.py` (SQLAlchemy Core) con las mismas vistas.

## Modo Fabric (SQL Server)
En `.env`: `DB_MODO=fabric`, `FABRIC_SERVIDOR` y `FABRIC_BASE` (opcional `FABRIC_USUARIO`, que se usa como sugerencia de cuenta al iniciar sesión).

**Inicio de sesión.** `Authentication=ActiveDirectoryInteractive` del driver ODBC falla desde un proceso sin consola (FA004), así que la aplicación obtiene un token de Microsoft Entra ID con `azure-identity` (`InteractiveBrowserCredential`) y lo entrega al driver "ODBC Driver 18 for SQL Server" (atributo `SQL_COPT_SS_ACCESS_TOKEN`). La primera vez se abre el navegador; la sesión queda en un caché cifrado del sistema operativo (`tumores_cerebrales`) y en `app/almacen/fabric_auth.json` (ignorado por git), así que el servidor, el reentrenamiento y la carga la reutilizan sin volver a pedirla. El token se renueva solo cuando está por vencer. Código: `app/backend/fabric.py` y `app/backend/db.py`.

**Esquema.** En modo Fabric, `db.crear_esquema()` ejecuta `01_crear_tablas.sql` por lotes (`GO`); no usa `metadata.create_all` (que crearía `DATETIME` y omitiría los CHECK).

**Prueba de punta a punta:** `.venv\Scripts\python.exe scripts/probar_fabric.py` (conecta, crea el esquema, carga, cuenta filas, corre 3 consultas de `03_consultas.sql` y una del asistente). Se corre con el usuario presente porque puede abrir el navegador.

## Asistente de consultas: solo lectura
- El asistente valida cada consulta (solo `SELECT` sobre la lista blanca de vistas, con `TOP` forzado en T-SQL) y la ejecuta en una conexión aparte con `ApplicationIntent=ReadOnly`, tiempo máximo y transacción revertida.
- `ApplicationIntent=ReadOnly` **no impide escribir** si la base no tiene réplica de lectura. **En producción, la conexión del asistente debe usar un usuario con solo `db_datareader`** (o, mejor, `GRANT SELECT` únicamente sobre las vistas de la lista blanca); el ejemplo está al final de `01_crear_tablas.sql`. En la versión actual el asistente usa la misma identidad de Entra ID que la aplicación; separar la identidad es la mejora pendiente para producción.

## Diferencias SQLite / T-SQL resueltas en el código
| Tema | SQLite | T-SQL |
|---|---|---|
| Límite de filas del asistente | `LIMIT n` | `TOP n` (sqlglot lo traduce) |
| Solo lectura | `file:...?mode=ro` + `PRAGMA query_only` | `ApplicationIntent=ReadOnly` + usuario `db_datareader` |
| Ajustes de conexión | `PRAGMA journal_mode=WAL`, `busy_timeout`, `foreign_keys` | no aplica |
| Booleanos en consultas | `= 1` / `= 0` (no `IS 1`, que T-SQL rechaza) | igual |
| Vistas | `CREATE VIEW IF NOT EXISTS` | `CREATE OR ALTER VIEW` |
| Inserciones masivas | `executemany` | `fast_executemany=True`, lotes de 1,000 |
