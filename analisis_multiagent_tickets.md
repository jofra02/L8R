# Análisis del framework multiagente para atención de tickets (diagnóstico/troubleshooting/validación)

## Premisa (contexto del problema)
Tenés un multiagent orientado a tickets: diagnóstico, troubleshooting, validación de configuraciones, estado de implementaciones y planificación de cambios.

Caso típico:
> “Revisa si la subred `192.168.241.0/24` llega hasta la subred `100.64.120.0/27`. Los devices son `fgt_casa` y `fgt_druidics`. Además, si podés corroborar policies relacionadas con el tráfico entre estas redes.”

Observación:
- Si le das ese ticket directo a un LLM (ej. `gpt-5-2`) + MCP tools, suele “auto-orquestarse” bien: busca rutas, detecta cuáles FWs participan, hace `policy lookup`, revisa routing table, etc.
- Si le das el mismo ticket al multiagent, te devuelve un reporte conservador/inconcluso (“no se puede confirmar”, “faltan rutas/policies”, “no hay evidencia de selectors”, etc.), aun cuando el LLM solo sí lo resuelve.

Objetivo de este documento:
1) Iterar los módulos/agentes y mapear cómo funcionan.
2) Identificar el/los problemas más probables que rompen el “flujo natural”.
3) Proponer fixes mínimos para que el multiagent se comporte como el LLM “solo” pero de forma estable y controlada.

---

## 1) Mapa del pipeline: agentes/módulos y responsabilidades

### 1. Context loading / Topology seed
- **context_agent**  
  Carga `ClientContext` (inventory, baselines, dependencies) para el `customer_id`. Además “siembra” un grafo (topología: nodes/edges) a partir de inventory/dependencies.

### 2. Ticket classification
- **classifier**  
  Clasifica el ticket (dominios, confianza, rationale).

### 3. Entity extraction / Reconciliation
- **mapper**  
  Extrae componentes del texto (devices, IPs, subnets, servicios) y los reconcilia con el inventory (normalización + matching).

### 4. Evidence acquisition (tools)
- **evidence_collector**  
  Por cada *component*:
  - El LLM genera *tool-search intents*
  - Busca tools en vector search (ej. Qdrant)
  - El LLM elige tools y arma args
  - Ejecuta con `AdaptiveExecutor`
  - Guarda evidence snapshots y hace recovery si faltan dependencias

### 5. Evidence → facts + topology enrichment
- **enricher**  
  Toma evidence snapshots nuevos, los comprime, extrae **facts** (structured JSON) y también nodos/aristas de topología. Deduplica y marca evidence como procesada.

### 6. Hypotheses generation
- **hypothesis**  
  Con ticket + facts + topología + baselines/cambios, genera hipótesis rankeadas. Además intenta `path_analysis` (candidate paths, breakpoints, suggested probes).

### 7. Targeted verification
- **investigator**  
  Elige 1 hipótesis activa (prioriza `verifying`) y ejecuta 1 tool “mejor” para verificarla. Guarda evidence y setea estado de hipótesis.

### 8. Scoring / decision
- **scoring**  
  Calcula `confidence`, `evidence_coverage`, `risk_score` y decide: `proceed_to_plan` / `needs_more_evidence` / `escalate_to_human`.

### 9. Plan generation
- **planner**  
  Arma plan (diagnosis/proposed changes/validation/rollback) usando hipótesis activa + CBR (casos similares).

### 10. Final response / HITL
- **response**  
  Si hay `pending_requirements`, entra en modo pausa/HITL (needs + checkpoint). Si no, sintetiza reporte final desde facts/evidence/hypotheses/plan.

### 11. Orchestration
- **supervisor + router**  
  Lleva el loop por iteraciones y decide el próximo nodo según estado/scoring.

---

## 2) Dónde está el inconveniente (por qué “no fluye”)

### A) Problema de routing/orquestación: el loop “inteligente” puede estar incompleto
Síntoma:
- El sistema recolecta evidencia, pero no entra consistentemente en el ciclo:
  `evidence → enricher → hypothesis → scoring → (investigator / más evidence)`.

Riesgo:
- Si el router tiene un fallback que, con `evidence_refs` ya presentes, manda directo a `planner`/`response`,
  el pipeline termina siendo: “muestreo amplio” → “reporte conservador”.

Efecto práctico:
- Se obtienen outputs como:
  - “No vi policy explícita con match exacto”
  - “No vi ruta explícita hacia X”
  - “No hay evidencia de Phase2 selectors”
  sin haber ejecutado probes determinísticos que cierran la verificación.

---

