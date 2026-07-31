"""Asset import/export: CSV + XLSX export, CSV/JSON non-destructive import.

Export honors the exact list filters. Import upserts by a caller-chosen
match key with per-row results and a dry-run mode — never a destructive
replace (unlike the legacy /inventory/import).
"""

from __future__ import annotations

import csv
import io as _io
import json
import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import select

from src.api.exceptions import APIError
from src.api.schemas.assets import (
    AssetCreate,
    AssetUpdate,
    ImportResponse,
    ImportRowResult,
)
from src.assets import registry
from src.assets.service import AssetService
from src.assets.validation import validate_attributes
from src.config import settings
from src.core.orm import AssetORM, AssetProductORM

logger = logging.getLogger(__name__)

EXPORT_COMMON_COLUMNS = [
    "id", "name", "ref", "asset_type", "status", "criticality",
    "manufacturer", "model", "product_name", "serial_number", "location", "owner",
    "ip_address", "fqdn", "tags", "purchase_date", "warranty_expires",
    "eol_date", "managed", "sync_status", "last_synced_at",
    "external_source", "external_id", "created_at", "updated_at",
]

IMPORT_MATCH_KEYS = ("id", "ref", "serial_number", "external_id")

# Columns accepted on import that map straight onto AssetCreate fields.
_IMPORT_SCALAR_FIELDS = (
    "id", "name", "ref", "asset_type", "manufacturer", "model", "product_name",
    "serial_number", "location", "owner", "ip_address", "fqdn",
    "status", "criticality", "purchase_date", "warranty_expires", "eol_date",
)


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


async def build_export(
    session,
    assets: List[AssetORM],
) -> Tuple[List[str], List[List[Any]]]:
    """Flatten assets to (headers, rows).

    Declared attribute keys of the exported asset types become ``attr.<key>``
    columns (deterministic order); undeclared attribute keys land in a final
    ``attributes_json`` column.
    """
    types = await registry.get_latest_types(session)
    declared: List[str] = []
    seen = set()
    for asset in assets:
        type_def = types.get(asset.asset_type)
        if not type_def:
            continue
        for f in type_def.fields:
            if f.key not in seen:
                seen.add(f.key)
                declared.append(f.key)
    declared.sort()

    headers = EXPORT_COMMON_COLUMNS + [f"attr.{k}" for k in declared] + ["attributes_json"]
    rows: List[List[Any]] = []
    for asset in assets:
        attributes = dict(asset.attributes or {})
        attributes.pop("legacy_role", None)
        row = []
        for col in EXPORT_COMMON_COLUMNS:
            value = getattr(asset, col)
            if col == "tags":
                value = ";".join(value or [])
            row.append(_cell(value))
        rest = dict(attributes)
        for key in declared:
            row.append(_cell(rest.pop(key, None)))
        row.append(json.dumps(rest, ensure_ascii=False) if rest else "")
        rows.append(row)
    return headers, rows


def render_csv(headers: List[str], rows: List[List[Any]]) -> str:
    buf = _io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return buf.getvalue()


def render_xlsx(headers: List[str], rows: List[List[Any]]) -> bytes:
    from openpyxl import Workbook  # write_only bounds memory on large exports

    wb = Workbook(write_only=True)
    ws = wb.create_sheet("assets")
    ws.append(headers)
    for row in rows:
        ws.append(row)
    out = _io.BytesIO()
    wb.save(out)
    return out.getvalue()


# --- Import ---

def parse_csv_rows(text: str) -> List[Dict[str, Any]]:
    reader = csv.DictReader(_io.StringIO(text))
    rows: List[Dict[str, Any]] = []
    for raw in reader:
        row: Dict[str, Any] = {}
        attributes: Dict[str, Any] = {}
        for key, value in (raw or {}).items():
            if key is None:
                continue
            key = key.strip()
            if value is None or str(value).strip() == "":
                continue
            value = str(value).strip()
            if key.startswith("attr."):
                attributes[key[5:]] = _parse_scalar(value)
            elif key == "tags":
                row["tags"] = [t.strip() for t in value.split(";") if t.strip()]
            elif key == "attributes_json":
                try:
                    attributes.update(json.loads(value))
                except (TypeError, ValueError):
                    row.setdefault("_errors", []).append("attributes_json: invalid JSON")
            elif key in _IMPORT_SCALAR_FIELDS:
                row[key] = value
        if attributes:
            row["attributes"] = attributes
        rows.append(row)
    return rows


