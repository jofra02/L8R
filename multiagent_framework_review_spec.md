# Especificación conceptual para revisión del framework multiagente IT

## Objetivo de este documento

Este documento define **cómo debería comportarse conceptualmente** el framework multiagente para atención de tickets IT.  
La tarea del agente revisor/desarrollador no es asumir que esto ya se cumple, sino **investigar el código y el flujo actual** para validar:

1. si esta arquitectura lógica existe realmente,
2. si las responsabilidades entre agentes están bien separadas,
3. si el loop de investigación y resolución funciona de esta manera,
4. y, si no se cumple, qué cambios concretos hay que hacer.

---

## Premisa general

El framework atiende tickets IT de distinta índole, por ejemplo:

- troubleshooting / incident investigation,
- validación de configuraciones,
- análisis de estado actual,
- fulfillment de requerimientos,
- planificación de cambios,
- respuesta a consultas técnicas.

Supuesto recomendado: el framework opera en modo **read-only / no-op por defecto**.  
Debe investigar, razonar, recolectar evidencia, diagnosticar y/o detectar issues pero **no ejecutar cambios reales**.

---

## Problema conceptual a resolver

El problema principal no parece ser “falta de agentes”, sino **falta de una lógica de flujo clara**, con:

- estado compartido estructurado,
- responsabilidades bien separadas,
- selección de herramientas basada en capacidades,
- evidencia normalizada,
- y un loop explícito de investigación → síntesis → replanificación o resolución.

El framework no debería depender de que “un agente inteligente haga todo”, sino de una arquitectura donde el razonamiento esté guiado por estado y contratos de datos.

---

# Arquitectura lógica esperada

## Vista general

El flujo correcto no debería ser lineal del tipo:

```text
Ticket -> hipótesis -> tools -> respuesta
```

Sino un loop controlado:

```text
Ticket -> modelado -> plan -> investigar -> sintetizar -> replanificar si hace falta -> resolver
```

---

## Diagrama ASCII de alto nivel

```text
+------------------+
| 1. Ticket Intake |
| / Triage         |
+--------+---------+
         |
         v
+---------------------------+
| 2. Problem Modeler        |
| - classify ticket         |
| - extract entities        |
| - define success criteria |
| - build hypotheses/goal   |
+-------------+-------------+
              |
              v
+---------------------------+
| 3. Planner                |
| - open questions          |
| - evidence needed         |
| - task ordering           |
| - stop conditions         |
+-------------+-------------+
              |
              v
+---------------------------+
| 4. Investigator           |
| / Evidence Collector      |
| - pick next question      |
| - derive info needs       |
+-------------+-------------+
              |
              v
+---------------------------+
| 5. Tool Selector/Broker   |
| - match capabilities      |
| - resolve params          |
| - choose 1..N tools       |
+-------------+-------------+
              |
              v
+---------------------------+
| 6. Tool Execution         |
| - execute tools           |
| - collect raw evidence    |
| - normalize observations  |
+-------------+-------------+
              |
              v
+---------------------------+
| 7. Synthesizer            |
| / Case Updater            |
| - update case file        |
| - score hypotheses        |
| - detect gaps/conflicts   |
+------+------+-------------+
       |      |
       |      +-----------------------------+
       |                                    |
       v                                    |
+---------------------------+               |
| 8. Resolver               |               |
| - answer / diagnosis      |               |
| - rationale               |               |
| - recommended actions     |               |
+---------------------------+               |
                                            |
                if confidence low / unknowns remain
                                            |
                                            v
                                   +------------------+
                                   | Replan / Loop    |
                                   +------------------+
```

---

# Qué debe hacer cada etapa

## 1. Ticket Intake / Triage

Debe:

- entender el problema o requerimiento,
- clasificar el ticket,
- extraer objetivo, entidades, restricciones y criterios de éxito.

Tipos mínimos sugeridos:

- `incident/troubleshooting`
- `request/fulfillment`
- `change/planning`
- `question/information`

No debería:

- ejecutar tools,
- resolver el ticket,
- mezclar clasificación con investigación profunda.

---

## 2. Problem Modeler

Debe convertir el ticket en un problema estructurado.

### Si el ticket es troubleshooting
Debe producir:

