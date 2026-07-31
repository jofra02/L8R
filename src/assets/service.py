"""AssetService: relational asset CRUD, audit, gateway sync and search.

Owns the MCP gateway ordering contract inherited from the legacy
InventoryService: local write FIRST with sync_status="pending" (committed),
then the gateway call, then a second commit with the outcome — the gateway
must never hold a device the app has no record of. The token is write-only:
forwarded to the gateway, never persisted app-side.

Tenant isolation: every query filters by customer_id; the tenant check is a
404, never a 403 (assessment-service pattern).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.exceptions import APIError
from src.api.schemas.assets import AssetCreate, AssetUpdate, RelationCreate
from src.api.schemas.inventory import McpConnection
from src.api.services.gateway_admin_client import GatewayAdminClient, GatewaySyncResult
from src.assets import registry
from src.assets.products import ensure_product
from src.assets.schema import AssetTypeDefinition
from src.assets.validation import (
    coerce_filter_value,
    filterable_field_defs,
    sensitive_keys,
    validate_attributes,
)
from src.core.orm import (
    AssetAuditLogORM,
    AssetORM,
    AssetRelationORM,
    AssetSubitemORM,
    AssetSyncRunORM,
)

logger = logging.getLogger(__name__)

COMMON_FIELDS = (
    "name", "ref", "asset_type", "manufacturer", "model", "product_name",
    "serial_number", "location", "owner", "ip_address", "fqdn", "status",
    "criticality", "tags", "purchase_date", "warranty_expires", "eol_date",
)

SORTABLE_COLUMNS = {
    "name": AssetORM.name,
    "ref": AssetORM.ref,
    "asset_type": AssetORM.asset_type,
    "status": AssetORM.status,
    "criticality": AssetORM.criticality,
    "manufacturer": AssetORM.manufacturer,
    "model": AssetORM.model,
    "product_name": AssetORM.product_name,
    "serial_number": AssetORM.serial_number,
    "ip_address": AssetORM.ip_address,
    "last_synced_at": AssetORM.last_synced_at,
    "created_at": AssetORM.created_at,
    "updated_at": AssetORM.updated_at,
}

_SEARCH_COLUMNS = (
    AssetORM.name, AssetORM.ref, AssetORM.serial_number, AssetORM.ip_address,
    AssetORM.fqdn, AssetORM.manufacturer, AssetORM.model, AssetORM.product_name,
)

# Multi-value column filters. Values arrive as lists (or comma-separated
# strings from internal callers); OR within a column, AND across columns.
_EXACT_FILTER_COLUMNS = {
    "asset_type": AssetORM.asset_type,
    "status": AssetORM.status,
    "criticality": AssetORM.criticality,
    "sync_status": AssetORM.sync_status,
}

_ILIKE_FILTER_COLUMNS = {
    "name": AssetORM.name,
    "product_name": AssetORM.product_name,
    "model": AssetORM.model,
    "manufacturer": AssetORM.manufacturer,
    "ip_address": AssetORM.ip_address,
    "serial_number": AssetORM.serial_number,
    "owner": AssetORM.owner,
}


def _filter_values(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = raw.split(",")
    return [v.strip() for v in raw if isinstance(v, str) and v.strip()]


# Subitem listings share the assets filtering model (CSV multi-value,
# exact IN for enums, OR-of-ILIKE for free text).
SUBITEM_SORTABLE_COLUMNS = {
    "name": AssetSubitemORM.name,
    "kind": AssetSubitemORM.kind,
    "state": AssetSubitemORM.state,
    "source": AssetSubitemORM.source,
    "external_id": AssetSubitemORM.external_id,
    "first_seen_at": AssetSubitemORM.first_seen_at,
    "last_seen_at": AssetSubitemORM.last_seen_at,
    "created_at": AssetSubitemORM.created_at,
}

_SUB_EXACT_FILTER_COLUMNS = {
    "kind": AssetSubitemORM.kind,
    "state": AssetSubitemORM.state,
    "source": AssetSubitemORM.source,
}

_SUB_ILIKE_FILTER_COLUMNS = {
    "name": AssetSubitemORM.name,
    "external_id": AssetSubitemORM.external_id,
}

# parent_subitem_id filter sentinel: only top-level rows.
SUBITEM_ROOT_SENTINEL = "root"

REDACTED = "***"


async def compute_subitems_summary(
    session: AsyncSession,
    asset_ids: List[str],
    customer_id: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """One grouped query -> {asset_id: {kind: {total, by_state, absent}}}.

    Shared by the API (per-page batches) and the context adapter (all live
    tenant assets). Plain GROUP BY on purpose — must run identically on
    Postgres and the sqlite test engine. customer_id=None is the /global
    path (uuid PKs make cross-tenant id collision impossible).
    """
    if not asset_ids:
        return {}
    stmt = (
        select(AssetSubitemORM.parent_asset_id, AssetSubitemORM.kind,
               AssetSubitemORM.state, AssetSubitemORM.absent, func.count())
        .where(AssetSubitemORM.parent_asset_id.in_(asset_ids))
        .group_by(AssetSubitemORM.parent_asset_id, AssetSubitemORM.kind,
                  AssetSubitemORM.state, AssetSubitemORM.absent)
    )
    if customer_id is not None:
        stmt = stmt.where(AssetSubitemORM.customer_id == customer_id)
    out: Dict[str, Dict[str, Any]] = {}
    for parent_id, kind, state, absent, n in (await session.execute(stmt)).all():
        entry = out.setdefault(parent_id, {}).setdefault(
            kind, {"total": 0, "by_state": {}, "absent": 0})
        entry["total"] += n
        state_key = state or "unknown"
        entry["by_state"][state_key] = entry["by_state"].get(state_key, 0) + n
        if absent:
            entry["absent"] += n
    return out


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mcp_config_from_connection(mcp: McpConnection) -> Dict[str, Any]:
    """Persisted connection descriptors — deliberately excludes the token."""
    return {
        "vendor": mcp.vendor,
        "appliance": mcp.appliance,
        "device_type": mcp.device_type,
        "os_version": mcp.os_version,
        "host": mcp.host,
        "port": mcp.port,
        "verify_ssl": mcp.verify_ssl,
        "primary": mcp.primary,
    }


def _gateway_payload(asset: AssetORM, mcp: McpConnection) -> dict:
    connection: dict = {
        "host": mcp.host,
        "port": mcp.port,
        "verify_ssl": mcp.verify_ssl,
    }
    if mcp.token:
        connection["token"] = mcp.token
    payload = {
        "id": asset.id,
        "name": asset.ref,
        "type": mcp.device_type,
        "primary": mcp.primary,
        "connection": connection,
    }
    if mcp.os_version:
        payload["os_version"] = mcp.os_version
    return payload


def build_asset_query(
    *,
    customer_id: Optional[str],
    filters: Dict[str, Any],
    filterable_defs: Dict[str, Any],
    include_deleted: bool = False,
):
    """Shared filter builder for the tenant list and the global MSP list."""
    stmt = select(AssetORM)
    if customer_id is not None:
        stmt = stmt.where(AssetORM.customer_id == customer_id)
    elif filters.get("customer_id"):
        stmt = stmt.where(AssetORM.customer_id == filters["customer_id"])
    if not include_deleted:
        stmt = stmt.where(AssetORM.deleted_at.is_(None))

    for key, column in _EXACT_FILTER_COLUMNS.items():
        vals = _filter_values(filters.get(key))
        if vals:
            stmt = stmt.where(column == vals[0] if len(vals) == 1
                              else column.in_(vals))
    for key, column in _ILIKE_FILTER_COLUMNS.items():
        vals = _filter_values(filters.get(key))
        if vals:
            stmt = stmt.where(or_(*[column.ilike(f"%{v}%") for v in vals]))
    if filters.get("managed") is not None:
        stmt = stmt.where(AssetORM.managed == filters["managed"])
    for tag in filters.get("tags") or []:
        stmt = stmt.where(AssetORM.tags.contains([tag]))

    q = (filters.get("q") or "").strip()
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(*[c.ilike(like) for c in _SEARCH_COLUMNS]))

    for key, raw in (filters.get("attrs") or {}).items():
        field = filterable_defs.get(key)
        if field is None:
            raise APIError(422, "validation_error",
                           f"attr.{key} is not a filterable attribute")
        stmt = stmt.where(AssetORM.attributes.contains({key: coerce_filter_value(field, raw)}))
    return stmt


def apply_sort(stmt, sort: Optional[str]):
    if not sort:
        return stmt.order_by(AssetORM.created_at.desc())
    desc = sort.startswith("-")
    key = sort.lstrip("+-")
    column = SORTABLE_COLUMNS.get(key)
    if column is None:
        raise APIError(422, "validation_error",
                       f"sort must be one of {sorted(SORTABLE_COLUMNS)}")
    return stmt.order_by(column.desc() if desc else column.asc(), AssetORM.id)


def apply_subitem_sort(stmt, sort: Optional[str]):
    if not sort:
        return stmt.order_by(AssetSubitemORM.name, AssetSubitemORM.id)
    desc = sort.startswith("-")
    key = sort.lstrip("+-")
    column = SUBITEM_SORTABLE_COLUMNS.get(key)
    if column is None:
        raise APIError(422, "validation_error",
                       f"sort must be one of {sorted(SUBITEM_SORTABLE_COLUMNS)}")
    return stmt.order_by(column.desc() if desc else column.asc(), AssetSubitemORM.id)


class AssetService:
    def __init__(self, session: AsyncSession, gateway: Optional[GatewayAdminClient] = None):
        self.session = session
        self.gateway = gateway if gateway is not None else GatewayAdminClient.from_settings()

    # --- internals ---

    async def _get(self, customer_id: str, asset_id: str, *,
                   include_deleted: bool = False) -> AssetORM:
        stmt = select(AssetORM).where(
            AssetORM.customer_id == customer_id, AssetORM.id == asset_id
        )
        if not include_deleted:
            stmt = stmt.where(AssetORM.deleted_at.is_(None))
        asset = (await self.session.execute(stmt)).scalar_one_or_none()
        if asset is None:
            raise APIError(404, "not_found", f"Asset '{asset_id}' not found")
        return asset

    async def _type_def(self, asset_type: str) -> AssetTypeDefinition:
        type_def = await registry.get_latest_type(self.session, asset_type)
        if type_def is None:
            raise APIError(422, "validation_error", f"Unknown asset_type '{asset_type}'")
        return type_def

    async def _check_ref_free(self, customer_id: str, ref: str,
                              exclude_id: Optional[str] = None) -> None:
        stmt = select(AssetORM.id).where(
            AssetORM.customer_id == customer_id,
            AssetORM.ref == ref,
            AssetORM.deleted_at.is_(None),
        )
        if exclude_id:
            stmt = stmt.where(AssetORM.id != exclude_id)
        if (await self.session.execute(stmt)).first() is not None:
            raise APIError(409, "conflict", f"An active asset with ref '{ref}' already exists")

    def _audit(self, asset: AssetORM, actor: str, action: str,
               changes: Optional[Dict[str, Any]] = None,
               sync_run_id: Optional[str] = None) -> None:
        self.session.add(AssetAuditLogORM(
            customer_id=asset.customer_id,
            asset_id=asset.id,
            actor=actor,
            action=action,
            changes=changes or {},
            sync_run_id=sync_run_id,
        ))

    @staticmethod
    def _stamp_manual(asset: AssetORM, keys: List[str]) -> None:
        prov = dict(asset.provenance or {})
        stamp = {"source": "manual", "updated_at": _now().isoformat()}
        for key in keys:
            prov[key] = stamp
        asset.provenance = prov

    async def _validate_attrs(self, type_def: AssetTypeDefinition,
                              attributes: Dict[str, Any],
                              existing_keys: Tuple[str, ...] = (),
                              lenient: bool = False) -> Dict[str, Any]:
        normalized, errors = validate_attributes(
            type_def, attributes, allowed_extra_keys=existing_keys
        )
        if errors and not lenient:
            raise APIError(422, "validation_error", "; ".join(errors))
        return normalized

    # --- gateway sync (ordering contract preserved from InventoryService) ---

    async def _sync_to_gateway(self, asset: AssetORM, mcp: McpConnection, *,
                               create: bool, actor: str) -> GatewaySyncResult:
        if self.gateway is None:
            result = GatewaySyncResult(status="skipped",
                                       error="Gateway admin sync is not configured")
        else:
            result = await self.gateway.upsert_device(
                asset.customer_id, _gateway_payload(asset, mcp), create=create
            )
        cfg = dict(asset.mcp_config or {})
        if result.warnings:
            cfg["sync_warnings"] = result.warnings
        else:
            cfg.pop("sync_warnings", None)
        asset.mcp_config = cfg
        old_status = asset.sync_status
        asset.sync_status = result.status
        asset.sync_error = result.error
        if result.status == "synced":
            asset.last_synced_at = _now()
        self._audit(asset, actor, "sync_status_changed",
                    {"sync_status": {"old": old_status, "new": result.status}})
        return result

    async def _gateway_delete(self, asset: AssetORM) -> GatewaySyncResult:
        if self.gateway is None:
            return GatewaySyncResult(status="skipped",
                                     error="Gateway admin sync is not configured")
        return await self.gateway.delete_device(asset.customer_id, asset.id)

    async def _maybe_auto_enrich(self, asset: AssetORM) -> None:
        """Best-effort: queue an enrichment run after a successful MCP sync."""
        try:
            from src.assets.enrichment.engine import enqueue_enrichment
            await enqueue_enrichment(asset.customer_id, asset.id, trigger="auto")
        except Exception as e:
            logger.warning(f"Auto-enrichment enqueue failed for asset {asset.id}: {e}")

    # --- CRUD ---

    async def create_asset(self, customer_id: str, data: AssetCreate, actor: str,
                           *, auto_enrich: bool = True, lenient: bool = False) -> AssetORM:
        """lenient=True (legacy /inventory shim only): tolerate undeclared or
        malformed attributes instead of failing with 422 — the old API never
        validated metadata."""
        type_def = await self._type_def(data.asset_type)
        attributes = await self._validate_attrs(type_def, data.attributes, lenient=lenient)

        asset_id = data.id or uuid.uuid4().hex
        existing = (await self.session.execute(
            select(AssetORM.id).where(AssetORM.id == asset_id)
        )).first()
        if existing is not None:
            raise APIError(409, "conflict", f"Asset '{asset_id}' already exists")

        ref = data.ref or data.name
        await self._check_ref_free(customer_id, ref)

        product_name = None
        if data.product_name:
            product_name = await ensure_product(self.session, data.product_name)

        asset = AssetORM(
            id=asset_id,
            customer_id=customer_id,
            name=data.name,
            ref=ref,
            asset_type=data.asset_type,
            type_schema_version=type_def.version,
            manufacturer=data.manufacturer,
            model=data.model,
            product_name=product_name,
            serial_number=data.serial_number,
            location=data.location,
            owner=data.owner,
            ip_address=data.ip_address,
            fqdn=data.fqdn,
            status=data.status,
            criticality=data.criticality,
            tags=list(data.tags),
            purchase_date=data.purchase_date,
            warranty_expires=data.warranty_expires,
            eol_date=data.eol_date,
            attributes=attributes,
            provenance={},
            created_by=actor,
            updated_by=actor,
        )
        manual_keys = [f for f in COMMON_FIELDS
                       if getattr(data, f, None) not in (None, [], {})]
        manual_keys += [f"attributes.{k}" for k in (data.attributes or {})]
        self._stamp_manual(asset, manual_keys)

        # Local write first (pending) — gateway never holds an unknown device.
        if data.mcp_connection:
            asset.managed = True
            asset.mcp_config = _mcp_config_from_connection(data.mcp_connection)
            asset.sync_status = "pending"
        self.session.add(asset)
        # No relationship() links AssetAuditLogORM to AssetORM, so the unit
        # of work has no ordering edge between the two INSERTs — the asset
        # must be flushed before its audit row or the audit FK can fire
        # first (mapper batch order shifts whenever the mapper set changes).
        await self.session.flush([asset])
        self._audit(asset, actor, "created", {"asset": {"old": None, "new": asset.name}})
        await self.session.commit()

        gateway_sync: Optional[GatewaySyncResult] = None
        if data.mcp_connection:
            gateway_sync = await self._sync_to_gateway(
                asset, data.mcp_connection, create=True, actor=actor
            )
            await self.session.commit()
            if auto_enrich and gateway_sync.status == "synced":
                await self._maybe_auto_enrich(asset)

        asset.gateway_sync_transient = gateway_sync  # consumed by the router
        return asset

    async def update_asset(self, customer_id: str, asset_id: str, data: AssetUpdate,
                           actor: str, *, auto_enrich: bool = True,
                           lenient: bool = False) -> AssetORM:
        asset = await self._get(customer_id, asset_id)

        updates = data.model_dump(exclude_none=True,
                                  exclude={"mcp_connection", "mcp_managed", "attributes"})
        if updates.get("product_name"):
            updates["product_name"] = await ensure_product(
                self.session, updates["product_name"])
        if "asset_type" in updates and updates["asset_type"] != asset.asset_type:
            type_def = await self._type_def(updates["asset_type"])
        else:
            type_def = await self._type_def(asset.asset_type)
            updates.pop("asset_type", None)

        if "ref" in updates and updates["ref"] != asset.ref:
            await self._check_ref_free(customer_id, updates["ref"], exclude_id=asset.id)

        changes: Dict[str, Any] = {}
        for field, new in updates.items():
            old = getattr(asset, field)
            if old != new:
                changes[field] = {"old": _jsonable(old), "new": _jsonable(new)}
                setattr(asset, field, new)
        if "asset_type" in changes:
            asset.type_schema_version = type_def.version

        # Attributes: merge semantics — provided keys overwrite, explicit
        # null deletes. Discovered keys the form does not know survive.
        if data.attributes is not None:
            merged = dict(asset.attributes or {})
            touched: List[str] = []
            for key, value in data.attributes.items():
                if value is None:
                    if key in merged:
                        changes[f"attributes.{key}"] = {"old": _jsonable(merged.pop(key)), "new": None}
                        touched.append(key)
                    continue
                if merged.get(key) != value:
                    changes[f"attributes.{key}"] = {"old": _jsonable(merged.get(key)), "new": _jsonable(value)}
                    merged[key] = value
                    touched.append(key)
            merged = await self._validate_attrs(
                type_def, merged,
                existing_keys=tuple((asset.attributes or {}).keys()),
                lenient=lenient,
            )
            asset.attributes = merged
            asset.type_schema_version = type_def.version
            self._stamp_manual(asset, [f"attributes.{k}" for k in touched])

        self._stamp_manual(asset, [f for f in changes if not f.startswith("attributes.")])
        if changes:
            asset.updated_by = actor
            self._audit(asset, actor, "updated", changes)

        gateway_sync: Optional[GatewaySyncResult] = None
        was_managed = asset.managed
        if data.mcp_connection:
            asset.managed = True
            asset.mcp_config = _mcp_config_from_connection(data.mcp_connection)
            asset.sync_status = "pending"
            asset.sync_error = None
            await self.session.commit()  # local pending state first
            gateway_sync = await self._sync_to_gateway(
                asset, data.mcp_connection, create=not was_managed, actor=actor
            )
            await self.session.commit()
            if auto_enrich and gateway_sync.status == "synced":
                await self._maybe_auto_enrich(asset)
        elif data.mcp_managed is False and was_managed:
            gateway_sync = await self._gateway_delete(asset)
            asset.managed = False
            asset.mcp_config = None
            asset.sync_status = None
            asset.sync_error = None
            asset.last_synced_at = None
            self._audit(asset, actor, "sync_status_changed",
                        {"managed": {"old": True, "new": False}})
            await self.session.commit()
        else:
            await self.session.commit()

        asset.gateway_sync_transient = gateway_sync
        return asset

    async def soft_delete(self, customer_id: str, asset_id: str, actor: str) -> Dict[str, Any]:
        asset = await self._get(customer_id, asset_id)
        gateway_sync: Optional[GatewaySyncResult] = None
        if asset.managed:
            gateway_sync = await self._gateway_delete(asset)
            asset.sync_status = None
        asset.deleted_at = _now()
        asset.updated_by = actor
        self._audit(asset, actor, "deleted", {})
        await self.session.commit()
        out: Dict[str, Any] = {"deleted": asset_id}
        if gateway_sync:
            out["gateway_sync"] = gateway_sync.model_dump()
        return out

    async def restore(self, customer_id: str, asset_id: str, actor: str) -> AssetORM:
        asset = await self._get(customer_id, asset_id, include_deleted=True)
        if asset.deleted_at is None:
            raise APIError(409, "invalid_state", f"Asset '{asset_id}' is not deleted")
        await self._check_ref_free(customer_id, asset.ref, exclude_id=asset.id)
        asset.deleted_at = None
        asset.updated_by = actor
        self._audit(asset, actor, "restored", {})
        await self.session.commit()

        gateway_sync: Optional[GatewaySyncResult] = None
        if asset.managed and asset.mcp_config:
            # Token stays gateway-side; re-provision without it (drift repair).
            mcp = McpConnection(**{k: v for k, v in asset.mcp_config.items()
                                   if k in McpConnection.model_fields})
            asset.sync_status = "pending"
            await self.session.commit()
            gateway_sync = await self._sync_to_gateway(asset, mcp, create=True, actor=actor)
            await self.session.commit()
        asset.gateway_sync_transient = gateway_sync
        return asset

    async def get_asset(self, customer_id: str, asset_id: str, *,
                        include_deleted: bool = False) -> AssetORM:
        return await self._get(customer_id, asset_id, include_deleted=include_deleted)

    async def list_assets(
        self,
        customer_id: Optional[str],
        filters: Dict[str, Any],
        *,
        page: int,
        page_size: int,
        sort: Optional[str] = None,
        include_deleted: bool = False,
    ) -> Tuple[List[AssetORM], int]:
        types = await registry.get_latest_types(self.session)
        filterable = filterable_field_defs(types)
        stmt = build_asset_query(
            customer_id=customer_id, filters=filters,
            filterable_defs=filterable, include_deleted=include_deleted,
        )
        total = (await self.session.execute(
            select(func.count()).select_from(stmt.subquery())
        )).scalar() or 0
        stmt = apply_sort(stmt, sort).offset((page - 1) * page_size).limit(page_size)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), total

    async def redact_sensitive(self, assets: List[AssetORM]) -> None:
        """Mask sensitive attribute values for callers without assets:manage."""
        types = await registry.get_latest_types(self.session)
        for asset in assets:
            type_def = types.get(asset.asset_type)
            if type_def is None:
                continue
            hidden = sensitive_keys(type_def)
            if not hidden:
                continue
            masked = dict(asset.attributes or {})
            for key in hidden:
                if key in masked:
                    masked[key] = REDACTED
            asset.attributes = masked

    # --- subitems (discovered sub-inventory, read-only) ---

    async def list_subitems(
        self, customer_id: str, asset_id: str, *,
        filters: Optional[Dict[str, Any]] = None,
        sort: Optional[str] = None,
        page: int,
        page_size: int,
    ) -> Tuple[List[AssetSubitemORM], int]:
        await self._get(customer_id, asset_id)  # tenant check -> 404
        filters = filters or {}
        stmt = select(AssetSubitemORM).where(
            AssetSubitemORM.customer_id == customer_id,
            AssetSubitemORM.parent_asset_id == asset_id,
        )
        parent = filters.get("parent_subitem_id")
        if parent == SUBITEM_ROOT_SENTINEL:
            stmt = stmt.where(AssetSubitemORM.parent_subitem_id.is_(None))
        elif parent:
            stmt = stmt.where(AssetSubitemORM.parent_subitem_id == parent)
        for key, column in _SUB_EXACT_FILTER_COLUMNS.items():
            vals = _filter_values(filters.get(key))
            if vals:
                stmt = stmt.where(column == vals[0] if len(vals) == 1 else column.in_(vals))
        for key, column in _SUB_ILIKE_FILTER_COLUMNS.items():
            vals = _filter_values(filters.get(key))
            if vals:
                stmt = stmt.where(or_(*[column.ilike(f"%{v}%") for v in vals]))
        absent = filters.get("absent")
        if absent is not None:
            stmt = stmt.where(AssetSubitemORM.absent.is_(absent))
        q = filters.get("q")
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(AssetSubitemORM.name.ilike(like),
                                  AssetSubitemORM.external_id.ilike(like)))
        total = (await self.session.execute(
            select(func.count()).select_from(stmt.subquery())
        )).scalar() or 0
        stmt = (apply_subitem_sort(stmt, sort)
                .offset((page - 1) * page_size).limit(page_size))
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), total

    async def get_subitem(self, customer_id: str, asset_id: str,
                          subitem_id: str) -> AssetSubitemORM:
        await self._get(customer_id, asset_id)  # tenant check -> 404
        row = (await self.session.execute(
            select(AssetSubitemORM).where(
                AssetSubitemORM.customer_id == customer_id,
                AssetSubitemORM.parent_asset_id == asset_id,
                AssetSubitemORM.id == subitem_id,
            )
        )).scalar_one_or_none()
        if row is None:
            raise APIError(404, "not_found", f"Subitem '{subitem_id}' not found")
        return row

    _ANCESTOR_DEPTH_CAP = 16

    async def subitem_ancestors(self, row: AssetSubitemORM) -> List[Dict[str, str]]:
        """Root-first parent chain, excluding the row itself. Iterative walk
        on purpose (portable across Postgres/sqlite, depth is bounded)."""
        chain: List[Dict[str, str]] = []
        current = row
        for _ in range(self._ANCESTOR_DEPTH_CAP):
            if current.parent_subitem_id is None:
                break
            parent = (await self.session.execute(
                select(AssetSubitemORM).where(
                    AssetSubitemORM.customer_id == row.customer_id,
                    AssetSubitemORM.id == current.parent_subitem_id,
                )
            )).scalar_one_or_none()
            if parent is None:
                break
            chain.insert(0, {"id": parent.id, "name": parent.name, "kind": parent.kind})
            current = parent
        return chain

    async def subitem_children_counts(self, subitem_ids: List[str]) -> Dict[str, int]:
        """One GROUP BY for the current page (compute_subitems_summary pattern)."""
        if not subitem_ids:
            return {}
        rows = (await self.session.execute(
            select(AssetSubitemORM.parent_subitem_id, func.count())
            .where(AssetSubitemORM.parent_subitem_id.in_(subitem_ids))
            .group_by(AssetSubitemORM.parent_subitem_id)
        )).all()
        return {pid: n for pid, n in rows}

    async def subitems_summary(
        self, asset_ids: List[str], customer_id: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        return await compute_subitems_summary(self.session, asset_ids, customer_id)

    # --- relations ---

    async def list_relations(self, customer_id: str, asset_id: str) -> List[Dict[str, Any]]:
        await self._get(customer_id, asset_id, include_deleted=True)
        stmt = (
            select(AssetRelationORM)
            .where(AssetRelationORM.customer_id == customer_id,
                   or_(AssetRelationORM.source_asset_id == asset_id,
                       AssetRelationORM.target_asset_id == asset_id))
            .order_by(AssetRelationORM.id)
        )
        rels = (await self.session.execute(stmt)).scalars().all()
        ids = {r.source_asset_id for r in rels} | {r.target_asset_id for r in rels}
        names: Dict[str, str] = {}
        if ids:
            rows = (await self.session.execute(
                select(AssetORM.id, AssetORM.name).where(AssetORM.id.in_(ids))
            )).all()
            names = {r[0]: r[1] for r in rows}
        return [{
            "id": r.id,
            "source_asset_id": r.source_asset_id,
            "target_asset_id": r.target_asset_id,
            "relation_type": r.relation_type,
            "provenance": r.provenance,
            "details": r.details or {},
            "created_at": r.created_at,
            "source_name": names.get(r.source_asset_id),
            "target_name": names.get(r.target_asset_id),
        } for r in rels]

    async def add_relation(self, customer_id: str, asset_id: str,
                           data: RelationCreate, actor: str) -> AssetRelationORM:
        asset = await self._get(customer_id, asset_id)
        other = (await self.session.execute(
            select(AssetORM).where(AssetORM.customer_id == customer_id,
                                   AssetORM.id == data.target_asset_id,
                                   AssetORM.deleted_at.is_(None))
        )).scalar_one_or_none()
        if other is None:
            raise APIError(422, "validation_error",
                           f"Asset '{data.target_asset_id}' not found")

        source, target = (asset, other) if data.direction == "out" else (other, asset)
        type_def = await registry.get_latest_type(self.session, source.asset_type)
        if type_def and type_def.relations.allowed and \
                data.relation_type not in type_def.relations.allowed:
            raise APIError(422, "validation_error",
                           f"relation_type '{data.relation_type}' not allowed for "
                           f"type '{source.asset_type}' "
                           f"(allowed: {type_def.relations.allowed})")

        dup = (await self.session.execute(
            select(AssetRelationORM.id).where(
                AssetRelationORM.customer_id == customer_id,
                AssetRelationORM.source_asset_id == source.id,
                AssetRelationORM.target_asset_id == target.id,
                AssetRelationORM.relation_type == data.relation_type,
            )
        )).first()
        if dup is not None:
            raise APIError(409, "conflict", "Relation already exists")

        rel = AssetRelationORM(
            customer_id=customer_id,
            source_asset_id=source.id,
            target_asset_id=target.id,
            relation_type=data.relation_type,
            provenance="manual",
            details=data.details,
        )
        self.session.add(rel)
        self._audit(asset, actor, "relation_added",
                    {"relation": {"old": None,
                                  "new": f"{source.id} -{data.relation_type}-> {target.id}"}})
        await self.session.commit()
        return rel

    async def delete_relation(self, customer_id: str, relation_id: int, actor: str) -> None:
        rel = (await self.session.execute(
            select(AssetRelationORM).where(
                AssetRelationORM.customer_id == customer_id,
                AssetRelationORM.id == relation_id,
            )
        )).scalar_one_or_none()
        if rel is None:
            raise APIError(404, "not_found", f"Relation '{relation_id}' not found")
        source = (await self.session.execute(
            select(AssetORM).where(AssetORM.customer_id == customer_id,
                                   AssetORM.id == rel.source_asset_id)
        )).scalar_one_or_none()
        if source is not None:
            self._audit(source, actor, "relation_removed",
                        {"relation": {"old": f"{rel.source_asset_id} "
                                             f"-{rel.relation_type}-> {rel.target_asset_id}",
                                      "new": None}})
        await self.session.delete(rel)
        await self.session.commit()

    # --- history / sync runs ---

    async def history(self, customer_id: str, asset_id: str, *,
                      page: int, page_size: int) -> Tuple[List[AssetAuditLogORM], int]:
        await self._get(customer_id, asset_id, include_deleted=True)
        base = select(AssetAuditLogORM).where(
            AssetAuditLogORM.customer_id == customer_id,
            AssetAuditLogORM.asset_id == asset_id,
        )
        total = (await self.session.execute(
            select(func.count()).select_from(base.subquery())
        )).scalar() or 0
        rows = (await self.session.execute(
            base.order_by(AssetAuditLogORM.created_at.desc(), AssetAuditLogORM.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )).scalars().all()
        return list(rows), total

    async def list_sync_runs(self, customer_id: str, asset_id: str, *,
                             page: int, page_size: int) -> Tuple[List[AssetSyncRunORM], int]:
        await self._get(customer_id, asset_id, include_deleted=True)
        base = select(AssetSyncRunORM).where(
            AssetSyncRunORM.customer_id == customer_id,
            AssetSyncRunORM.asset_id == asset_id,
        )
        total = (await self.session.execute(
            select(func.count()).select_from(base.subquery())
        )).scalar() or 0
        rows = (await self.session.execute(
            base.order_by(AssetSyncRunORM.created_at.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )).scalars().all()
        return list(rows), total

    async def get_sync_run(self, customer_id: str, run_id: str) -> AssetSyncRunORM:
        run = (await self.session.execute(
            select(AssetSyncRunORM).where(
                AssetSyncRunORM.customer_id == customer_id,
                AssetSyncRunORM.id == run_id,
            )
        )).scalar_one_or_none()
        if run is None:
            raise APIError(404, "not_found", f"Sync run '{run_id}' not found")
        return run


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
