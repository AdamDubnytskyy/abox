# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/)
and this project adheres to [Semantic Versioning](http://semver.org/).

## [0.0.10] - 2026-09-30

### Added

- [003-ADR](https://github.com/AdamDubnytskyy/abox/blob/main/cluster-observer/AD0003-vector-retrieval-embeddings.md)

- [Official Qdrant MCP server Dockerfile](https://github.com/AdamDubnytskyy/abox/tree/main/images/qdrant-mcp-official)

- [Official Qdrant MCP server image](https://github.com/users/AdamDubnytskyy/packages/container/package/abox%2Fmcp-server-qdrant)

- [qdrant-mcp-official MCPServer manifest](./releases/011-qdrant-mcp-official.yaml)

- [retrieval-agent-qdrant-mcp-official Agent manifest](./releases/012-retrieval-agent-official.yaml)

- [004-lab](./labs/004-lab/)

    - [INDEXING](./labs/004-lab/INDEXING.md)
    - [indexing-script](./scripts/index.py)


    - [MCP_INGESTION](./labs/004-lab/MCP_INGESTION.md)
    - [mcp-ingestion-script](./scripts/mcp_ingest.py)


    - [EVALUATION](./labs/004-lab/EVALUATION.md)
    - [results](./labs/004-lab/artifacts/)
    - [evaluation-script](./scripts/eval_retrieval.py)
    - [evaluation-questions](./scripts/questions.yaml)

## [0.0.9] - 2026-09-13

### Added

- Commands to [Makefile](./labs/003-lab/Makefile) in [003-lab](./labs/003-lab/) for embeddings sidecar deployment

## [0.0.8] - 2026-09-13

### Added

- [ADR0002](./cluster-observer/AD0002-embedding-model-deployment-topology-in-kubernetes-cluster.md)

## [0.0.7] - 2026-09-13

### Changed

- Renamed [AD0001](./cluster-observer/AD0001-matryoshka-embedding-model-for-the-cluster-observer-kubernetes-native-agent.md)

## [0.0.6] - 2026-09-13

### Added

- [Architectural Decision Record](./cluster-observer/AD0001-matryoshka-embedding-model-for-the-cluster-observer-kubernetes-native-agent.md)

## [0.0.5] - 2026-09-13

### Added

- 003-lab `Makefile`
- 003-lab scripts

### Changed

- 003-lab llama-server.md

## [0.0.4] - 2026-09-12

### Changed

- Updated 003-lab todo.md

## [0.0.3] - 2026-09-12

### Added

- Matryoshka Embeddings evaluation script
- todo.md

## [0.0.2] - 2026-09-12

### Added

- LLaMA server in embedding mode, load Nomic Embed Text v1.5 using the Q4_K_M quantized model

## [0.0.1] - 2026-09-10

### Added

- Provision Infrastructure

[0.0.9]: https://github.com/AdamDubnytskyy/abox/compare/0.0.8...0.0.9
[0.0.8]: https://github.com/AdamDubnytskyy/abox/compare/0.0.7...0.0.8
[0.0.7]: https://github.com/AdamDubnytskyy/abox/compare/0.0.6...0.0.7
[0.0.6]: https://github.com/AdamDubnytskyy/abox/compare/0.0.5...0.0.6
[0.0.5]: https://github.com/AdamDubnytskyy/abox/compare/0.0.4...0.0.5
[0.0.4]: https://github.com/AdamDubnytskyy/abox/compare/0.0.3...0.0.4
[0.0.3]: https://github.com/AdamDubnytskyy/abox/compare/0.0.2...0.0.3
[0.0.2]: https://github.com/AdamDubnytskyy/abox/compare/0.0.1...0.0.2
[0.0.1]: https://github.com/AdamDubnytskyy/abox/releases/tag/0.0.1