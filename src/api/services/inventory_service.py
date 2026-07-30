"""Legacy inventory API service — delegating shim over AssetService.

Components and dependencies live in the relational assets/asset_relations
tables since the Asset Inventory migration; this service preserves the old
/inventory response shapes by translating Component <-> Asset on the way
through. Baselines and known changes still live in the client_contexts
blob. The gateway ordering contract (pending-first) now lives inside
AssetService.

Deprecation path: the /inventory components/dependencies endpoints are
retired once the frontend moves to /assets.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from src.core.models import ClientContext, Baseline, KnownChange
from src.core.context_store import ContextStore
from src.core.orm import AssetORM
from src.api.exceptions import APIError
from src.api.schemas.inventory import (
    ComponentCreate, ComponentUpdate,
    DependencyCreate,
    BaselineCreate, BaselineUpdate,
    KnownChangeCreate, KnownChangeUpdate,
    InventoryImport,
)
from src.api.schemas.assets import AssetCreate, AssetUpdate, RelationCreate
from src.api.services.gateway_admin_client import GatewayAdminClient
from src.assets.context_adapter import (
    PRIORITY_TO_CRITICALITY,
    asset_to_component_dict,
    assemble_inventory,
)
from src.assets.service import AssetService

# Legacy Component.role -> asset type (kept in sync with the starter type
# definitions; the b9c0d1e2f3a4 migration carries its own frozen copy).
ROLE_TO_TYPE = {
    "firewall": "firewall",
    "router": "router",
    "switch": "switch",
    "access_point": "access_point",
    "server": "server",
    "host": "server",
    "endpoint": "endpoint",
}

_SHIM_ACTOR = "legacy:inventory"


def _component_to_asset_create(data: ComponentCreate) -> AssetCreate:
    attributes = dict(data.metadata or {})
    attributes.pop("mcp", None)
    attributes["legacy_role"] = data.role
    return AssetCreate(
        id=data.id,
        name=data.ref,
        ref=data.ref,
        asset_type=ROLE_TO_TYPE.get(data.role, "generic"),
        manufacturer=data.vendor,
        criticality=PRIORITY_TO_CRITICALITY.get(data.priority, "low"),
        attributes=attributes,
        mcp_connection=data.mcp_connection,
    )


def _component_out(asset: AssetORM) -> dict:
    out = asset_to_component_dict(asset)
    sync = getattr(asset, "gateway_sync_transient", None)
    if sync is not None:
        out["gateway_sync"] = sync.model_dump()
    return out


class InventoryService:
    def __init__(self, session: AsyncSession, gateway: Optional[GatewayAdminClient] = None):
        self.session = session
        self.store = ContextStore(session)
        self.assets = AssetService(session, gateway=gateway)
        self.gateway = self.assets.gateway

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
        """Components/dependencies upsert into the asset tables
        (non-destructive: assets absent from the payload are NOT deleted —
        unlike the pre-migration full replace). Baselines/known changes keep
        the legacy destructive-replace semantics in the blob.
        """
        existing_ids = {
            c["id"] for c in (await assemble_inventory(self.session, customer_id))[0]
        }
        for comp in data.components:
            create = _component_to_asset_create(comp)
            create.mcp_connection = None  # legacy import drops mcp_connection
            if comp.id in existing_ids:
                await self.assets.update_asset(
                    customer_id, comp.id,
                    AssetUpdate(
                        name=create.name, ref=create.ref,
                        asset_type=create.asset_type,
                        manufacturer=create.manufacturer,
                        criticality=create.criticality,
                        attributes=create.attributes,
                    ),
                    _SHIM_ACTOR,
                    lenient=True,
                )
            else:
                await self.assets.create_asset(customer_id, create, _SHIM_ACTOR, lenient=True)

        for dep in data.dependencies:
            try:
                await self.add_dependency(customer_id, dep)
            except APIError as e:
                if e.error != "conflict":  # idempotent import
                    raise

        ctx = await self._load_or_init(customer_id)
        ctx.baselines = [Baseline(**b.model_dump()) for b in data.baselines]
        ctx.known_changes = [KnownChange(**kc.model_dump()) for kc in data.known_changes]
        await self._save_incremented(ctx)
        return await self.get_full_context(customer_id)

    # --- Components (delegating shims) ---

    async def list_components(self, customer_id: str) -> List[dict]:
        components, _ = await assemble_inventory(self.session, customer_id)
        return components

    async def get_component(self, customer_id: str, component_id: str) -> dict:
        try:
            asset = await self.assets.get_asset(customer_id, component_id)
        except APIError:
            raise APIError(404, "not_found", f"Component '{component_id}' not found")
        return _component_out(asset)

    async def add_component(self, customer_id: str, data: ComponentCreate) -> dict:
        try:
            asset = await self.assets.create_asset(
                customer_id, _component_to_asset_create(data), _SHIM_ACTOR, lenient=True
            )
        except APIError as e:
            if e.error == "conflict":
                raise APIError(409, "conflict", f"Component '{data.id}' already exists")
            raise
        return _component_out(asset)

    async def update_component(self, customer_id: str, component_id: str,
                               data: ComponentUpdate) -> dict:
        try:
            asset = await self.assets.get_asset(customer_id, component_id)
        except APIError:
            raise APIError(404, "not_found", f"Component '{component_id}' not found")

        update = AssetUpdate(
            mcp_connection=data.mcp_connection,
            mcp_managed=data.mcp_managed,
        )
        if data.ref is not None:
            update.ref = data.ref
            update.name = data.ref
        if data.vendor is not None:
            update.manufacturer = data.vendor
        if data.priority is not None:
            update.criticality = PRIORITY_TO_CRITICALITY.get(data.priority, "low")
        if data.role is not None:
            update.asset_type = ROLE_TO_TYPE.get(data.role, "generic")

        # Legacy metadata semantics: full replace (merge + explicit deletes).
        attributes = None
        if data.metadata is not None:
            new_meta = dict(data.metadata)
            new_meta.pop("mcp", None)
            attributes = {
                key: None
                for key in (asset.attributes or {})
                if key != "legacy_role" and key not in new_meta
            }
            attributes.update(new_meta)
        if data.role is not None:
            attributes = attributes if attributes is not None else {}
            attributes["legacy_role"] = data.role
        update.attributes = attributes

        asset = await self.assets.update_asset(
            customer_id, component_id, update, _SHIM_ACTOR, lenient=True
        )
        return _component_out(asset)

    async def delete_component(self, customer_id: str, component_id: str) -> dict:
        try:
            relations = await self.assets.list_relations(customer_id, component_id)
        except APIError:
            raise APIError(404, "not_found", f"Component '{component_id}' not found")

        result = await self.assets.soft_delete(customer_id, component_id, _SHIM_ACTOR)

        # Blob cascade parity: baselines/known changes referencing the id.
        ctx = await self._load_or_init(customer_id)
        baselines_removed = len(ctx.baselines)
        ctx.baselines = [b for b in ctx.baselines if b.component_id != component_id]
        baselines_removed -= len(ctx.baselines)
        changes_removed = len(ctx.known_changes)
        ctx.known_changes = [kc for kc in ctx.known_changes if kc.component_id != component_id]
        changes_removed -= len(ctx.known_changes)
        if baselines_removed or changes_removed:
            await self._save_incremented(ctx)

        out = {
            "deleted": component_id,
            "cascade": {
                "dependencies_removed": len(relations),
                "baselines_removed": baselines_removed,
                "known_changes_removed": changes_removed,
            },
        }
        if "gateway_sync" in result:
            out["gateway_sync"] = result["gateway_sync"]
        return out

    # --- Dependencies (delegating shims) ---

    async def list_dependencies(self, customer_id: str) -> List[dict]:
        _, dependencies = await assemble_inventory(self.session, customer_id)
        return dependencies

    async def add_dependency(self, customer_id: str, data: DependencyCreate) -> dict:
        try:
            await self.assets.get_asset(customer_id, data.source_id)
        except APIError:
            raise APIError(422, "validation_error",
                           f"Source component '{data.source_id}' not found in inventory")
        try:
            await self.assets.add_relation(
                customer_id, data.source_id,
                RelationCreate(target_asset_id=data.target_id,
                               relation_type=data.relation,
                               direction="out",
                               details=data.metadata),
                _SHIM_ACTOR,
            )
        except APIError as e:
            if e.error == "validation_error":
                raise APIError(422, "validation_error",
                               f"Target component '{data.target_id}' not found in inventory")
            if e.error == "conflict":
                raise APIError(409, "conflict", "Dependency already exists")
            raise
        return {
            "source_id": data.source_id,
            "target_id": data.target_id,
            "relation": data.relation,
            "metadata": data.metadata,
        }

    async def delete_dependency(self, customer_id: str, source_id: str,
                                target_id: str, relation: str) -> None:
        relations = await self.assets.list_relations(customer_id, source_id)
        match = next(
            (r for r in relations
             if r["source_asset_id"] == source_id and r["target_asset_id"] == target_id
             and r["relation_type"] == relation),
            None,
        )
        if match is None:
            raise APIError(404, "not_found", "Dependency not found")
        await self.assets.delete_relation(customer_id, match["id"], _SHIM_ACTOR)

    # --- Baselines (blob-owned, unchanged) ---

    async def list_baselines(self, customer_id: str) -> List[dict]:
        ctx = await self._load_or_init(customer_id)
        return [b.model_dump() for b in ctx.baselines]

    async def add_baseline(self, customer_id: str, data: BaselineCreate) -> dict:
        components, _ = await assemble_inventory(self.session, customer_id)
        if data.component_id not in {c["id"] for c in components}:
            raise APIError(422, "validation_error",
                           f"Component '{data.component_id}' not found in inventory")

        ctx = await self._load_or_init(customer_id)
        for b in ctx.baselines:
            if b.component_id == data.component_id and b.metric == data.metric:
                raise APIError(409, "conflict",
                               f"Baseline for ({data.component_id}, {data.metric}) already exists")

        baseline = Baseline(**data.model_dump())
        ctx.baselines.append(baseline)
        await self._save_incremented(ctx)
        return baseline.model_dump()

    async def update_baseline(self, customer_id: str, component_id: str,
                              metric: str, data: BaselineUpdate) -> dict:
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

    # --- Known Changes (blob-owned, unchanged) ---

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

    async def update_known_change(self, customer_id: str, index: int,
                                  data: KnownChangeUpdate) -> dict:
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
