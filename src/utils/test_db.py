import asyncio
from src.core.database import get_session
from sqlalchemy import text

async def test_connection():
    try:
        async with get_session() as session:
            result = await session.execute(text("SELECT 1"))
            print(f"Connection Successful: {result.scalar()}")
            
            result = await session.execute(text("SELECT count(*) FROM platform_tenants"))
            print(f"PlatformTenants count: {result.scalar()}")
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_connection())
