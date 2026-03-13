# Review técnico — Framework multiagente para atención de tickets (Tool Selection & Orchestration)

**Fecha:** 2026-03-01  
**Alcance:** análisis de arquitectura y mejoras recomendadas para el subsistema de selección/encadenamiento de herramientas (tools) en un framework multiagente orientado a diagnóstico, troubleshooting, validación de configuración, estado de implementaciones y planificación de cambios.

---

## 1) Contexto y objetivo del framework

El framework busca resolver tickets mediante un ciclo iterativo:
- entender el ticket + contexto del cliente,
- recolectar evidencia con tools,
- generar y validar hipótesis,
- decidir si falta evidencia, si se puede planificar, o si requiere escalamiento,
- producir una respuesta final y/o un plan.

El problema observado se concentra en el **sistema de selección de tools y armado de argumentos (args)**, que hoy no logra razonar de forma confiable del estilo:
> “Tengo la hipótesis X → necesito evidencia Y → dispongo de tools A/B/C → se invocan con parámetros P → ejecuto en orden y encadeno outputs”.

---

## 2) Diagnóstico ejecutivo (alto nivel)

### Hallazgos principales (síntesis)
1) **No existe un “Tool Contract” operativo** (inputs/outputs semánticos + propósito/capability).  
   El sistema conoce “cómo llamar” (JSON Schema), pero no “para qué sirve” y “qué produce”, por lo que no puede encadenar herramientas de forma determinística.

2) **Selección duplicada e inconsistente**: hay al menos dos estrategias distintas de selección (multi-tool vs single-tool), lo que genera comportamientos divergentes y ciclos de evidencia incompletos.

3) **Arg binding insuficiente**: la construcción de args depende demasiado de LLM o de placeholders (ej. `""`), sin un binder determinístico que resuelva `required`, alias, y faltantes (“missing inputs”).

4) **Recovery incompleto**: ante dependencias faltantes, se ejecutan tools de resolución pero no se cierra el loop reintentando el tool original con los inputs ya resueltos.

5) **Modelo de facts no robusto**: los facts se pisan entre evidencias y carecen de segmentación por componente/herramienta, lo cual complica binding, scoring y verificación.

---

## 3) Problemas de diseño detectados (qué se detecta y por qué importa)

### 3.1 Falta de un `Tool Contract` (capabilities + inputs/outputs)
**Situación actual:** el catálogo/tool registry se usa principalmente con `args_schema` (JSON Schema).  
**Impacto:** el orquestador no puede:
- determinar qué tool corresponde a una necesidad de evidencia (capability),
- rankear tools por “utilidad” para la hipótesis,
- encadenar outputs de una tool como inputs de otra de forma segura.

**Recomendación:** incorporar metadatos de contrato por tool:
- `capability` (ej. `route_lookup`, `policy_lookup`, `nat_lookup`, `interface_status`, `logs_query`, etc.)
- `domain` (ej. `network`, `firewall`, `auth`, `endpoint`, etc.)
- `read_only` / `intrusive`
- `inputs_required` semánticos (no solo schema)
- `outputs` semánticos
- 1–2 `examples` reales de invocación (args) y output normalizado

> Resultado esperado: habilita filtrado determinístico + encadenamiento por outputs + reducción del uso “creativo” del LLM.

---

### 3.2 Selección de tools duplicada (multi-tool vs single-tool)
**Situación actual:** un componente del pipeline puede ejecutar múltiples tools, mientras otro fuerza 1 tool por iteración.  
**Impacto:** diagnósticos comunes (routing/policy/NAT/VRF) requieren “bundles” de verificación; si se fuerza una sola tool se pierde cobertura y se alargan iteraciones.

**Recomendación:** unificar la lógica de selección en un único broker (ver sección 4).

---

### 3.3 Arg binding débil (dependencia excesiva de LLM)
**Situación actual:** en flujos relacionales se inicializan args como `""` para todas las properties o se delega la construcción al LLM leyendo un schema ruidoso.  
**Impacto:** fallos por `required` no satisfechos, valores inventados, o invocaciones incompletas.

**Recomendación:** binder determinístico:
- respeta `required` del schema,
- soporta aliases (ej. `mgmt_ip` vs `ip` vs `address`),
- no rellena con `""`,
- devuelve `missing_inputs[]` estructurados.

---

### 3.4 Recovery sin “retry” del tool bloqueado
**Situación actual:** se ejecuta discovery/resolution cuando falta un input, pero no se reintenta el tool original.  
**Impacto:** se acumula evidencia pero no progresa la verificación de la hipótesis.

**Recomendación:** recovery loop correcto:
1) detectar `missing_inputs`,
2) ejecutar discovery tools mapeados a esos faltantes,
3) extraer el dato (idealmente JSON normalizado),
4) rebind,
5) retry 1 vez el tool original en la misma iteración.

---

### 3.5 Facts sin partición (pisado de keys)
**Situación actual:** facts globales se pisan (ej. `status`, `routes`, `interfaces`).  
**Impacto:** el sistema pierde contexto por componente y la verificación se vuelve no determinística.

**Recomendación:** facts estructurados:
- `facts.by_component[component_id]`
- `facts.by_tool[tool_name] = [runs...]`
- `facts.index` para valores globales agregados

---

### 3.6 Riesgo de multitenancy/concurrencia
**Situación actual:** estado de customer/tenant manejado con variables globales.  
**Impacto:** en concurrencia se puede seleccionar tools del tenant equivocado o mezclar contexto.

**Recomendación:** hacer tenant/customer explícito en todas las funciones del broker y en la capa de retrieval.

