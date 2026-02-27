import asyncio
import sys
import os
from typing import List, Dict, Any
from src.core.qdrant import vector_store
from qdrant_client import models
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Initialize Embeddings (Assuming OPENAI_API_KEY is set)
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

async def seed_kb(directory: str, customer_id: str):
    """Seed Knowledge Base from a directory of files."""
    print(f"Seeding KB for {customer_id} from {directory}")
    
    if not os.path.exists(directory):
        print(f"Directory {directory} does not exist.")
        return

    # 1. Read Files
    documents = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith((".md", ".txt", ".json")):
                path = os.path.join(root, file)
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()
                    documents.append({"source": file, "text": text})

    print(f"Found {len(documents)} documents.")

    # 2. Chunking
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=100,
        length_function=len,
    )
    
    points = []
    
    for doc in documents:
        chunks = text_splitter.split_text(doc["text"])
        print(f"Processing {doc['source']}: {len(chunks)} chunks")
        
        # Batch Embed (for efficiency, could batch across docs too)
        # For simplicity, embed per doc's chunks
        vectors = await embeddings.aembed_documents(chunks)
        
        for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
            point_id = f"{doc['source']}_{i}" # Simple determinist ID logic
            # Use UUID in production or hash
            import uuid
            point_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, point_id))
            
            points.append(models.PointStruct(
                id=point_uuid,
                vector=vector,
                payload={
                    "customer_id": customer_id,
                    "source": doc["source"],
                    "text": chunk,
                    "chunk_index": i
                }
            ))

    # 3. Upsert to Qdrant
    if points:
        print(f"Upserting {len(points)} points to Qdrant...")
        # Upsert in batches of 100
        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i:i+batch_size]
            await vector_store.upsert_raw(
                collection_name="knowledge_base",
                points=batch,
                customer_id=customer_id
            )
        print("Seeding Complete.")
    else:
        print("No content to seed.")

if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python seed_kb.py --dir <dir> --customer-id <id>")
        sys.exit(1)
        
    # Simple arg parse
    args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
    dir_path = args.get("--dir")
    cid = args.get("--customer-id")
    
    if dir_path and cid:
        asyncio.run(seed_kb(dir_path, cid))
    else:
        print("Invalid arguments.")