def _parse_scalar(value: str) -> Any:
    low = value.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    if value[:1] in ("{", "["):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            pass
    return value


async def _find_by_match_key(session, customer_id: str, match_key: str,
                             value: str) -> Optional[AssetORM]:
    column = getattr(AssetORM, match_key)
    stmt = select(AssetORM).where(
        AssetORM.customer_id == customer_id,
        column == value,
        AssetORM.deleted_at.is_(None),
    )
    matches = (await session.execute(stmt)).scalars().all()
    if len(matches) > 1:
        raise APIError(409, "conflict",
                       f"match_key {match_key}='{value}' matches {len(matches)} assets")
    return matches[0] if matches else None


async def import_assets(
    session,
    customer_id: str,
    rows: List[Dict[str, Any]],
    *,
    match_key: str,
    dry_run: bool,
    actor: str,
) -> ImportResponse:
    if match_key not in IMPORT_MATCH_KEYS:
        raise APIError(422, "validation_error",
                       f"match_key must be one of {IMPORT_MATCH_KEYS}")
    if len(rows) > settings.ASSETS_IMPORT_MAX_ROWS:
        raise APIError(422, "validation_error",
                       f"Import exceeds {settings.ASSETS_IMPORT_MAX_ROWS} rows")

    service = AssetService(session)
    types = await registry.get_latest_types(session)
    # product_name is constrained to the global catalog; preload once so
    # dry-run reports unknown products as row errors without touching it.
    products = {
        n.lower(): n
        for n in (await session.execute(select(AssetProductORM.name))).scalars()
    }
    results: List[ImportRowResult] = []
    created = updated = skipped = failed = 0

    for index, row in enumerate(rows, start=1):
        errors: List[str] = list(row.pop("_errors", []))
        try:
            match_value = row.get(match_key)
            existing = None
            if match_value:
                existing = await _find_by_match_key(session, customer_id,
                                                    match_key, str(match_value))

            asset_type = row.get("asset_type") or (existing.asset_type if existing else None)
            if not asset_type:
                errors.append("asset_type is required")
            elif asset_type not in types:
                errors.append(f"unknown asset_type '{asset_type}'")
            elif row.get("attributes"):
                base_keys = tuple((existing.attributes or {}).keys()) if existing else ()
                _, attr_errors = validate_attributes(
                    types[asset_type], row["attributes"], allowed_extra_keys=base_keys
                )
                errors.extend(attr_errors)

            if row.get("product_name"):
                canonical = products.get(str(row["product_name"]).strip().lower())
                if canonical is None:
                    errors.append(f"unknown product_name '{row['product_name']}':"
                                  " not in the product catalog")
                else:
                    row["product_name"] = canonical

            if not existing and not row.get("name"):
                errors.append("name is required for new assets")

            if errors:
                failed += 1
                results.append(ImportRowResult(row=index, action="error", errors=errors))
                continue

            if dry_run:
                action = "update" if existing else "create"
                if action == "update":
                    updated += 1
                else:
                    created += 1
                results.append(ImportRowResult(
                    row=index, action=action,
                    asset_id=existing.id if existing else None,
                ))
                continue

            if existing:
                payload = AssetUpdate(**{
                    k: v for k, v in row.items()
                    if k in AssetUpdate.model_fields and k != "id"
                })
                asset = await service.update_asset(customer_id, existing.id,
                                                   payload, actor, auto_enrich=False)
                service._audit(asset, actor, "imported", {})
                await session.commit()
                updated += 1
                results.append(ImportRowResult(row=index, action="update", asset_id=asset.id))
            else:
                payload = AssetCreate(**{
                    k: v for k, v in row.items() if k in AssetCreate.model_fields
                })
                asset = await service.create_asset(customer_id, payload, actor,
                                                   auto_enrich=False)
                service._audit(asset, actor, "imported", {})
                await session.commit()
                created += 1
                results.append(ImportRowResult(row=index, action="create", asset_id=asset.id))
        except APIError as e:
            failed += 1
            results.append(ImportRowResult(row=index, action="error",
                                           errors=[f"{e.error}: {e.detail}"]))
        except Exception as e:  # defensive: one bad row never kills the batch
            logger.warning(f"asset import row {index} failed: {e}")
            failed += 1
            results.append(ImportRowResult(row=index, action="error", errors=[str(e)]))

    return ImportResponse(
        dry_run=dry_run,
        total=len(rows),
        created=created,
        updated=updated,
        skipped=skipped,
        failed=failed,
        rows=results,
    )
