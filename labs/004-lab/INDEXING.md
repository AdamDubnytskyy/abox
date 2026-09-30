# Ingestion script

    Index k8s manifests into Qdrant Vector Search Engine

- [index.py](../../scripts/index.py)

## Prerequisites
```sh
python3 -m venv .venv
source .venv/bin/activate
pip install fastembed qdrant-client pyyaml
```
---
## Dry-run

```sh
python index.py ../releases --dry-run
```

## Indexing
---
```sh
export QDRANT_URL=http://localhost:6333
export COLLECTION_NAME=abox-minilm
python index.py ../releases --source gitops --prune
```

Verify:
```sh
curl -s localhost:6333/collections/abox-minilm | jq '.result.points_count'
...
$ 65 # 
```