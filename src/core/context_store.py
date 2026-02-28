from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, update
from typing import Optional
from src.core.models import ClientContext
from src.core.orm import ClientContextORM
import logging

logger = logging.getLogger(__name__)

class ContextStore:
    """Manages long-term Client Context persistence."""
    
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_active_context(self, customer_id: str) -> Optional[ClientContext]:
        """Retrieve the latest active context for a customer."""
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
        
        if not orm_obj:
            return None
            
        # Hydrate Pydantic model
        try:
            return ClientContext(**orm_obj.content)
        except Exception as e:
            logger.error(f"Failed to hydrate ClientContext for {customer_id}: {e}")
            return None

    async def save_context(self, context: ClientContext) -> ClientContextORM:
        """Save a new version of the client context. Deactivates previous active versions."""
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
            content=context.model_dump(),
            is_active=True
        )
        
        self.session.add(orm_obj)
        await self.session.commit()
        return orm_obj