### B) Guardrails anti-hallucination bloquean los tools que “cierran” reachability
En tu diseño hay reglas explícitas tipo:
- “Si un tool requiere parámetros mandatory y faltan, no inventar y skip”.

En reachability:
- Muchos `policy-lookup`/`route-lookup` requieren **IPs concretas** (src/dst host), no solo prefijos CIDR.

Si el ticket trae solo subnets:
- El multiagent tiende a NO elegir un host representativo y entonces:
  - evita `policy-lookup`/lookup preciso
  - cae a “list policies / list routes”
  - concluye: “no se puede confirmar”.

El LLM “solo” suele hacer lo contrario:
- elige un host típico (`.1`) o un IP dentro del rango para poder correr los lookups.

---

### C) Evidence collection “por componente” no modela bien problemas relacionales
Reachability no es una entidad suelta; es una relación:
- `(src_device, dst_device, src_subnet, dst_subnet, transport)`.

Si el collector recorre por component suelto:
- termina disparando toolsets genéricos:
  - “list firewall policies” (ancho)
  - “get routing table” (ancho)
- y después depende de que el summary o el enricher detecten justo el match exacto.

Resultado:
- Mucho “no vi X en un muestreo” incluso cuando X existe pero:
  - está como address object/group (no literal CIDR en policy listing)
  - está en rutas agregadas/sumarizadas
  - requiere lookup, no listing.

---

### D) Footgun de inyección de argumentos (placeholder → valor inválido)
Si el LLM deja placeholders para args de tool (ej. `subnet`, `destination`, etc.)
y el injector los rellena con `comp.id` por defecto, podés terminar con llamadas inválidas tipo:
- `subnet="fgt_casa"` (cuando debería ser `192.168.241.0/24`)

Aunque no siempre explote, degrada evidence y lleva a conclusiones “no confirmadas”.

---

### E) UX del reporte final: inferencias probabilísticas en validaciones
En tickets de VALIDATION/INQUIRY:
- Si falta evidencia, el reporte debería decir “Not confirmed” + “Qué falta para confirmar”.

Si el generador de respuesta permite frases tipo:
- “probablemente inexistente”
- “probablemente faltan rutas/policies”
terminás con un output más editorial que operativo.

---

## 3) Fix mínimo para que el multiagent “se comporte como el LLM solo”

### 1) Arreglar el loop (routing) de forma determinística
Regla sugerida (alto nivel):
- Si hay evidence nuevo sin procesar → **enricher**
- Si facts/topology cambió o no hay hipótesis → **hypothesis**
- Si no hay scoring actualizado → **scoring**
- Si scoring = `needs_more_evidence` → **investigator** (o collector con probes guiados)
- Si scoring = `proceed_to_plan` → **planner** → **response**

Esto fuerza el ciclo “cierra-hipótesis-cierra-decisión”.

---

### 2) Derivar “representative IPs” desde CIDR (sin LLM)
Para tools que requieren host IP, derivá una convención determinística:
- `probe_ip = network_address + 1` (ej. `192.168.241.1`, `100.64.120.1`)
- Validá que no sea network/broadcast y que el prefijo lo permita.

Esto NO es “inventar”: es una estrategia operativa repetible para habilitar lookups.

---

### 3) Playbook fijo para FortiGate reachability (read-only)
En vez de depender 100% del semantic tool picking para este caso, creá un playbook de verificación:

En ambos FGT (o el/los relevantes según topología):
- `route lookup` para `dst_probe_ip` desde `src_device`
- `policy lookup` para `src_probe_ip → dst_probe_ip`
- búsqueda de policies por:
  - srcaddr/dstaddr objects que contengan el CIDR
  - addrgrp membership
- verificación de transporte inter-site:
  - IPsec Phase2 selectors
  - SD-WAN rules / routes (si aplica)
- NAT check (si aplica)

Output del playbook:
- `can_route` (ida/vuelta)
- `can_policy_match` (ida/vuelta)
- `transport_ok` (si aplica)
- `missing_items` (exacto, accionable)

---

### 4) Endurecer el estilo del reporte en VALIDATION
Cambios:
- Prohibir “probablemente” cuando no hay evidencia concluyente.
- Formato:
  - **Status**: Confirmed / Not confirmed / Inconclusive
  - **Evidence**: links/refs a outputs concretos
  - **Next probes**: 3–6 acciones exactas (tools + args)

---

## 4) Diagnóstico resumido (en una línea)
El multiagent está fallando por una combinación de **routing incompleto** + **evidence acquisition poco relacional** + **guardrails que impiden usar lookups cuando faltan IPs concretas**, lo que lo empuja a listados anchos y conclusiones conservadoras.

