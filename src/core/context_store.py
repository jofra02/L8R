from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, update
from typing import Optional
from src.core.models import ClientContext
from src.core.orm import ClientContextORM
import logging

logger = logging.getLogger(__name__)

class ContextStore:
    """Manages long-term Client Context persistence.

    Since the Asset Inventory migration the relational assets/asset_relations
    tables are authoritative for inventory and dependencies: reads overlay
    them onto the blob (context_adapter), writes ignore those two keys.
    The blob keeps owning baselines / known_changes / policies.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_active_context(self, customer_id: str) -> Optional[ClientContext]:
        """Retrieve the latest active context, inventory assembled from assets."""
        stmt = (
            select(ClientContextORM)
            .where(
                ClientContextORM.customer_id == customer_id,
                ClientContextORM.is_active == True
            )
            .order_by(desc(ClientContextORM.created_at))
            .limit(1)
        )

        result = await self.session.execute(stmt)
        orm_obj = result.scalar_one_or_none()

        content = dict(orm_obj.content) if orm_obj else None

        # Authoritative overlay: components/dependencies come from the asset
        # tables; stale blob copies (pre-migration snapshots) are inert.
        try:
            from src.assets.context_adapter import assemble_inventory
            components, dependencies = await assemble_inventory(self.session, customer_id)
        except Exception as e:
            logger.error(f"Asset overlay failed for {customer_id}: {e}")
            components, dependencies = None, None

        if content is None:
            if not components:
                return None
            content = {"customer_id": customer_id, "version": "0"}

        if components is not None:
            content["inventory"] = components
            content["dependencies"] = dependencies

        # Hydrate Pydantic model
        try:
            return ClientContext(**content)
        except Exception as e:
            logger.error(f"Failed to hydrate ClientContext for {customer_id}: {e}")
            return None

    async def save_context(self, context: ClientContext) -> ClientContextORM:
        """Save a new version of the client context. Deactivates previous active versions.

        inventory/dependencies are NOT persisted here — the asset tables are
        authoritative (write assets via AssetService). Passing non-empty
        values logs a warning and drops them.
        """
        content = context.model_dump()
        if content.get("inventory") or content.get("dependencies"):
            logger.warning(
                f"save_context({context.customer_id}): inventory/dependencies are "
                f"managed in the assets tables; dropping them from the blob"
            )
        content["inventory"] = []
        content["dependencies"] = []

        # Deactivate all previous active versions for this tenant
        await self.session.execute(
            update(ClientContextORM)
            .where(
                ClientContextORM.customer_id == context.customer_id,
                ClientContextORM.is_active == True
            )
            .values(is_active=False)
        )

        orm_obj = ClientContextORM(
            customer_id=context.customer_id,
            version=context.version,
            content=content,
            is_active=True
        )

        self.session.add(orm_obj)
        await self.session.commit()
        return orm_obj
