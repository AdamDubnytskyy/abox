# ADR: Embedding model and MCP server for agentic vector retrieval

- [ADR:Embedding model and MCP server for agentic vector retrieval](../../cluster-observer/AD0003-vector-retrieval-embeddings.md)

## Run te full evaluation

```sh
source .venv/bin/activate
pip install "mcp<2" pyyaml

python eval_retrieval.py questions.yaml \
  --target minilm=http://localhost:3000/mcp,qdrant-find \
  --target nomic=http://localhost:3001/mcp,vector_find

```

See results: 
- [eval-20260930T193012Z.md](./artifacts/eval-20260930T193012Z.md)
- [eval-20260930T193012Z.json](./artifacts/eval-20260930T193012Z.json)