- hipótesis iniciales,
- facts conocidos,
- unknowns,
- success criteria.

### Si el ticket es request / fulfillment
Debe producir:

- goal principal,
- subtareas lógicas,
- gaps de información necesarios para cumplir el requerimiento.

No debería:

- correr herramientas,
- seleccionar comandos concretos,
- saltear la estructuración del caso.

---

## 3. Planner

Este componente es crítico.

Su responsabilidad no es investigar directamente, sino generar un **plan de investigación**.

Debe producir:

- `open_questions`,
- `evidence_requirements`,
- dependencias entre preguntas,
- orden de investigación,
- criterios de corte.

### Qué significa “planificar” realmente

No es una lista vaga de pasos.  
Debe generar algo más cercano a un **Investigation Graph**.

Ejemplo:

```text
Goal:
"Validar si red A llega a red B y si existe policy que lo permita"

Open Questions:
Q1. ¿Dónde vive la red A? ¿en qué device/interface/VRF/VDOM?
Q2. ¿Dónde vive la red B?
Q3. ¿Existe route desde A hacia B?
Q4. ¿Existe route de retorno desde B hacia A?
Q5. ¿Hay NAT involucrado?
Q6. ¿Hay security policy permitiendo ese flujo?
Q7. ¿Hay indicios de deny / shadow rule / asymmetric path?

Dependencies:
Q3 depende de resolver Q1 y Q2
Q4 depende de resolver Q1 y Q2
Q6 depende de Q1, Q2 y puertos/protocolo si aplican
```

No debería:

- ejecutar tools,
- parsear outputs crudos complejos,
- producir conclusiones finales.

---

## 4. Investigator / Evidence Collector

Toma una `open_question` y la transforma en necesidades de información concretas.

Ejemplo conceptual:

- Si la hipótesis es “no existe route desde la red A hacia la red B”,
- el investigador debe derivar que necesita:
  - localizar ambas redes,
  - saber qué devices participan,
  - inspeccionar rutas efectivas,
  - validar retorno,
  - revisar si hay policy y NAT.

Otro ejemplo no de red:

- Si se necesita inferir idioma o nacionalidad,
- el investigador debe derivar qué evidencia válida puede usar:
  - audio,
  - documentación,
  - metadata,
  - fuentes internas,
  - correlaciones cruzadas.

No debería:

- elegir tools “porque parecen útiles” sin criterio,
- emitir resolución final del caso por su cuenta,
- saltear el paso de síntesis.

---

## 5. Tool Selector / Tool Broker

Este componente no debería elegir herramientas por intuición o memoria libre.

Debe hacer matching entre:

- `qué necesito averiguar`,
- `qué capacidades ofrece cada tool`,
- `qué parámetros puedo resolver con el contexto actual`.

### Regla clave

La selección de herramientas debe estar basada en **capabilities**, no en texto libre ni en asociaciones difusas.

Cada tool debería describirse con un contrato similar a este:

```json
{
  "tool_name": "fortigate_route_lookup",
  "capabilities": [
    "lookup_route_by_prefix",
    "lookup_routing_table",
    "resolve_interface_for_prefix"
  ],
  "required_params": ["device", "prefix"],
  "optional_params": ["vdom"],
  "produces": ["route_entry", "next_hop", "out_interface"],
  "cost": "low",
  "reliability": "high",
  "side_effect": false
}
```

El selector debe poder:

- elegir una o varias tools,
- resolver parámetros usando inventario, outputs previos y contexto del ticket,
- detectar cuando faltan parámetros,
- preferir herramientas más específicas y confiables,
- evitar tools redundantes o sin valor adicional.

No debería:

- razonar el caso entero desde cero,
- mezclar su lógica con el planner,
- depender de nombres de herramientas hardcodeados en prompts.

---

## 6. Tool Execution

Debe ejecutar las herramientas seleccionadas y devolver:

- raw output,
- observaciones normalizadas,
- provenance,
- confidence,
- errores y timeouts.

No debería retornar solo texto libre.

---

## 7. Synthesizer / Case Updater

Es quien toma la evidencia recolectada y actualiza el estado del caso.

Debe:

- actualizar facts conocidos,
- asociar evidencia a hipótesis o goals,
- confirmar o descartar hipótesis,
- detectar conflictos entre evidencias,
- decidir si alcanza para resolver o si hay que seguir investigando.

