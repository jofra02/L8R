# Análisis Profundo: Comunicación, Estado y Sincronización de Agentes

He analizado a fondo el flujo, la mutación de estado (`GlobalState`) y las decisiones de enrutamiento del `Supervisor`. El sistema tiene una base sólida, pero existen **tres desconexiones arquitectónicas críticas** que explican comportamientos anómalos (como abandonar una investigación prematuramente o no solicitar ayuda al humano cuando falla el `Investigator`).

A continuación, el detalle del flujo de datos, el timing y los problemas encontrados.

## 1. Flujo de Datos y Mutación de Estado (Expected vs Actual)

| Agente | Lee de (Inputs) | Escribe en (Outputs) | Observaciones de Implementación |
| :--- | :--- | :--- | :--- |
| **Collector** | `ticket`, `components` | `evidence_refs`, `pending_requirements` | Correcto. Descubre evidencia inicial y, si falla gravemente, levanta requerimientos pendientes. |
| **Investigator** | `hypotheses`, `facts`, `evidence_refs`, `components` | `evidence_refs`, `hypotheses` (modifica a `verifying`) | **[ALERTA]** Cuando falla gravemente (MissingDependency), guarda la evidencia pero **NO** levanta `pending_requirements`. Esto rompe el HITL (Human-in-the-Loop) en etapas avanzadas. |
| **Enricher** | `evidence_refs` | `facts` | **[CRÍTICO]** Actualmente el código es un MVP: `enriched_facts[f"status_{ref.id}"] = "analyzed"`. No utiliza un LLM para extraer conclusiones reales de la evidencia al formato `facts`. |
| **Hypothesis** | `facts`, `hypotheses` | `hypotheses` | Depende absolutamente de los `facts` para cambiar una hipótesis de `verifying` a `verified`. Al estar roto el Enricher, el LLM de este agente de vez en cuando "adivina" leyendo el historial, pero la mayoría de las veces se estanca. |
| **Supervisor** | Todo el estado | `meta.iterations` (Enrutamiento) | **[BUG LÓGICO]** Su lógica asume que si no hay `verified` y no hay `proposed`, se debe pasar a planificar. Falla al no contemplar las hipótesis estancadas en `verifying`. |

---

## 2. Los Bugs de Sincronización (Timing & State Logic)

### Problema A: La Trampa del Estado "Verifying" (Supervisor Routing Bug)
El ciclo de investigación es: `Investigator` -> `Enricher` -> `Hypothesis` -> `Supervisor`.
1. `Investigator` toma una hipótesis `proposed`, corre una herramienta, y la marca como `verifying`.
2. El `Supervisor` (en `src/agents/supervisor.py` líneas 97-101) tiene esta lógica si no se han alcanzado las iteraciones máximas:
   ```python
   if not has_verified:
       if any(h.status == "proposed" for h in hypotheses):
           return "investigator_agent"
       return "planner_agent" # <-- BUGS HERE
   ```
**¿Qué pasa?** Si el `Investigator` intentó algo, y el agente de Hipótesis la dejó en `verifying` (porque faltan pruebas concluyentes), la lista de hipótesis solo tiene `verifying` y/o `rejected`. Como no hay ninguna `verified` ni `proposed`, **el Supervisor aborta la investigación y salta al `planner_agent` directamente**.
**Efecto visual:** El agente prueba un comando, falla o queda a medias, y de repente dice "Terminé, aquí está el plan", abandonando el hilo de pensamiento.

### Problema B: El Cuello de Botella del Enricher
El agente `Hypothesis` está instruido estrictamente: *"If a hypothesis is 'verifying', check the 'Facts'. If facts CONFIRM it, change status to 'verified'."*
Sin embargo, `src/agents/enricher.py` no está inyectando el contenido de las terminales en `facts` (solo hace un mock).
**Efecto visual:** El `Investigator` consigue la evidencia correcta, pero el agente de Hipótesis no se entera formalmente mediante los "Hechos", por lo que no verifica la hipótesis, dejándola en el purgatorio del estado `verifying` (lo que detona el Problema A).

### Problema C: Falta de Señal de Bloqueo en Investigator (HITL Drop)
En `evidence_collector.py`, si el `AdaptiveExecutor` arroja `MissingDependencyError` y la auto-recuperación falla, se añade el objeto a `pending_requirements`. El `ResponseAgent` lee este array y pausa el grafo (creando `needs.json` y pidiendo input al usuario).
Cundo replicamos esta lógica en `investigator.py`, olvidamos agregar el `req` a `pending_requirements`.
**Efecto visual:** Si falta una IP en el colector, el bot te pide la IP. Si falta un Auth Token al intentar verificar una hipótesis en el Investigator, el bot simplemente lo anota como evidencia de que falló y el Response Agent emite el reporte final pidiendo disculpas, en lugar de pausar y esperar tu ayuda.

---

## 3. Plan de Acción / Remediación Propuesta

Para que la arquitectura brille como está diseñada, necesitamos implementar tres fixes:

1. **Fix Supervisor (Fácil):**
   Modificar la condición de ruteo para que mantenga activo al `investigator_agent` mientras existan hipótesis en estado `verifying` O `proposed`.
2. **Fix Investigator HITL (Fácil):**
   Añadir el append a `pending_requirements` en la cláusula `except MissingDependencyError` del `investigator.py` luego de emitir la evidencia de bloqueo.
3. **Fix Enricher (Medio):**
   Implementar un extraction loop rápido con el LLM en `enricher_agent_node`. Debe leer los `evidence_refs` recién llegados, resumir sus hallazgos técnicos en una o dos líneas y agregarlos al diccionario `facts`. Esto alimentará correctamente al `Hypothesis Agent`.
