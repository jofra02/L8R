# SETUP_FINDINGS — Entorno espejo Docker (2026-07-07)

Registro de hallazgos durante el levantamiento completo del entorno espejo
(ciclo: `.env` → build → up → migraciones → init Qdrant → seeding → E2E).
Cada finding indica severidad y el fix sugerido para aplicar en el root del proyecto.

Convención de severidad:
- **BLOCKER**: impide completar el setup sin workaround.
- **BUG**: comportamiento incorrecto, no bloquea el setup.
- **DOC**: documentación desalineada con el código.
- **MINOR**: mejora o inconsistencia menor.

---

## F-01 [DOC] Seeding documentado vía `docker compose exec` pero `data/tenants/` está excluido de la imagen

- **Dónde**: `docs/setup/deployment.md` §"Tenant Registration" indica:
  `docker compose exec app python src/main.py register-tenant --file data/tenants/<tenant>/tenant.yaml`
- **Problema**: `.dockerignore` excluye `data/tenants/` (y `data/evidence/`), por lo que esos YAML
  no existen dentro del contenedor `app`. El comando documentado falla con file-not-found.
- **Fix sugerido**: o bien (a) documentar el seeding desde el host (`uv run python src/main.py ...`
  con los puertos publicados), o (b) documentar un `docker compose cp data/tenants app:/app/data/` previo,
  o (c) montar `./data/tenants` como volumen read-only en el servicio `app`.

---

## F-02 [BLOCKER] Build del frontend roto: TS18048 en `ComponentModal.tsx`

- **Dónde**: `frontend/src/pages/inventory/ComponentModal.tsx:94-96` (función `buildMcpConnection`).
- **Problema**: `docker compose build frontend` falla (`tsc -b` exit 2):
  `error TS18048: 'pack' is possibly 'undefined'` ×3. Con `noUncheckedIndexedAccess`,
  `MCP_PACKS[mcpPack]` tipa `T | undefined` y el código lo desreferencia sin guard.
  El branch `feature/mcp-gateway` no compila → la imagen `frontend` no se puede construir.
- **Fix aplicado en el espejo** (replicar en el root):
  ```ts
  const pack = MCP_PACKS[mcpPack] ?? MCP_PACKS[0];
  if (!pack) return undefined;
  ```
- **Nota**: indica que el frontend no se compiló (`npm run build`/`tsc`) después del último cambio
  en `ComponentModal.tsx`. Sugerencia: agregar un check de build de frontend al flujo previo a commit.

---

## F-03 [BLOCKER] Healthcheck de Qdrant usa `wget`, inexistente en la imagen `qdrant/qdrant:v1.14.0`

- **Dónde**: `docker-compose.yml`, servicio `qdrant`:
  `test: ["CMD-SHELL", "wget -qO- http://localhost:6333/readyz || exit 1"]`
- **Problema**: la imagen oficial de Qdrant no trae `wget` ni `curl`. El healthcheck falla
  siempre (`/bin/sh: 1: wget: not found`), el contenedor queda `unhealthy` aunque Qdrant
  esté sirviendo, y `docker compose up` aborta con
  `dependency failed to start: container ...-qdrant-1 is unhealthy` → el `app` y el `frontend`
  nunca arrancan. **El full-stack Docker documentado en deployment.md no puede haber funcionado
  nunca con esta imagen.**
- **Fix aplicado en el espejo** (replicar en el root): probe TCP+HTTP con bash (la imagen sí trae bash):
  ```yaml
  test: ["CMD-SHELL", "bash -c 'exec 3<>/dev/tcp/127.0.0.1/6333 && echo -e \"GET /readyz HTTP/1.1\\r\\nHost: localhost\\r\\nConnection: close\\r\\n\\r\\n\" >&3 && grep -q \"200 OK\" <&3'"]
  ```

---

## F-04 [BLOCKER] `entrypoint.sh` llega con CRLF a la imagen — el contenedor `app` entra en crash-loop

- **Dónde**: `scripts/entrypoint.sh` + falta de `.gitattributes` en el repo.
- **Problema**: el repo se clona en Windows con `core.autocrlf=true` (index LF, working tree CRLF).
  El `COPY . .` del Dockerfile mete el script con CRLF y dentro del contenedor cada línea
  arrastra un `\r`:
  - `set -e` falla (`set: -` invalid option) → los errores siguientes no abortan;
  - `alembic upgrade head\r` → `Can't locate revision identified by 'head'` (las migraciones NUNCA corren);
  - `python -m src.utils.init_qdrant\r` → `No module named src.utils.init_qdrant`;
  - `\r` sueltos → `$'\r': command not found`, y el heredoc del if final →
    `syntax error: unexpected end of file` → uvicorn no arranca → restart-loop.
- **Fix aplicado en el espejo**: `sed -i 's/\r$//' scripts/entrypoint.sh` + rebuild.
- **Fix sugerido en el root** (los dos, defensa en profundidad):
  1. Agregar `.gitattributes`:
     ```
     *.sh text eol=lf
     ```
  2. Endurecer el Dockerfile (stage runtime): `RUN sed -i 's/\r$//' scripts/entrypoint.sh`
     para que un checkout CRLF nunca rompa la imagen.