Debe poder decidir entre:

- `resolve`,
- `continue investigating`,
- `replan`,
- `block`,
- `needs_human`.

No debería:

- ejecutar tools por su cuenta sin respetar el flujo,
- producir una respuesta final sin trazabilidad.

---

## 8. Resolver

Debe producir la salida final human-readable:

- diagnóstico o respuesta,
- razonamiento resumido,
- evidencia que sustenta la conclusión,
- gaps pendientes,
- acciones recomendadas.

La salida debe estar respaldada por evidencia trazable.

---

# El framework debe tener un Case File estructurado

Si el estado viaja solo como texto libre entre agentes, el sistema deriva, duplica trabajo y pierde trazabilidad.

Se recomienda un `Case File` persistente por ticket.

Ejemplo:

```json
{
  "ticket_id": "TCK-123",
  "ticket_type": "troubleshooting",
  "goal": "Validar conectividad entre red A y red B",
  "entities": {
    "source_network": "192.168.241.0/24",
    "destination_network": "100.64.120.0/27",
    "devices": ["fgt_casa", "fgt_druidics"]
  },
  "constraints": [],
  "success_criteria": [
    "Determinar si existe path de ida y vuelta",
    "Determinar si hay policy habilitante o bloqueante"
  ],
  "known_facts": [],
  "hypotheses": [],
  "open_questions": [],
  "evidence": [],
  "status": "triaged"
}
```

---

## Hipótesis estructuradas

Ejemplo:

```json
{
  "id": "H1",
  "statement": "No existe route desde fgt_casa hacia 100.64.120.0/27",
  "confidence": 0.35,
  "supporting_evidence": [],
  "contradicting_evidence": [],
  "status": "open"
}
```

---

## Open Questions estructuradas

Ejemplo:

```json
{
  "id": "Q3",
  "question": "¿Existe route efectiva desde el origen hacia la red destino?",
  "why": "Valida H1",
  "depends_on": ["Q1", "Q2"],
  "done_when": "Se identifica route o se confirma ausencia",
  "status": "open"
}
```

---

## Observations / Evidence normalizadas

Ejemplo:

```json
{
  "id": "OBS-22",
  "question_id": "Q3",
  "source_tool": "fortigate_route_lookup",
  "input_params": {
    "device": "fgt_casa",
    "prefix": "100.64.120.0/27"
  },
  "raw_ref": "artifact://tool-runs/abc123",
  "normalized_fact": {
    "route_exists": true,
    "next_hop": "10.0.0.1",
    "out_interface": "port3"
  },
  "confidence": 0.92,
  "timestamp": "2026-03-12T00:00:00Z"
}
```

---

# Estado y loop operativo esperado

## State machine sugerida

```text
NEW
 -> TRIAGED
 -> MODELED
 -> PLANNED
 -> INVESTIGATING
 -> SYNTHESIZING
 -> RESOLVED | BLOCKED | NEEDS_HUMAN | REPLAN
```

## Loop operativo

```text
while not resolved:
    1. tomar próxima open_question prioritaria
    2. derivar qué evidence hace falta
    3. seleccionar tools compatibles
    4. ejecutar tools
    5. normalizar observations
    6. actualizar case file
    7. recalcular hipótesis / fulfillment status
    8. decidir:
       - resolve
       - next question
       - replan
       - block
```

Este loop debe estar implementado explícitamente o, como mínimo, reflejado claramente en el diseño.

---

# Dos modos de operación que deben existir

## A. Troubleshooting

Cuando el ticket describe un problema o falla:

- generar hipótesis,
- buscar evidencia para validarlas o descartarlas,
- converger hacia la causa probable o el bloqueo real.

## B. Fulfillment / Request

Cuando el ticket pide cumplir un requerimiento:

- no inventar hipótesis innecesarias,
- transformar el requerimiento en goals y subtareas,
- investigar solo la información faltante necesaria para cumplirlo.

Esta distinción es importante porque muchos frameworks fallan al tratar todo como troubleshooting.

---

# Ejemplo conceptual aplicado

## Ticket

“Validar si desde la red A puedo llegar a la red B y revisar policies relacionadas”

## Problem Model

