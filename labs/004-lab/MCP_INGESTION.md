## Dry run

```sh
source .venv/bin/activate

python mcp_ingest.py --url http://localhost:3001/mcp --tool vector_store ../releases --dry-run 2>/dev/null | head -3
```

## Ingest data

```sh
python mcp_ingest.py --url http://localhost:3001/mcp --tool vector_store ../releases
...
Using vector_store(information=..., metadata)
66 chunks
stored 10/66
stored 20/66
stored 30/66
stored 40/66
stored 50/66
stored 60/66
stored 66/66
```

Verify:

```sh
curl -s localhost:6333/collections/abox-nomic | jq '.result.config.params.vectors, .result.points_count'

{
  "size": 768,
  "distance": "Cosine"
}
66
```