"""AssetProductService: global product catalog CRUD.

The catalog ("FortiGate", "ESXi", ...) is platform reference data, not
tenant data — no customer_id anywhere. Assets store the product name
denormalized (assets.product_name, no FK); this module is the single
validation point for that string:

- create/update/import of an asset resolve the value via ensure_product()
  (canonical casing or 422);
- rename_product() propagates via bulk UPDATE across all tenants and
  writes one asset_audit_log row per affected asset so History stays
  truthful;
- delete_product() is blocked (409) while any non-deleted asset
  references the name.

Provenance is deliberately NOT restamped on rename: the value's origin is
still the original manual edit, only its spelling changed.
"""

from __future__ import annotations

import uuid
from typing import List, Optional, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.exceptions import APIError
from src.core.orm import AssetAuditLogORM, AssetORM, AssetProductORM


async def ensure_product(session: AsyncSession, name: str) -> str:
    """Return the canonical-cased catalog name, or 422 if not registered."""
    row = (await session.execute(
        select(AssetProductORM.name)
        .where(func.lower(AssetProductORM.name) == name.strip().lower())
    )).first()
    if row is None:
        raise APIError(
            422, "validation_error",
            f"Unknown product_name '{name}': not in the product catalog",
        )
    return row[0]


class AssetProductService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _get(self, product_id: str) -> AssetProductORM:
        product = await self.session.get(AssetProductORM, product_id)
        if product is None:
            raise APIError(404, "not_found", f"Product '{product_id}' not found")
        return product

    async def _usage_count(self, name: str) -> int:
        return (await self.session.execute(
            select(func.count()).select_from(AssetORM)
            .where(AssetORM.product_name == name, AssetORM.deleted_at.is_(None))
        )).scalar_one()

    async def _check_name_free(self, name: str, exclude_id: Optional[str] = None) -> None:
        stmt = select(AssetProductORM.id).where(
            func.lower(AssetProductORM.name) == name.lower())
        if exclude_id:
            stmt = stmt.where(AssetProductORM.id != exclude_id)
        if (await self.session.execute(stmt)).first() is not None:
            raise APIError(409, "conflict", f"Product '{name}' already exists")

    @staticmethod
    def _normalize(name: str) -> str:
        name = name.strip()
        if not name:
            raise APIError(422, "validation_error", "Product name must not be empty")
        return name

    async def list_products(self, include_usage: bool = False) -> List[dict]:
        products = (await self.session.execute(
            select(AssetProductORM).order_by(func.lower(AssetProductORM.name))
        )).scalars().all()
        usage = {}
        if include_usage:
            rows = (await self.session.execute(
                select(AssetORM.product_name, func.count())
                .where(AssetORM.product_name.is_not(None),
                       AssetORM.deleted_at.is_(None))
                .group_by(AssetORM.product_name)
            )).all()
            usage = dict(rows)
        return [
            {
                "id": p.id,
                "name": p.name,
                "created_at": p.created_at,
                "updated_at": p.updated_at,
                "created_by": p.created_by,
                "usage_count": usage.get(p.name, 0) if include_usage else None,
            }
            for p in products
        ]

    async def create_product(self, name: str, actor: str) -> AssetProductORM:
        name = self._normalize(name)
        await self._check_name_free(name)
        product = AssetProductORM(id=uuid.uuid4().hex, name=name, created_by=actor)
        self.session.add(product)
        await self.session.commit()
        return product

    async def rename_product(self, product_id: str, new_name: str,
                             actor: str) -> Tuple[AssetProductORM, int]:
        product = await self._get(product_id)
        new_name = self._normalize(new_name)
        old_name = product.name
        if new_name == old_name:
            return product, 0
        await self._check_name_free(new_name, exclude_id=product_id)

        affected = (await self.session.execute(
            select(AssetORM.id, AssetORM.customer_id)
            .where(AssetORM.product_name == old_name, AssetORM.deleted_at.is_(None))
        )).all()
        if affected:
            await self.session.execute(
                update(AssetORM)
                .where(AssetORM.product_name == old_name,
                       AssetORM.deleted_at.is_(None))
                .values(product_name=new_name, updated_by=actor)
            )
            self.session.add_all([
                AssetAuditLogORM(
                    customer_id=customer_id,
                    asset_id=asset_id,
                    actor=actor,
                    action="updated",
                    changes={"product_name": {"old": old_name, "new": new_name}},
                )
                for asset_id, customer_id in affected
            ])

        product.name = new_name
        await self.session.commit()
        return product, len(affected)

    async def delete_product(self, product_id: str) -> None:
        product = await self._get(product_id)
        in_use = await self._usage_count(product.name)
        if in_use:
            raise APIError(
                409, "conflict",
                f"Product '{product.name}' is referenced by {in_use} asset(s); "
                "reassign or delete them first",
            )
        await self.session.delete(product)
        await self.session.commit()
