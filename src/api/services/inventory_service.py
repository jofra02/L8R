from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from src.core.models import ClientContext, Component, InventoryDependency, Baseline, KnownChange
from src.core.context_store import ContextStore
from src.api.exceptions import APIError
from src.api.schemas.inventory import (
    ComponentCreate, ComponentUpdate, McpConnection,
    DependencyCreate,
    BaselineCreate, BaselineUpdate,
    KnownChangeCreate, KnownChangeUpdate,
    InventoryImport,
)
from src.api.services.gateway_admin_client import GatewayAdminClient, GatewaySyncResult


class InventoryService:
    def __init__(self, session: AsyncSession, gateway: Optional[GatewayAdminClient] = None):
        self.store = ContextStore(session)
        self.gateway = gateway if gateway is not None else GatewayAdminClient.from_settings()

    async def _load_or_init(self, customer_id: str) -> ClientContext:
        ctx = await self.store.get_active_context(customer_id)
        if not ctx:
            return ClientContext(customer_id=customer_id, version="0")
        return ctx

    async def _save_incremented(self, ctx: ClientContext) -> ClientContext:
        try:
            v = int(ctx.version)
        except (ValueError, TypeError):
            v = 0
        ctx.version = str(v + 1)
        await self.store.save_context(ctx)
        return ctx

    # --- Context-level ---

    async def get_overview(self, customer_id: str) -> dict:
        ctx = await self._load_or_init(customer_id)
        return {
            "customer_id": ctx.customer_id,
            "version": ctx.version,
            "component_count": len(ctx.inventory),
            "dependency_count": len(ctx.dependencies),
            "baseline_count": len(ctx.baselines),
            "known_change_count": len(ctx.known_changes),
        }

    async def get_full_context(self, customer_id: str) -> dict:
        ctx = await self._load_or_init(customer_id)
        return {
            "customer_id": ctx.customer_id,
            "version": ctx.version,
            "components": [c.model_dump() for c in ctx.inventory],
            "dependencies": [d.model_dump() for d in ctx.dependencies],
            "baselines": [b.model_dump() for b in ctx.baselines],
            "known_changes": [
                {**kc.model_dump(), "index": i}
                for i, kc in enumerate(ctx.known_changes)
            ],
        }

    async def import_context(self, customer_id: str, data: InventoryImport) -> dict:
        ctx = await self._load_or_init(customer_id)
        ctx.inventory = [
            Component(**c.model_dump(exclude={"mcp_connection"})) for c in data.components
        ]
        ctx.dependencies = [InventoryDependency(**d.model_dump()) for d in data.dependencies]
        ctx.baselines = [Baseline(**b.model_dump()) for b in data.baselines]
        ctx.known_changes = [KnownChange(**kc.model_dump()) for kc in data.known_changes]
        ctx = await self._save_incremented(ctx)
        return await self.get_full_context(customer_id)

    # --- Components ---

    async def list_components(self, customer_id: str) -> List[dict]:
        ctx = await self._load_or_init(customer_id)
        return [c.model_dump() for c in ctx.inventory]

    async def get_component(self, customer_id: str, component_id: str) -> dict:
        ctx = await self._load_or_init(customer_id)
        for c in ctx.inventory:
            if c.id == component_id:
                return c.model_dump()
        raise APIError(404, "not_found", f"Component '{component_id}' not found")

    # --- MCP gateway sync helpers ---

    @staticmethod
    def _gateway_payload(component: Component, mcp: McpConnection) -> dict:
        connection: dict = {
            "host": mcp.host,
            "port": mcp.port,
            "verify_ssl": mcp.verify_ssl,
        }
        if mcp.token:
            connection["token"] = mcp.token
        return {
            "id": component.id,
            "name": component.ref,
            "type": mcp.device_type,
            "primary": mcp.primary,
            "connection": connection,
        }

    @staticmethod
    def _set_mcp_metadata(component: Component, mcp: McpConnection, sync_info: dict) -> None:
        """Write the managed-connection descriptors (never the token) into metadata."""
        component.metadata["mcp"] = {
            "managed": True,
            "vendor": mcp.vendor,
            "appliance": mcp.appliance,
            "device_type": mcp.device_type,
            "host": mcp.host,
            "port": mcp.port,
            "verify_ssl": mcp.verify_ssl,
            "primary": mcp.primary,
            "sync": sync_info,
        }

    @staticmethod
    def _pending_sync_info() -> dict:
        return {"status": "pending", "last_error": None, "warnings": []}

    async def _sync_component_to_gateway(
        self, customer_id: str, component: Component, mcp: McpConnection, *, create: bool
    ) -> GatewaySyncResult:
        """Propagate a managed device to the gateway and record the outcome
        in ``component.metadata["mcp"]``; the caller persists the context.
        """
        if self.gateway is None:
            result = GatewaySyncResult(
                status="skipped", error="Gateway admin sync is not configured"
            )
        else:
            result = await self.gateway.upsert_device(
                customer_id, self._gateway_payload(component, mcp), create=create
            )

        sync_info = {
            "status": result.status,
            "last_error": result.error,
            "warnings": result.warnings,
        }
        if result.status == "synced":
            sync_info["last_synced_at"] = datetime.now(timezone.utc).isoformat()

        self._set_mcp_metadata(component, mcp, sync_info)
        return result

    @staticmethod
    def _is_managed(component: Component) -> bool:
        return bool((component.metadata.get("mcp") or {}).get("managed"))

    async def add_component(self, customer_id: str, data: ComponentCreate) -> dict:
        ctx = await self._load_or_init(customer_id)
        for c in ctx.inventory:
            if c.id == data.id:
                raise APIError(409, "conflict", f"Component '{data.id}' already exists")
        component = Component(**data.model_dump(exclude={"mcp_connection"}))

        # Local write first: the gateway must never hold a device the app has
        # no record of. The sync outcome is persisted in a second save.
        if data.mcp_connection:
            self._set_mcp_metadata(component, data.mcp_connection, self._pending_sync_info())
        ctx.inventory.append(component)
        await self._save_incremented(ctx)

        gateway_sync: Optional[GatewaySyncResult] = None
        if data.mcp_connection:
            gateway_sync = await self._sync_component_to_gateway(
                customer_id, component, data.mcp_connection, create=True
            )
            await self._save_incremented(ctx)
        out = component.model_dump()
        if gateway_sync:
            out["gateway_sync"] = gateway_sync.model_dump()
        return out

    async def update_component(self, customer_id: str, component_id: str, data: ComponentUpdate) -> dict:
        ctx = await self._load_or_init(customer_id)
        for c in ctx.inventory:
            if c.id == component_id:
                updates = data.model_dump(exclude_none=True, exclude={"mcp_connection", "mcp_managed"})
                for k, v in updates.items():
                    setattr(c, k, v)

                gateway_sync: Optional[GatewaySyncResult] = None
                was_managed = self._is_managed(c)
                if data.mcp_connection:
                    # Local write first (see add_component); sync outcome is
                    # persisted by the final save below.
                    self._set_mcp_metadata(c, data.mcp_connection, self._pending_sync_info())
                    await self._save_incremented(ctx)
                    gateway_sync = await self._sync_component_to_gateway(
                        customer_id, c, data.mcp_connection, create=not was_managed
                    )
                elif data.mcp_managed is False and was_managed:
                    if self.gateway is None:
                        gateway_sync = GatewaySyncResult(
                            status="skipped", error="Gateway admin sync is not configured"
                        )
                    else:
                        gateway_sync = await self.gateway.delete_device(customer_id, c.id)
                    c.metadata.pop("mcp", None)

                await self._save_incremented(ctx)
                out = c.model_dump()
                if gateway_sync:
                    out["gateway_sync"] = gateway_sync.model_dump()
                return out
        raise APIError(404, "not_found", f"Component '{component_id}' not found")

    async def delete_component(self, customer_id: str, component_id: str) -> dict:
        ctx = await self._load_or_init(customer_id)
        target = next((c for c in ctx.inventory if c.id == component_id), None)
        if target is None:
            raise APIError(404, "not_found", f"Component '{component_id}' not found")

        gateway_sync: Optional[GatewaySyncResult] = None
        if self._is_managed(target):
            if self.gateway is None:
                gateway_sync = GatewaySyncResult(
                    status="skipped", error="Gateway admin sync is not configured"
                )
            else:
                gateway_sync = await self.gateway.delete_device(customer_id, component_id)

        ctx.inventory = [c for c in ctx.inventory if c.id != component_id]

        # Cascade: remove related dependencies, baselines, known_changes
        deps_removed = len(ctx.dependencies)
        ctx.dependencies = [
            d for d in ctx.dependencies
            if d.source_id != component_id and d.target_id != component_id
        ]
        deps_removed -= len(ctx.dependencies)

        baselines_removed = len(ctx.baselines)
        ctx.baselines = [b for b in ctx.baselines if b.component_id != component_id]
        baselines_removed -= len(ctx.baselines)

        changes_removed = len(ctx.known_changes)
        ctx.known_changes = [kc for kc in ctx.known_changes if kc.component_id != component_id]
        changes_removed -= len(ctx.known_changes)

        await self._save_incremented(ctx)
        out = {
            "deleted": component_id,
            "cascade": {
                "dependencies_removed": deps_removed,
                "baselines_removed": baselines_removed,
                "known_changes_removed": changes_removed,
            },
        }
        if gateway_sync:
            out["gateway_sync"] = gateway_sync.model_dump()
        return out

    # --- Dependencies ---

    async def list_dependencies(self, customer_id: str) -> List[dict]:
        ctx = await self._load_or_init(customer_id)
        return [d.model_dump() for d in ctx.dependencies]

    async def add_dependency(self, customer_id: str, data: DependencyCreate) -> dict:
        ctx = await self._load_or_init(customer_id)
        inv_ids = {c.id for c in ctx.inventory}
        if data.source_id not in inv_ids:
            raise APIError(422, "validation_error", f"Source component '{data.source_id}' not found in inventory")
        if data.target_id not in inv_ids:
            raise APIError(422, "validation_error", f"Target component '{data.target_id}' not found in inventory")

        for d in ctx.dependencies:
            if d.source_id == data.source_id and d.target_id == data.target_id and d.relation == data.relation:
                raise APIError(409, "conflict", "Dependency already exists")

        dep = InventoryDependency(**data.model_dump())
        ctx.dependencies.append(dep)
        await self._save_incremented(ctx)
        return dep.model_dump()

    async def delete_dependency(self, customer_id: str, source_id: str, target_id: str, relation: str) -> None:
        ctx = await self._load_or_init(customer_id)
        original_len = len(ctx.dependencies)
        ctx.dependencies = [
            d for d in ctx.dependencies
            if not (d.source_id == source_id and d.target_id == target_id and d.relation == relation)
        ]
        if len(ctx.dependencies) == original_len:
            raise APIError(404, "not_found", "Dependency not found")
        await self._save_incremented(ctx)

    # --- Baselines ---

    async def list_baselines(self, customer_id: str) -> List[dict]:
        ctx = await self._load_or_init(customer_id)
        return [b.model_dump() for b in ctx.baselines]

    async def add_baseline(self, customer_id: str, data: BaselineCreate) -> dict:
        ctx = await self._load_or_init(customer_id)
        inv_ids = {c.id for c in ctx.inventory}
        if data.component_id not in inv_ids:
            raise APIError(422, "validation_error", f"Component '{data.component_id}' not found in inventory")

        for b in ctx.baselines:
            if b.component_id == data.component_id and b.metric == data.metric:
                raise APIError(409, "conflict", f"Baseline for ({data.component_id}, {data.metric}) already exists")

        baseline = Baseline(**data.model_dump())
        ctx.baselines.append(baseline)
        await self._save_incremented(ctx)
        return baseline.model_dump()

    async def update_baseline(self, customer_id: str, component_id: str, metric: str, data: BaselineUpdate) -> dict:
        ctx = await self._load_or_init(customer_id)
        for b in ctx.baselines:
            if b.component_id == component_id and b.metric == metric:
                updates = data.model_dump(exclude_none=True)
                for k, v in updates.items():
                    setattr(b, k, v)
                await self._save_incremented(ctx)
                return b.model_dump()
        raise APIError(404, "not_found", f"Baseline ({component_id}, {metric}) not found")

    async def delete_baseline(self, customer_id: str, component_id: str, metric: str) -> None:
        ctx = await self._load_or_init(customer_id)
        original_len = len(ctx.baselines)
        ctx.baselines = [
            b for b in ctx.baselines
            if not (b.component_id == component_id and b.metric == metric)
        ]
        if len(ctx.baselines) == original_len:
            raise APIError(404, "not_found", f"Baseline ({component_id}, {metric}) not found")
        await self._save_incremented(ctx)

    # --- Known Changes ---

    async def list_known_changes(self, customer_id: str) -> List[dict]:
        ctx = await self._load_or_init(customer_id)
        return [
            {**kc.model_dump(), "index": i}
            for i, kc in enumerate(ctx.known_changes)
        ]

    async def add_known_change(self, customer_id: str, data: KnownChangeCreate) -> dict:
        ctx = await self._load_or_init(customer_id)
        kc = KnownChange(**data.model_dump())
        ctx.known_changes.append(kc)
        idx = len(ctx.known_changes) - 1
        await self._save_incremented(ctx)
        return {**kc.model_dump(), "index": idx}

    async def update_known_change(self, customer_id: str, index: int, data: KnownChangeUpdate) -> dict:
        ctx = await self._load_or_init(customer_id)
        if index < 0 or index >= len(ctx.known_changes):
            raise APIError(404, "not_found", f"Known change at index {index} not found")
        kc = ctx.known_changes[index]
        updates = data.model_dump(exclude_none=True)
        for k, v in updates.items():
            setattr(kc, k, v)
        await self._save_incremented(ctx)
        return {**kc.model_dump(), "index": index}

    async def delete_known_change(self, customer_id: str, index: int) -> None:
        ctx = await self._load_or_init(customer_id)
        if index < 0 or index >= len(ctx.known_changes):
            raise APIError(404, "not_found", f"Known change at index {index} not found")
        ctx.known_changes.pop(index)
        await self._save_incremented(ctx)
