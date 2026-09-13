---
adr_id: "0001"
comments:
    - author: ""
      comment: "1"
      date: "2026-09-13 14:41:09"
status: decided
title: ClusterObserver
---

## <a name="question"></a> Context and Problem Statement

How Kubernetes operator can reliably govern multiple clusters with less operational overhead?

## <a name="options"></a> Considered Options
1. <a name="option-1"></a> Kubernetes operator can adapt Kubernetes Native agents, utilizing nomic-embeded-text-v1.5 Matryoshka model
2. <a name="option-2"></a> Kubernetes operator can adapt Kubernetes Native agents, utilizing sentence-transformers MatryoshkaLoss available for training custom models
3. <a name="option-3"></a> Kubernetes operator can adapt Kubernetes Native agents, utilizing OpenAI text-embedding-3-small (1536D), text-embedding-3-large (3072D) — support dimensions API parameter

## <a name="criteria"></a> Decision Drivers
1. <a name="criterion-1"></a> Data sovereignty / air-gapped compatibility — embeddings process infrastructure, security, and configuration data across managed clusters; the solution must not require sending this data outside the perimeter (critical for regulated or air-gapped environments where the operator governs multiple customer clusters)
2. <a name="criterion-2"></a> Operational footprint per cluster — the problem statement explicitly calls for "less operational overhead"; the solution must not require a heavy inference stack (GPU fleet, Python/PyTorch runtime) deployed per managed cluster
3. <a name="criterion-3"></a> Native integration with Go-based operator tooling — most Kubernetes operators are built on Go (operator-sdk, controller-runtime); the solution should be easy to call from a Go controller (sidecar HTTP server or bindings) without a mandatory dependency on the Python ecosystem
4. <a name="criterion-4"></a> Network dependency / availability — governance logic should not degrade because of an unavailable external API (rate limits, outages, latency to a cloud provider) during critical multi-cluster operations
5. <a name="criterion-5"></a> Embedding dimensionality flexibility — ability to adjust vector size to the data volume of a specific cluster (small edge cluster vs. large production cluster) without retraining or swapping the model
6. <a name="criterion-6"></a> Cost model at scale — cost should scale predictably with the number of clusters/event volume, without per-token/per-call billing that becomes unpredictable when managing tens or hundreds of clusters
7. <a name="criterion-7"></a> Reproducibility / version pinning — the model and its behavior must be deterministically pinned (specific version/checksum) so that the operator's governance decisions are reproducible and auditable, without silent changes to a cloud-hosted model under the same version string
8. <a name="criterion-8"></a> Maintenance overhead / need for custom training — the solution should not require the operator maintainers to run their own ML lifecycle (dataset collection, fine-tuning, retraining) if an off-the-shelf model already covers the need
9. <a name="criterion-9"></a> Licensing for redistribution — if the operator is shipped as a product to third parties (multi-tenant governance), the model license must permit commercial redistribution bundled with the operator
10. <a name="criterion-10"></a> Latency for in-loop decisions — if embeddings are used in real time inside the reconciliation loop (not only offline analysis), latency must be acceptable without a network round trip to an external API

## <a name="decision"></a> Decision Outcome

Chosen option: **"nomic-embed-text-v1.5 Matryoshka model" (Option 1)**, because it is the only option that scores strongly across the two criteria weighted highest by the problem statement — operational footprint (criterion 2) and freedom from custom ML maintenance (criterion 8) — while also satisfying data-sovereignty and reproducibility requirements that Option 3 fails outright.

### Decision Matrix

Scoring: 1 (poor fit) – 5 (excellent fit). Weight reflects relative importance for this problem statement (governing multiple clusters with less operational overhead).

| # | Criterion | Weight | Option 1: nomic-embed-text-v1.5 | Option 2: sentence-transformers + MatryoshkaLoss (custom-trained) | Option 3: OpenAI text-embedding-3 |
|---|---|---|---|---|---|
| 1 | Data sovereignty / air-gapped | 5 | 5 | 5 | 1 |
| 2 | Operational footprint per cluster | 5 | 5 | 2 | 5 |
| 3 | Native integration with Go operator tooling | 3 | 4 | 3 | 4 |
| 4 | Network dependency / availability | 4 | 5 | 5 | 2 |
| 5 | Embedding dimensionality flexibility | 4 | 5 | 3 | 5 |
| 6 | Cost model at scale | 4 | 5 | 4 | 2 |
| 7 | Reproducibility / version pinning | 4 | 5 | 5 | 2 |
| 8 | Maintenance overhead / custom training | 5 | 5 | 1 | 5 |
| 9 | Licensing for redistribution | 3 | 5 | 4 | 3 |
| 10 | Latency for in-loop decisions | 3 | 4 | 4 | 2 |
| | **Weighted total** | | **196** | **135** | **129** |

*(Weighted total = Σ score × weight per option. Max possible = 5 × Σweights = 5 × 40 = 200.)*

### Consequences

- Good, because the operator can run fully self-hosted (via `llama.cpp`/GGUF), keeping cluster data inside the perimeter and avoiding per-call cloud costs at scale.
- Good, because Matryoshka truncation lets the operator tune vector size per cluster tier (edge vs. production) without retraining or model swaps.
- Bad, because the model ceiling on raw retrieval quality is lower than large proprietary models (OpenAI text-embedding-3-large); this should be re-evaluated if retrieval accuracy proves insufficient for high-stakes security scenarios.
- Bad, because `nomic-bert` is a less mainstream architecture in the Go/K8s tooling ecosystem than plain LLM backends, so the specific `llama.cpp` version used must be pinned and validated rather than upgraded blindly.

### Rejected options

- **Option 2 (sentence-transformers + MatryoshkaLoss, custom-trained)** — rejected primarily on criterion 8 (maintenance overhead): it requires the team to own a full ML training lifecycle (labeled data, fine-tuning, ongoing retraining) that directly contradicts the "less operational overhead" goal in the problem statement, even though it scores well on data sovereignty and reproducibility.
- **Option 3 (OpenAI text-embedding-3-small/large)** — rejected primarily on criterion 1 (data sovereignty) and criterion 4 (network dependency): sending multi-cluster infrastructure and security data to an external API is unacceptable for governance use cases involving regulated or air-gapped clusters, and reconciliation-loop logic should not depend on external API availability. The native `dimensions` parameter (criterion 5) and low maintenance (criterion 8) are real advantages, but do not offset the sovereignty and availability risk for this problem statement.
## <a name="outcome"></a> Outcome
We decided for [Option 1](#option-1) because: it is the only option that scores strongly across the two criteria weighted highest by the problem statement — operational footprint (criterion 2) and freedom from custom ML maintenance (criterion 8) — while also satisfying data-sovereignty and reproducibility requirements that Option 3 fails outright

## <a name="comments"></a> Comments
<a name="comment-1"></a>1. (2026-09-13 14:41:09) : marked decision as decided