---

## F-05 [BUG] Primer arranque: la indexación del tool_catalog bloquea `/health` y el healthcheck marca `app` unhealthy → `frontend` no arranca

- **Dónde**: `src/api/app.py` (lifespan: `CapabilityRegistry.index_tools()` síncrono dentro del startup)
  + `docker-compose.yml` (healthcheck del `app`: `start_period: 30s`, `retries: 5`, `interval: 10s`).
- **Problema**: uvicorn no sirve requests hasta que el lifespan termina. En un Qdrant limpio,
  `index_tools()` clasifica 2182 tools vía LLM (146 batches) + embeddings — varios minutos.
  La ventana del healthcheck (~80s) expira, Docker marca `app` como `unhealthy`, y
  `docker compose up -d` aborta el `frontend` (`dependency failed to start`). El stack "one-command"
  de deployment.md no funciona en el primer boot con Qdrant vacío. En warm boots no se reproduce
  (diff logic: "tool_catalog up to date, skipping").
- **Workaround en el espejo**: esperar a que termine la indexación (el healthcheck vuelve a `healthy`
  solo) y correr `docker compose up -d frontend` de nuevo.
- **Fix sugerido en el root** (uno o ambos):
  1. Mover `index_tools()` a un background task post-startup (`asyncio.create_task`) para que
     `/health` responda de inmediato; exponer el estado de indexación en `/health` o `/ready`.
  2. Como mínimo, subir `start_period` del healthcheck del `app` (p. ej. `600s`).

---

## F-06 [MINOR] Los comandos ops del CLI (`register-tenant`, `seed-context`, `create-tenant-key`) cargan los 2182 tools MCP antes de ejecutar

- **Dónde**: `src/main.py` — `main()` ejecuta `CapabilityRegistry.load_builtin_packs()` +
  `await CapabilityRegistry.load_external_tools()` incondicionalmente antes de despachar el comando.
- **Problema**: registrar un tenant (un INSERT en Postgres) tarda ~60s porque primero conecta al
  gateway por SSE y registra 2182 tools. Además, si el gateway está caído, el seeding falla aunque
  no lo necesite.
- **Fix sugerido**: cargar capabilities solo para los comandos que las usan (`test`); los comandos
  de seeding/keys no las necesitan.

---

## F-07 [MINOR] `seed_tenant` re-ejecutado duplica el scope "default" en `capability_scopes`