- tipo: `troubleshooting`
- goal: validar reachability + policy path
- entities:
  - src subnet,
  - dst subnet,
  - candidate devices
- success criteria:
  - saber si el path existe,
  - saber si hay policy permitiva o bloqueante.

## Hipótesis iniciales

- H1: no existe route de ida.
- H2: no existe route de vuelta.
- H3: existe route pero falta policy.
- H4: existe policy pero un objeto/address group no matchea.
- H5: existe NAT o asymmetry que rompe el flujo.

## Plan

Preguntas:

- ¿Dónde está src?
- ¿Dónde está dst?
- ¿Qué devices participan?
- ¿Hay routing ida/vuelta?
- ¿Hay policy matching?
- ¿Hay NAT o central SNAT?
- ¿Hay logs de deny?

## Investigación

Para Q1/Q2:

- inventory lookup,
- subnet ownership lookup,
- interface mapping.

Para Q3/Q4:

- route lookup,
- routing table inspection,
- policy route lookup.

Para Q5:

- security policy lookup,
- address object expansion,
- service object lookup.

## Síntesis esperada

Ejemplo de salida del razonamiento:

- route ida: sí,
- route vuelta: sí,
- policy: no matchea porque dst address object excluye la subred real,
- resultado: la conectividad no está garantizada por falta de policy efectiva.

El framework debería poder llegar a una conclusión similar siguiendo el loop y apoyándose en evidencia.

---

# Fallos de arquitectura que el agente revisor debe buscar

## 1. Ausencia de Case File estructurado

Señales de problema:

- el estado se pasa solo como texto libre,
- cada agente reinterpreta todo de nuevo,
- no hay persistencia de facts, hipótesis, preguntas y evidencia.

## 2. Hipótesis implícitas o inexistentes

Señales de problema:

- el sistema investiga “por intuición”,
- no queda claro qué está intentando validar o descartar,
- no se puede explicar por qué se consultó determinada tool.

## 3. Planner débil o inexistente

Señales de problema:

- el planner se limita a decir “investigar más”,
- no produce open questions ni dependencias,
- ejecuta tools directamente o se mezcla con Investigator.

## 4. Tool selection deficiente

Señales de problema:

- se eligen herramientas por nombre o recuerdo del modelo,
- no existe catálogo de capacidades,
- el binding de parámetros es frágil o improvisado,
- no se manejan faltantes de contexto.

## 5. Evidence normalization ausente

Señales de problema:

- cada tool devuelve un formato distinto y nadie lo unifica,
- el razonamiento consume raw output desordenado,
- no hay confidence, provenance ni trazabilidad.

## 6. Mezcla de responsabilidades entre agentes

Señales de problema:

- el mismo agente clasifica, planifica, investiga, selecciona tools y resuelve,
- los agentes tienen solapamientos que generan decisiones inconsistentes,
- el flujo depende demasiado de prompts narrativos.

## 7. Falta de criterios de corte

Señales de problema:

- loops infinitos,
- sobreinvestigación sin valor,
- resolución prematura sin evidencia suficiente.

## 8. No diferenciación entre troubleshooting y fulfillment

Señales de problema:

- todo se trata como hipótesis técnicas,
- los tickets de requerimientos simples se complejizan innecesariamente,
- no existe path específico para cumplir solicitudes.

---

# Diseño mínimo de agentes recomendado

No hace falta multiplicar agentes sin control. Una segmentación razonable sería:

1. `TriageAgent`
   - Entrada: ticket.
   - Salida: `Case File` base.

2. `ReasoningAgent`
   - Entrada: `Case File`.
   - Salida: hipótesis o fulfillment goals + open questions iniciales.

3. `PlanningAgent`
   - Entrada: `Case File`.
   - Salida: `Investigation Plan`.

4. `InvestigationAgent`
   - Entrada: una `open_question`.
   - Salida: `Evidence Requests`.

5. `ToolBrokerAgent`
   - Entrada: `Evidence Request`.
   - Salida: tool choice + param binding + execution plan.

6. `SynthesisAgent`
   - Entrada: observations acumuladas.
   - Salida: case actualizado + decisión de loop.

7. `ResolutionAgent`
   - Entrada: case final.
   - Salida: respuesta final human-readable.