---

## 4) Mejoras recomendadas (arquitectura objetivo)

### 4.1 Introducir un `ToolBroker` único (Filter → Bind → Execute)
**Objetivo:** que todo el framework (evidence + investigation) use la misma lógica.

**Fases:**
1) **Requirement extraction (LLM, output estructurado)**
   - Entrada: hipótesis + scoring.missing_facts + path breakpoints
   - Salida: `requirements[]` tipados (capability + scope)
2) **Tool matching (determinístico)**
   - Match por `capability`/`domain`/`vendor`/`read_only`
   - Vector search solo como fallback
3) **Arg binding (determinístico)**
   - Resuelve args desde un `VarPool`
   - Si faltan inputs → agenda discovery tools
4) **Execute (DAG)**
   - Ejecuta discovery primero, luego verification
   - Normaliza outputs a facts y actualiza VarPool

---

### 4.2 Catalog/Registry: normalización mínima requerida
**Datos mínimos por tool** (además del schema):
- `tool_name`, `version`
- `capability`, `domain`, `vendor` (si aplica)
- `read_only`, `intrusive`
- `inputs_required` (semántico)
- `outputs` (semántico)
- `examples[]` (args + output esperado normalizado)

**Nota:** si no se quiere rediseñar el storage, estos campos pueden agregarse como metadata en el vector store / índice existente.

---

### 4.3 VarPool (fuente única de verdad para binding)
**Construcción:**
- inventory + component metadata
- facts por componente
- outputs recientes por tool
- valores inferidos (con control de origen)

**Reglas:**
- preferir datos “firmes” (inventory/outputs tool) sobre inferencias LLM
- rastrear `provenance` (de dónde salió cada valor), útil para auditoría

---

### 4.4 JSON-output enforcement
Para cualquier paso que se parsea como JSON (intents, tool selection, requirements), forzar:
- `response_format` JSON (o JSON Schema si disponible)
- `safe_json_load()` único (fallback controlado)

---

## 5) Fixes específicos (cambios concretos y acotados)

### 5.1 Eliminar placeholders `""` en args
- No inicializar args con strings vacíos.
- Bind solo si existe el valor real en VarPool o se puede derivar de manera determinística.

---

### 5.2 `missing_inputs → discovery_capability` (tabla determinística)
Construir un mapa:
- `mgmt_ip` → `device_identity_lookup`
- `vdom` → `device_vdom_list`
- `dst_cidr` → `ticket_entity_extract` (o parser determinístico)
- `interface` → `interface_list` / `route_lookup` (según caso)

Esto reemplaza el “LLM decide discovery tool” por una tabla segura y operable.

---

### 5.3 Recovery: reintento del tool original
Implementar: `execute_with_recovery(tool, args)`:
- si faltan inputs → ejecutar discovery plan → rebind → retry 1 vez
- si falla por HTTP/permission → registrar failure evidence y avanzar

---

### 5.4 Facts particionados por componente
Migración incremental:
- mantener `facts.global` (legacy)
- empezar a poblar `facts.by_component` y `facts.by_tool`
- binder solo usa `by_component` + inventory como prioridad

---

### 5.5 Unificar “multi-tool” y “single-tool”
- Investigator deja de elegir 1 tool.
- El broker devuelve un **bundle mínimo** por capability (ej. routing: route+interface+policy).
- Aplicar budgets (ver 5.6).

---

### 5.6 Budget y ranking operativo
Para controlar “1 o cientos”:
- `max_calls_per_iteration` (ej. 20)
- `max_calls_per_component` (ej. 5)
- `max_calls_per_capability` (ej. 3)
- scoring/ranking:
  - + match exacto capability
  - + required inputs ya disponibles
  - - tool lenta/expensive
  - - output no estructurado

---

### 5.7 Multitenancy: eliminar estado global
- pasar `customer_id`/tenant en cada llamada del broker y del tool retrieval
- evitar variables globales de tenant

---

## 6) Roadmap de implementación (pragmático)

### Fase 0 — “Stabilization” (rápida, bajo riesgo)
- Forzar JSON output en prompts parseados
- Eliminar args `""`
- Implementar binder determinístico con aliases + required
- Implementar `missing_inputs` + discovery table
- Agregar retry del tool original post-discovery
- Fix multitenancy (sin globals)

### Fase 1 — “Operability” (mejoras estructurales)
- Estructurar `facts.by_component` y `facts.by_tool`
- VarPool con prioridad por fuente (inventory/tool outputs)
- Budgets + ranking por disponibilidad de inputs

### Fase 2 — “Capability-driven orchestration”
- Agregar `capability/domain/outputs` al catálogo
- Tool matching determinístico por capability (vector fallback)
- Bundles mínimos por breakpoint/path analysis

---

## 7) Riesgos y trade-offs (breve)

- **Mayor inversión inicial en catalog metadata**: se compensa con menos fallos de ejecución y menos iteraciones.
- **Menos “libertad” del LLM**: se gana repetibilidad, auditabilidad y control de costos.
- **Normalización de outputs**: si las tools actuales devuelven texto, conviene migrarlas a JSON normalizado para cerrar encadenamientos.

---

## 8) Resultado esperado tras aplicar mejoras

- Selección de tools reproducible y explicable (por capability + inputs disponibles).
- Menos llamadas fallidas por args inválidos.
- Encadenamiento real: outputs → facts → VarPool → siguientes tools.
- Menos iteraciones por ticket y mejor coverage en troubleshooting.
- Menos riesgo de contaminación entre clientes/tenants.

---
