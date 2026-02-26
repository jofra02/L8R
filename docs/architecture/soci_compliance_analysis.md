# Análisis de Cumplimiento: Arquitectura SOC SOTA vs. `support_ai_agent`

He evaluado la arquitectura actual del proyecto `support_ai_agent` frente a las directrices y recomendaciones presentadas en el documento _"Estado del arte y diseño de arquitecturas de AI agents para un SOC modular"_. 

En términos generales, el proyecto **está altamente alineado (en compliance)** con el estado del arte propuesto para el 2026. A continuación, el desglose detallado por dimensiones arquitectónicas.

## 1. Orquestación y Control Plane
**Recomendación del Paper:** Uso de **LangGraph** como orquestador principal para manejar flujos largos (long-running), mantener estado (persistence/checkpointers), y soportar interrupciones (HITL).
**Estado en el Proyecto:** 🟢 **Cumple**
- El proyecto utiliza LangGraph (`src/agent_graph.py`) estructurando el flujo en un grafo con un nodo `supervisor` y agentes especializados (`evidence_collector`, `investigator`, `enricher`, `hypothesis`, `planner`, `response`).
- Usa persistencia de estado (`MemorySaver` / archivos) para pausar la ejecución y reanudarla (HITL soportado, evidenciado en `paused_state.json` y `needs.json` en `ResponseAgent`).

## 2. Herramientas e Integración (Tools Layer)
**Recomendación del Paper:** Uso de **FastAPI + MCP + FastMCP** para estandarizar la conexión de herramientas, tipado fuerte y conversión de OpenAPI de forma curada, aislando los recursos.
**Estado en el Proyecto:** 🟢 **Cumple**
- El proyecto implementa un cliente de Model Context Protocol (MCP) en `src/mcp/client.py` e interactúa con servidores remotos (ej. `remote-server (sse)` en logs anteriores).
- Registra dinámicamente capacidades (`CapabilityRegistry_`) derivadas de integraciones con MCP.

## 3. Patrones de Razonamiento (Agentic Patterns)
**Recomendación del Paper:** Implementar _planner-executor_, _tool-using_ con validación estructurada, y flujos _evidence-first_ (triage previo a la acción).
**Estado en el Proyecto:** 🟢 **Cumple con Excelencia**
- **Evidence-First:** El `EvidenceCollector` y el `Investigator` abstraen la recolección de pruebas antes de deducir conclusiones.
- **Planner-Executor acoplado a Structured Outputs:** El agente `Planner` usa `PydanticOutputParser` para asegurar la salida en JSON estricto del plan de remediación; el `Investigator` también abstrae el razonamiento paso a paso y la selección de herramientas de la ejecución en sí misma (haciendo uso del `AdaptiveExecutor`).
- **Recuperación Activa (Self-healing):** El `AdaptiveExecutor` implementa manejo heurístico (MissingDependencyError) para descubrir información faltante en lugar de fallar pasivamente, adaptándose a fallos de herramientas (ver `003_adaptive_investigator_flow.md`).

## 4. Memoria y Retrieval (RAG)
**Recomendación del Paper:** Memoria multi-capa (short-term para el hilo/incidente, long-term vía stores y _Agentic RAG_ para incidentes pasados).
**Estado en el Proyecto:** 🟢 **Cumple**
- **Short-term:** GlobalState de LangGraph por cada ticket.
- **Long-term / CBR (Case-Based Reasoning):** Implementación de `CaseRetriever` (`src/retrieval/case_retriever.py`) usando Qdrant (`VectorStore`) para inyectar incidentes previos resueltos en el contexto lógico del agente (`Planner`).
- **Evidence Store:** Hay un almacén inmutable de snapshots (`src/core/evidence_store.py`) separado de la memoria conversacional, tal cual recomienda el paper.

## 5. Prevención de Riesgos y Gobernanza (Security & HITL)
**Recomendación del Paper:** Policy gates, auditoría inmutable, mitigación de Output Handling inseguro (OWASP LLM02), y prevención de dependencias peligrosas.
**Estado en el Proyecto:** 🟢 **Cumple (Parcial a Total)**
- **Audit/Logging:** El proyecto guarda trazas mediante reportes y evidencia inmutable (evidence snapshot hashing).
- **HITL:** Integrado explícitamente cuando falta información (Requirement extraction -> Pausa -> Input de usuario).
- **Control de herramientas (OWASP LLM02):** Validaciones restrictivas y bloqueo mediante listas negras integradas (`_is_safe_tool` en `Investigator` usando `SAFETY_BLOCKED_KEYWORDS`). Se da prioridad implícita al Read-Only.

## 6. Modelos Fundacionales
**Recomendación del Paper:** Uso de Llama 4, Mistral Large 3, o GPT-5.2 / GPT-5 mini.
**Estado en el Proyecto:** 🟢 **Cumple**
- En `src/config.py` se definen y utilizan `gpt-5.2` y `gpt-5-mini` según el nivel de razonamiento requerido en cada nodo del grafo.

---
### Conclusión General
La arquitectura actual de `support_ai_agent` es un reflejo casi exacto del patrón SOTA 2026 descrito en el paper. Modula exitosamente la complejidad pasando de un modelo monolítico conversacional a un flujo agéntico determinista y auditable, separando el RAG (Casos), la Orquestación (LangGraph), la Ejecución (AdaptiveExecutor), y las herramientas (MCP).

**Únicas oportunidades menores de maduración derivadas del documento:**
1. **RBAC a nivel de MCP:** Asegurarse de que el servidor MCP que expone las herramientas tenga sus reglas de autorización/scoping segregadas por rol. (Actualmente manejado localmente por keywords y el conector MCP remoto no visible en este código fuente).
2. **Evaluaciones:** Ampliar la batería de testing adversarial y "Offline regression suites" para prompt injection indirecta, aunque ya se nota progreso en `test_rag_full_cycle.py`.