- **Dónde**: `src/utils/seed_context.py:47-57` — en cada corrida agrega un `CapabilityScope`
  nuevo sin chequear existencia (el propio comentario lo admite: "In real impl, handle existing
  scopes better").
- **Problema**: el registro de tenant no es idempotente; correr el seeding dos veces deja scopes
  duplicados.
- **Fix sugerido**: upsert por (`customer_id`, `scope_name`).

---

## F-08 [MINOR] `src/testing/test_inventory_gateway_sync.py` no es ejecutable con pytest pese al nombre `test_*`

- **Dónde**: `src/testing/test_inventory_gateway_sync.py` (nuevo en el branch).
- **Problema**: por el prefijo `test_`, pytest lo colecta pero los 5 casos fallan
  ("async def functions are not natively supported") — el archivo está diseñado como script
  (`python -m src.testing.test_inventory_gateway_sync`, así pasa 5/5 OK).
- **Fix sugerido**: convertirlo a pytest real (`@pytest.mark.asyncio` + `asyncio_mode=auto`
  en pyproject) o renombrarlo (p. ej. `verify_inventory_gateway_sync.py`) para que pytest no lo
  recoja roto.

---

## F-09 [BUG] Escritura de inventario como platform admin sin tenant explícito: 500 + device huérfano en el gateway bajo `__platform__`

- **Dónde**: `src/api/routers/inventory.py` + `src/api/services/inventory_service.py`
  (resolución de tenant en `AuthContext` para platform admins) y orden de operaciones del sync.
- **Reproducción**: login JWT como bootstrap super admin (`/auth/me` devuelve `customer_id: fake_client`),
  `POST /api/v1/inventory/components` con `mcp_connection` y **sin** `?customer_id=`.
- **Problema doble**:
  1. El `AuthContext` del platform admin resuelve al sentinel `__platform__` como `customer_id`
     (aunque `/auth/me` muestre `fake_client`). El INSERT en `client_contexts` viola la FK
     (`Key (customer_id)=(__platform__) is not present in platform_tenants`) → HTTP 500
     `internal_error` genérico. Debería ser un 400/422 claro ("platform admin requiere
     customer_id explícito") o usar el tenant activo del token.
  2. **El sync al gateway se ejecuta ANTES de persistir localmente**: el gateway creó
     `inventory/tenants/__platform__/devices/managed.yaml` con el device y token cifrado,
     y luego el guardado local falló → device huérfano en un tenant basura del gateway (drift).
     El diseño dice "local write always succeeds and sync status is surfaced" — el orden
     inverso (persistir local primero, sync después) o un rollback compensatorio evitaría esto.
     Nota: el admin API del gateway acepta cualquier `cid` en el path y crea el directorio del
     tenant si no existe — considerar validar contra tenants conocidos.

---

## F-10 [DOC] Quickstart §8 describe login del frontend por API key; el frontend actual usa email+password (JWT)

- **Dónde**: `docs/setup/quickstart.md` §8 ("You will see a login screen asking for an API key")
  y §6 (presenta la tenant key como credencial del dashboard).
- **Problema**: `LoginPage.tsx` pide email/password contra `/api/v1/auth/login` (RBAC + JWT,
  con cambio de contraseña forzado del bootstrap admin). La API key de tenant sirve solo para
  clientes programáticos y únicamente con permiso `tickets:write` (hardcodeado en
  `auth_service.py:_API_KEY_PERMISSIONS`) — no puede usar los endpoints de inventario.
- **Fix sugerido**: actualizar quickstart (login = bootstrap admin del log de migración o usuario
  creado con `create-admin`); aclarar el alcance real de las API keys.

---

## F-11 [BUG] Las API keys solo tienen `tickets:write`: pueden crear tickets pero no leer runs/reportes — el flujo documentado en quickstart §9 falla

- **Dónde**: `src/api/services/auth_service.py:17` (`_API_KEY_PERMISSIONS = {"tickets:write"}`).
- **Reproducción**: con la tenant key, `POST /api/v1/tickets` → 202 OK, pero
  `GET /api/v1/runs?ticket_id=...` → 403 `Requires permission 'runs:read'`.
- **Problema**: quickstart §6 describe el rol `operator` como "Submit tickets, view
  runs/evidence/hypotheses, retry runs", y §9 documenta el polling con la misma key. Un cliente
  programático que crea un ticket no puede consultar su resultado — la integración API queda coja.
- **Fix sugerido**: ampliar `_API_KEY_PERMISSIONS` (p. ej. `tickets:read`, `runs:read`,
  `evidence:read`, `reports` si aplica) o hacer los permisos de la key configurables al crearla.

---

# Resumen final

## Veredicto

El stack completo **levanta y funciona end-to-end en Docker**, pero NO out-of-the-box:
se necesitaron 3 fixes bloqueantes (F-02, F-03, F-04) para llegar a un primer arranque sano.
Con esos fixes aplicados, todo el ciclo funcional está verificado.

## Qué quedó verificado OK en el espejo

| Área | Resultado |
|---|---|
| Migraciones Alembic (7 revisiones) + bootstrap admin | OK |
| Init Qdrant (6 colecciones) | OK |
| MCP Gateway: pack fortinet/fortigate, 4 devices, 2546→2182 tools safety-filtered | OK |
| Indexación tool_catalog: 2182 puntos, clasificación LLM 146 batches (~30 min primer boot) | OK |
| Seeding: register-tenant, seed-context v1.1.0, create-tenant-key (desde host, ver F-01) | OK |
| Gateway admin API: health, auth (401), packs, CRUD devices, hot-reload (4→5→4 devices) | OK |
| Inventory sync app↔gateway: create→synced+reload, token cifrado no persistido app-side, detach→delete en gateway, delete→cascade | OK (con tenant explícito; ver F-09) |
| Tests: gateway 19/19; sync inventario 5/5 (como script, ver F-08) | OK |
| E2E ticket vía API: Engineer completó con datos REALES de los FortiGates (12 tool calls, 12 evidencias, 4 hipótesis, needs_human, reporte coherente) | OK |
| Evidencia: 12 puntos Qdrant + 12 archivos en volumen, namespaced por tenant | OK |
| Frontend: build (tras F-02), login JWT vía proxy nginx, listado de tickets | OK |

## Findings por severidad

- **BLOCKER**: F-02 (frontend no compila), F-03 (healthcheck Qdrant con wget), F-04 (CRLF en entrypoint.sh)
- **BUG**: F-05 (indexación bloquea /health en primer boot), F-09 (platform admin sin tenant → 500 + huérfano en gateway), F-11 (API keys no pueden leer runs)
- **DOC**: F-01 (seeding vía exec imposible por .dockerignore), F-10 (quickstart describe login por API key)
- **MINOR**: F-06 (CLI carga 2182 tools para comandos ops), F-07 (scopes duplicados al re-seedear), F-08 (test_ no compatible con pytest)

## Estado del entorno espejo

- 5 contenedores healthy: postgres, qdrant, mcp-gateway (:8001), app (:8000), frontend (:3001).
- `.env` reescrito para stack local (backup del anterior en `.env.remote.bak`; apuntaba a 100.113.47.96).
- Credenciales generadas: ver comentarios al final de `.env` (API key tenant + admin bootstrap).
- Fixes locales aplicados en el espejo (pendientes de replicar en el root):
  `frontend/src/pages/inventory/ComponentModal.tsx` (F-02), `docker-compose.yml` healthcheck qdrant (F-03),
  `scripts/entrypoint.sh` a LF (F-04).