---

# Qué debería revisar concretamente el agente que lea este documento

El objetivo de la revisión es validar si el framework actual **se comporta conceptualmente de esta manera**.

Debe inspeccionar:

- cómo se representa el estado del ticket,
- cómo se clasifican los tickets,
- cómo se generan hipótesis o goals,
- cómo se arma el plan,
- cómo se define qué investigar,
- cómo se seleccionan tools,
- cómo se hace param binding,
- cómo se almacenan evidencias,
- cómo se sintetizan conclusiones,
- cómo se decide continuar, replanificar o resolver.

Debe responder, al menos, estas preguntas:

1. ¿Existe un `Case File` estructurado o equivalente?
2. ¿Las hipótesis y open questions están explicitadas?
3. ¿El Planner produce un plan real o solo pasos vagos?
4. ¿Tool selection está basado en capabilities?
5. ¿La evidencia está normalizada?
6. ¿Hay provenance y confidence por observación?
7. ¿Existe un loop explícito de investigación y síntesis?
8. ¿Hay stop conditions claras?
9. ¿El framework separa troubleshooting de fulfillment?
10. ¿La salida final está respaldada por evidencia trazable?

---

# Entregable esperado de esa revisión

El agente revisor debería devolver algo como esto:

## 1. Mapa actual del framework

- agentes/componentes actuales,
- responsabilidades reales observadas,
- flujo actual real,
- puntos donde se rompe la lógica.

## 2. Gap analysis contra esta especificación

Para cada bloque:

- lo cumple,
- lo cumple parcialmente,
- no lo cumple.

## 3. Findings técnicos

Ejemplos:

- responsabilidades mezcladas,
- ausencia de state machine,
- planner no funcional,
- tool selection frágil,
- evidencia sin normalización,
- falta de trazabilidad,
- loops mal controlados.

## 4. Refactor propuesto

Con cambios concretos, por ejemplo:

- introducir `Case File`,
- definir schema de `Hypothesis`, `OpenQuestion`, `Observation`,
- desacoplar Planner de Investigator,
- crear catálogo de capabilities para tools,
- implementar `SynthesisAgent` explícito,
- agregar state machine y stop conditions.

---

# Instrucción lista para pasarle al otro agente

```text
Necesito que revises el framework multiagent a alto nivel y valides si su comportamiento respeta esta arquitectura lógica:

1. El sistema debe tener un Case File estructurado persistente por ticket.
2. Debe separar claramente:
   - ticket intake / triage
   - problem modeling / hypothesis building
   - planning
   - investigation / evidence collection
   - tool selection
   - tool execution
   - synthesis
   - resolution
3. El Planner no debe ejecutar tools: debe producir open questions, evidence requirements, dependencies y stop conditions.
4. El Investigator debe tomar una open question y derivar qué información necesita para validarla o descartarla.
5. Tool selection debe hacerse por capability matching, no por texto libre o intuición.
6. Toda tool execution debe devolver raw output + normalized observation + provenance + confidence.
7. El sistema debe operar en loop:
   model -> plan -> investigate -> synthesize -> replan/resolve
8. Debe haber criterios de corte claros para evitar loops infinitos.
9. Debe soportar dos modos:
   - troubleshooting basado en hypotheses
   - fulfillment/request basado en goals y information gaps
10. La salida final debe estar sustentada por evidencia trazable.

Revisá si el código actual cumple esto. Marcá:
- acoplamientos incorrectos entre agentes
- responsabilidades mezcladas
- falta de state machine
- ausencia de case file estructurado
- selección de tools deficiente
- ausencia de evidence normalization
- falta de stop conditions
- propuestas concretas de refactor
```

---

# Resumen final

La arquitectura deseada puede resumirse así:

```text
Ticket
  -> Case modeling
  -> Hypotheses o fulfillment goals
  -> Investigation plan
  -> Open question
  -> Evidence need
  -> Tool capability match
  -> Tool execution
  -> Normalized observation
  -> Case update
  -> Resolve o replan
```

La clave no es tener más agentes, sino tener:

- estado estructurado,
- separación real de responsabilidades,
- loop explícito,
- evidencia normalizada,
- trazabilidad,
- criterios de corte,
- y distinción entre troubleshooting y fulfillment.
