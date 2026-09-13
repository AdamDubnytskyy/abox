---
adr_id: "0002"
comments:
    - author: "Oleh Adam Dubnytskyy"
      comment: "1"
      date: "2026-09-13 19:58:26"
related:
    - "0001"
status: decided
supersedes: null
title: Embedding Model Deployment Topology in Kubernetes Cluster
---

## <a name="question"></a> Context and Problem Statement

ADR-0001 selected `nomic-embed-text-v1.5` (Matryoshka, served via `llama.cpp`, GGUF `Q4_K_M`) as the embedding model for the ClusterObserver agent. This ADR addresses a separate question: **how should this model be deployed and reached inside the Kubernetes cluster(s) the operator governs?**

**Scenario:** run this agent across multiple Kubernetes clusters and govern them with less operational overhead — the same driver behind ADR-0001's problem statement. Whatever deployment topology is chosen here must not turn "add one more managed cluster" into a multi-step infrastructure project.

The embedding model is called by multiple in-cluster consumers (reconciliation controllers, the agent's retrieval pipeline, ad-hoc CLI/debug tooling) whenever they need to embed metrics, events, manifests, or query text for semantic search.

## <a name="options"></a> Considered Options

1. <a name="option-1"></a> **Sidecar mode** — run `llama-server` (serving `nomic-embed-text-v1.5`) as a lightweight embedding instance reachable without crossing a cluster boundary. Recommended granularity: one shared instance per operational cluster (a small in-cluster `Deployment` + `Service`), not strictly one per pod — see the Tokenomics section for why.
2. <a name="option-2"></a> **llm-d via Helm** — deploy the model through [llm-d](https://llm-d.ai), a CNCF Sandbox, Kubernetes-native distributed inference stack (built on vLLM, the Gateway API Inference Extension, and Envoy), installed via its official Helm charts as a shared, cluster-level inference service.

## <a name="criteria"></a> Decision Drivers

*(Cleaned up from an earlier, longer list — consolidated to the drivers that actually differentiate the two options for this workload; a duplicate entry for "Call latency and locality" was merged into one.)*

1. <a name="criterion-1"></a> **Scalability** — how well each option handles growth in the dimension that actually matters for ClusterObserver: the *breadth* of many managed clusters and organizations, rather than the *depth* of request throughput to a single endpoint.
2. <a name="criterion-2"></a> **Operational complexity** — how much new infrastructure must be installed, learned, and kept healthy: a Helm chart, CRDs, and a routing layer (llm-d), versus one lightweight component reachable without crossing a cluster boundary (sidecar).
3. <a name="criterion-3"></a> **Call latency and locality** — whether embedding calls stay local to the cluster's own network, or require a hop to a shared, possibly cross-cluster, endpoint.
4. <a name="criterion-4"></a> **Security** — attack surface (number of network-facing components introduced), blast radius if one instance is compromised, and the ease of keeping the deployed model/runtime version patched consistently.
5. <a name="criterion-5"></a> **Multi-tenant / cross-organization data isolation** — if ClusterObserver's control plane governs clusters belonging to more than one organization, whether the topology inherently keeps each organization's raw data inside its own trust boundary, or requires raw data to cross into a shared component serving multiple tenants.

## <a name="decision"></a> Decision Outcome

Chosen option: **"Sidecar mode" (Option 1)**, because the embedding workload (a 137M-parameter, CPU-friendly, single-shape model) does not need the architecture llm-d exists to provide, and the top-priority driver — Scalability — favors a topology whose overhead stays flat as clusters and organizations are added. The sidecar approach also wins on Security and multi-tenant isolation, both of which become sharper concerns once the deployment spans a control plane governing multiple organizations' clusters (see the Scenario Walkthroughs below).

### Decision Matrix

Scoring: 1 (poor fit) – 5 (excellent fit).

| # | Criterion | Weight | Option 1: Sidecar mode | Option 2: llm-d via Helm |
|---|---|---|---|---|
| 1 | Scalability | 5 | 4 | 3 |
| 2 | Operational complexity | 4 | 5 | 2 |
| 3 | Call latency and locality | 3 | 5 | 3 |
| 4 | Security | 5 | 4 | 2 |
| 5 | Multi-tenant / cross-organization data isolation | 5 | 5 | 2 |
| | **Weighted total** | | **100** | **52** |

*(Weighted total = Σ score × weight per option. Max possible = 5 × Σweights = 5 × 22 = 110.)*

**On criterion 4 (Security):** the sidecar's smaller attack surface (no new network-facing routing layer, calls stay local) comes with a trade-off — many small, independently-deployed instances mean version/patch drift is a real maintenance concern and should be mitigated with a shared base image or Helm subchart so the runtime version stays centrally controlled even though deployment is decentralized. llm-d centralizes patching into one place, but that same centralization means a single compromised instance has a larger blast radius, and its additional components (Envoy, Gateway API CRDs, vLLM control plane) each add their own attack surface.

### Scenario Walkthrough: Governing Multiple Clusters with Low Operational Overhead

This is the concrete scenario criterion 1 exists to capture: the operator's job is to run and govern the ClusterObserver agent across a growing number of managed clusters, with low operational overhead per cluster added.

**Sidecar mode:**
- Onboarding a new managed cluster means deploying the agent's existing manifests — which already bundle the embedding component — to that cluster. There is no separate embedding-infrastructure decision to make per cluster.
- No cross-cluster inventory of "embedding capacity" to track or capacity-plan; each cluster is fully self-sufficient.
- Operational overhead per additional cluster: effectively zero beyond what is already templated in the agent's own manifests.
- Failure or upgrade blast radius stays per-cluster — a degraded instance in cluster A has no effect on clusters B through Z.

**llm-d via Helm** — this option forks into two sub-scenarios, and both work against the goal:
- *(a) One llm-d installation per managed cluster:* every new cluster now requires installing and operating an entire llm-d stack (Helm release, GPU node pool, Gateway API CRDs, Envoy) in addition to the agent itself — this multiplies the heaviest, most GPU-dependent option by the number of clusters, the opposite of low overhead.
- *(b) One central llm-d installation serving all managed clusters remotely:* this avoids re-installing llm-d per cluster, but now requires exposing that endpoint across every managed cluster's network (cross-cluster connectivity, firewall rules, latency, and a shared external dependency for every reconciliation loop everywhere) — trading per-cluster infrastructure overhead for a new category of overhead, and a new category of security exposure, that sidecar mode never introduces at all.

**Conclusion:** under this exact scenario, sidecar mode's overhead is flat — template once, replicate identically into every new cluster — while llm-d's overhead either multiplies with cluster count (sub-scenario a) or introduces an entirely new operational and security surface, cross-cluster networking (sub-scenario b). Either path directly contradicts "govern multiple clusters with less operational overhead," which is why this scenario is the concrete justification for weighting Scalability as the top decision driver.

### Scenario Walkthrough: Multi-Organization Hub-and-Spoke Deployment

Extending the above: a realistic deployment is not a flat set of consumer pods, but a **control-plane cluster** (hosting the agent's reasoning and retrieval logic) paired with multiple **operational clusters** per organization, and potentially multiple organizations sharing the same control plane:

```
Control plane cluster (indexing & reasoning)
        ▲              ▲              ▲              ▲
   vectors only    vectors only   vectors only   vectors only
        │              │              │              │
 ┌──────┴──────┐┌──────┴──────┐┌──────┴──────┐┌──────┴──────┐
 │ Cluster A1  ││ Cluster A2  ││ Cluster B1  ││ Cluster B2  │
 │ local embed ││ local embed ││ local embed ││ local embed │
 └─────────────┘└─────────────┘└─────────────┘└─────────────┘
      Organization A                  Organization B
```

**Sidecar / edge-embedding (Option 1, cluster-local granularity):** each operational cluster embeds its own metrics/events/configs locally, and only the resulting vectors cross the boundary up to the control plane. Raw data belonging to Organization A never enters the same component as Organization B's raw data; isolation (criterion 5) falls out of the topology itself, with no extra access-control layer required.

**llm-d via Helm (Option 2):** the same two sub-scenarios from the single-org walkthrough reappear, now compounded by organization count:
- *(a) One llm-d per operational cluster:* multiplies the heaviest, GPU-dependent option by (clusters × organizations) — strictly worse than the already-rejected single-org case.
- *(b) One central llm-d shared across all organizations:* requires shipping raw data from every organization's clusters into one shared embedding endpoint. This **commingles multiple organizations' raw infrastructure and security data in a single component** — a direct violation of the data sovereignty principle established as criterion 1 in ADR-0001, and realistically a compliance blocker for any multi-tenant deployment, independent of cost.

**Conclusion:** the edge-embedding pattern is the only one of the two options where cost, security, and trust boundaries scale together, linearly and locally, as both the number of managed clusters and the number of organizations grow. This is the strongest reason — stronger than cost alone — to treat llm-d's centralized model as unsuitable for a multi-organization control plane, not merely more expensive.

### Tokenomics: Cost per Embedding Call

A simplified cost model, in the spirit of "tokenomics" for compute rather than currency:

```
Let:
  N        = number of embedding-serving instances actually provisioned in the
             sidecar case. Recommended granularity is one shared instance per
             operational cluster (not per pod) — see the note below.
  C_cpu    = cost of the CPU/RAM reserved by one instance, per unit time
             (a standing reservation — paid whether or not it is actively serving)
  C_gpu    = cost of the GPU/accelerator-class node(s) required to run llm-d's
             stack, per unit time — the dominant cost term, since llm-d's
             benchmarked paths assume datacenter GPU/TPU-class hardware
  U        = utilization factor: fraction of that provisioned GPU capacity
             actually consumed by embedding calls (typically low for a
             137M-parameter model, since the accelerator is sized for
             batching large generative models, not small embedding requests)

Sidecar total cost   ≈ N × C_cpu                (scales with the number of
                                                  embedding-serving instances
                                                  provisioned, independent of
                                                  call volume)

llm-d total cost     ≈ C_gpu / U                (scales with the cost of keeping
                                                  at least one GPU-class node
                                                  warm, largely independent of
                                                  embedding call volume, since
                                                  GPU nodes are not typically
                                                  provisioned in small fractions)

Break-even (sidecar becomes more expensive than llm-d) when:
  N ≥ (C_gpu / U) / C_cpu
```

**Note on `N`'s granularity.** "Sidecar mode" does not require one instance per consumer *pod*. The recommended granularity is one shared embedding instance **per operational cluster** — a small in-cluster `Deployment` + `Service`, still reached without crossing a cluster boundary, but shared by every pod within that cluster rather than duplicated per pod. Under this granularity, `N` = number of operational clusters, which only strengthens the break-even math below in favor of the sidecar/edge-embedding approach.

Cloud CPU-vCPU vs. GPU-instance pricing commonly differs by roughly one to two orders of magnitude per unit time (exact ratio depends on provider and accelerator class — plug in your own numbers here). Combined with a low `U` (a 137M-parameter CPU-friendly model does not saturate hardware sized for 70B+-parameter generative serving), the break-even `N` typically lands well beyond the realistic operational-cluster count for ClusterObserver.

**Conclusion:** at realistic scale, the sidecar is not just simpler operationally and more secure, but also cheaper, because llm-d's cost floor is set by provisioning GPU-class capacity the embedding workload cannot exploit, not by the actual volume of embedding calls. This calculation should be revisited with real cloud pricing and real cluster counts if the deployment scope grows significantly (see the "More Information" section below).

### Infrastructure Environment Breakdown (AWS / GCP / Bare Metal)

The tokenomics conclusion above holds across environments, but the size of the gap — and the type of cost (opex vs. capex) — differs meaningfully:

| Environment | Option 1: Sidecar mode | Option 2: llm-d via Helm |
|---|---|---|
| **AWS (EKS)** | Runs on the existing general-purpose worker node pool; no new node group required. | Requires a GPU-backed node group, billed on-demand per hour regardless of embedding call volume, plus NVIDIA device plugin/driver management. Spot instances cut cost but introduce preemption risk for an always-available governance dependency. |
| **GCP (GKE)** | Runs on the existing CPU node pool; compatible with GKE Autopilot without accelerator configuration. | Requires a GPU or TPU node pool. GKE Autopilot supports accelerators but at a cost premium; committed-use discounts reduce, but do not remove, the cost floor. |
| **Bare metal** | Uses CPU capacity already provisioned — effectively marginal/incremental cost only. | If GPU hardware is not already present, this is a **capital expenditure** with weeks-to-months procurement lead time, not an on-demand rental. If GPU hardware already exists for other workloads, dedicating a slice to a small embedding model competes with higher-value workloads for the same physical accelerators. |

**Net effect:** the sidecar's advantage holds in all three environments, but is **largest on bare metal** (capex risk and procurement lead time) and **narrowest on managed cloud Kubernetes** (GPU capacity at least available on-demand, though still structurally more expensive than the CPU capacity the sidecar needs).

### Consequences

- Good, because there is no new cluster-level dependency (no Gateway API Inference Extension CRDs, no vLLM, no Envoy routing layer) to operate for a model this small.
- Good, because embedding calls stay local, avoiding an extra network hop and an extra point of failure shared across unrelated workloads.
- Good, because the runtime and model/GGUF version can be pinned per-deployment, consistent with ADR-0001's reproducibility requirement.
- Good, because scalability is handled implicitly as consumer clusters are added — no separate capacity-planning or autoscaling configuration is needed for the embedding layer itself.
- Good, because, under the recommended cluster-local granularity, multi-organization data isolation falls out of the topology itself — no raw data from any organization ever enters a component shared with another organization's data.
- Bad, because many small, independently-deployed instances create version/patch drift risk (criterion 4) that must be actively mitigated with a shared base image or Helm subchart, rather than a single place to patch.
- Bad, because a model or quantization change (e.g. `Q4_K_M` → `Q8_0` per ADR-0001's follow-up) must be rolled out to every deployment carrying the embedding component, rather than updated once in a shared service.

### Rejected option

- **Option 2 (llm-d via Helm)** — rejected primarily on Scalability, Security, and multi-tenant data isolation (criteria 1, 4, and 5). llm-d's core value — prefix-cache-aware routing, prefill/decode disaggregation, GPU/TPU-scale scheduling — targets large generative model serving depth, not the breadth-scaling, low-overhead governance workload described in the problem statement. Its centralized architecture forces a choice between multiplying the heaviest option per cluster/organization, or commingling multiple organizations' raw data in one shared component — the latter being a compliance blocker independent of cost. If future scope grows to include serving a large generative LLM for the agent itself (a separate model from the embedding model), llm-d should be re-evaluated on its own merits in a dedicated ADR, since that workload — and that scaling shape — is exactly what it is designed for.

## <a name="more-info"></a> More Information

If, at higher scale, embedding call volume or the number of provisioned instances becomes a measurable operational cost, consider a follow-up ADR evaluating a **plain shared embedding service per organization** (still `llama.cpp`-based, no llm-d) as an intermediate option between fully cluster-local instances and a fully centralized inference framework.
## <a name="outcome"></a> Outcome
We decided for [Option 1](#option-1) because: embedding workload (a 137M-parameter, CPU-friendly, single-shape model) does not need the architecture llm-d exists to provide, and the top-priority driver — Scalability — favors a topology whose overhead stays flat as clusters and organizations are added. The sidecar approach also wins on Security and multi-tenant isolation, both of which become sharper concerns once the deployment spans a control plane governing multiple organizations' clusters (see the Scenario Walkthroughs below)

## <a name="comments"></a> Comments
<a name="comment-1"></a>1. (2026-09-13 19:58:26) : marked decision as decided
