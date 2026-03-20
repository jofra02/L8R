import asyncio
import sys
import os
from langchain_text_splitters import RecursiveCharacterTextSplitter
from src.core.qdrant import vector_store


async def seed_kb(directory: str, customer_id: str, chunk_size: int = 1000, chunk_overlap: int = 100):
    """Seed Knowledge Base from a directory of files via add_texts()."""
    print(f"Seeding KB for {customer_id} from {directory}")

    if not os.path.exists(directory):
        print(f"Directory {directory} does not exist.")
        return

    documents = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith((".md", ".txt", ".json")):
                path = os.path.join(root, file)
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()
                    ext = os.path.splitext(file)[1].lstrip(".")
                    documents.append({"source": file, "text": text, "ext": ext})

    print(f"Found {len(documents)} documents.")

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
    )

    total_chunks = 0
    for doc in documents:
        chunks = text_splitter.split_text(doc["text"])
        print(f"Processing {doc['source']}: {len(chunks)} chunks")

        ids = [
            vector_store._generate_id(f"{customer_id}-{doc['source']}-{i}")
            for i in range(len(chunks))
        ]
        metadatas = [
            {
                "source": doc["source"],
                "doc_type": doc["ext"],
                "chunk_index": i,
                "total_chunks": len(chunks),
            }
            for i in range(len(chunks))
        ]
        await vector_store.add_texts(
            collection_name="knowledge_base",
            texts=chunks,
            metadatas=metadatas,
            ids=ids,
            customer_id=customer_id,
            source_type="kb_article",
        )
        total_chunks += len(chunks)

    print(f"Seeding complete. {total_chunks} chunks indexed.")


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python -m src.utils.seed_kb --dir <dir> --customer-id <id> [--chunk-size 1000] [--chunk-overlap 100]")
        sys.exit(1)

    args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
    dir_path = args.get("--dir")
    cid = args.get("--customer-id")
    cs = int(args.get("--chunk-size", "1000"))
    co = int(args.get("--chunk-overlap", "100"))

    if dir_path and cid:
        asyncio.run(seed_kb(dir_path, cid, cs, co))
    else:
        print("Invalid arguments. Required: --dir and --customer-id")
