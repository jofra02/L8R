import asyncio
import sys
import os
# Ensure src is in path just in case
sys.path.append(os.getcwd())

from src.core.database import get_session
from src.core.orm import ClientContextORM
from sqlalchemy import select

async def verify():
    output = []
    try:
        async with get_session() as session:
            stmt = select(ClientContextORM).where(ClientContextORM.customer_id == "fake_client")
            context = (await session.execute(stmt)).scalars().first()
            
            if not context:
                output.append("FAILURE: No ClientContext found for fake_client")
            else:
                inv = context.content.get("inventory", [])
                ids = [item['id'] for item in inv]
                output.append(f"Inventory IDs: {ids}")
                
                fgt_casa = next((i for i in inv if i['id'] == 'fgt_casa'), None)
                if fgt_casa:
                    output.append("SUCCESS: found fgt_casa")
                    
                    # Verify IP is mapped to metadata
                    ip = fgt_casa['metadata'].get('ip')
                    if ip == "192.168.241.1":
                        output.append(f"SUCCESS: IP mapped correctly: {ip}")
                    else:
                        output.append(f"FAILURE: IP incorrect: {ip}")

                    # Verify Token is REMOVED
                    token = fgt_casa['metadata'].get('token')
                    if not token:
                        output.append("SUCCESS: Token is absent (Clean Context)")
                    else:
                        output.append(f"FAILURE: Token found in metadata: {token[:10]}...")
                else:
                    output.append("FAILURE: fgt_casa not found")

    except Exception as e:
        output.append(f"EXCEPTION: {e}")
        import traceback
        output.append(traceback.format_exc())

    with open("verify_result.txt", "w") as f:
        f.write("\n".join(output))

if __name__ == "__main__":
    asyncio.run(verify())
