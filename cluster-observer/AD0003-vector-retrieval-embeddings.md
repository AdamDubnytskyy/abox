---
adr_id: "0003"
comments:
    - author: Oleh Adam Dubnytskyy
      comment: "1"
      date: "2026-09-30 23:41:52"
links:
    precedes: []
    succeeds: []
status: decided
tags:
    - vector-retrieval
    - embeddings
    - qdrant
    - mcp
title: VectorRetrievalEmbeddings
---

## <a name="question"></a> Question

Which embedding model and MCP server should the platform's retrieval agents use
to answer questions about the cluster's own configuration (Flux releases, kagent
agents, MCP servers, Gateway API routes), and what does each cost in quality,
latency and operations?

Agents in this cluster answer questions about the platform's own configuration
(Flux releases, kagent agents, MCP servers, Gateway API routes). They retrieve
that knowledge through an MCP server backed by Qdrant. Two candidates exist:

| | `qdrant-mcp-official` | `qdrant-mcp` |
|---|---|---|
| Implementation | Official `mcp-server-qdrant` (Python, `uvx`), stdio behind agentgateway | Own Go server, `ghcr.io/adamdubnytskyy/abox/qdrant-mcp:0.4.0`, stdio behind agentgateway |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2` via fastembed, in-process on CPU | nomic-embed via llama.cpp (`llama-cpp-embeddings.llama-cpp:8090`) |
| Vector | named `fast-all-minilm-l6-v2`, 384 dims, cosine | unnamed, 768 dims, cosine |
| Task prefixes | none (model does not use them) | `search_document: ` / `search_query: ` applied by the server |
| Collection | `abox-minilm` | `abox-nomic` |
| Tools | `qdrant-find(query)`, `qdrant-store(information, metadata)` | `vector_find(query, limit)`, `vector_store(information, metadata: map[string]string)` |
| Tool descriptions | overridden via `TOOL_FIND_DESCRIPTION` / `TOOL_STORE_DESCRIPTION` | defined in code |

## <a name="options"></a> Options

1. <a name="option-1"></a> Official mcp-server-qdrant with all-MiniLM-L6-v2 (`qdrant-mcp-official`, collection `abox-minilm`)
2. <a name="option-2"></a> Own qdrant-mcp server with nomic-embed via llama.cpp (`qdrant-mcp`, collection `abox-nomic`)
3. <a name="option-3"></a> Both, routed per data domain

Option 3 is only considered if results show complementary strengths: two
stores with the same data double ingest and make answers harder to attribute.

## <a name="criteria"></a> Criteria

### Decision drivers

1. Retrieval quality on questions about our own manifests, including questions
   that do not reuse the manifest's wording.
2. Agent behaviour: does the agent call the tool on its own, answer from what it
   retrieved, and admit when the data has no answer?
3. Operational cost: extra services, memory, cold-start latency, failure modes.
4. Portability: how much custom code we own and maintain.

### Decision rule

In order:

1. If one option leads on paraphrased-question hit@3 by 0.15 or more and is not
   worse on literal questions, choose it: that gap reflects real-world queries.
2. If quality is within that margin, prefer the option with the smaller
   operational footprint and less owned code (option 1), unless Layer 2 shows
   agent behaviour differs materially.
3. Either way, keep built-in agent memory disabled on retrieval agents and keep
   the retrieval rule in the system prompt (findings 1 and 2).

### Experiment setup

#### Data

- Source: `releases/` in this repository (the Flux source of truth).
- 66 chunks generated, **64 unique** after de-duplication: `Namespace`
  `kagent` and `agentgateway-system` are each declared twice (release file and
  CRDs file) and collapse to one point.
- Each object is converted to short natural-language descriptions
  (`scripts/index.py`), not raw YAML: one summary chunk per object, plus extra
  chunks for Helm values, MCP server environment and agent system prompts. The
  full, redacted manifest is stored in `metadata.manifest`.
- Secret values (keys, tokens, passwords) are redacted everywhere, including in
  the stored manifest; references to Secrets by name are kept.
- Identical texts and metadata in both collections:
  - `abox-minilm`: written directly by `scripts/index.py` (stable IDs,
    `--prune`), plus one test note (`blue-falcon-88`).
  - `abox-nomic`: written through the server's own `vector_store` tool by
    `scripts/mcp_ingest.py`, so the stored format is the server's own.

#### Agents

| | `retrieval-agent-official` | `retrieval-agent` |
|---|---|---|
| Model | `gpt-4.1-mini` | `gpt-4.1-mini` (verify: Git file says `gemini-gemini-3-5-flash`) |
| Vector tools | `qdrant-find`, `qdrant-store` | `vector_find`, `vector_store` |
| Other tools | none | `neo4j-mcp` (get-schema, read-cypher, write-cypher), agent `k8s-agent` |
| System prompt | vector-only, must call `qdrant-find` first | ingest/retrieve prompt, routes content questions to `vector_find` and relationship questions to Neo4j |
| Long-term memory | disabled | none |
| Managed by | created in UI, exported to Git (commit: `<hash>`) | Flux, `releases/006-agent-retrieval.yaml` |

Because the agents differ in more than the vector store, the evaluation has two
layers.

#### Method

**Layer 1: retrieval only.** `scripts/eval_retrieval.py` sends every question in
`scripts/questions.yaml` straight to `qdrant-find` and `vector_find`, with no
agent or LLM involved, and records the rank of the expected manifest in the top
5 results. Metrics over answerable questions: hit@1, hit@3, hit@5, MRR, and p50
latency per call.

**Layer 2: agentic retrieval.** The same questions are asked in a new chat with
each agent in the kagent UI. Per question: which tool was called, whether the
answer is correct, whether the source was cited, and for unanswerable questions
whether the agent declined instead of guessing. Answers that `retrieval-agent`
produced from Neo4j are recorded separately; they say nothing about the
embedding model.

Question set: 14 answerable (7 literal, 7 paraphrased) and 2 unanswerable.

### Results

#### Layer 1: retrieval

Run: 2026-09-30 19:30 UTC, `results/eval-20260930T193012Z.md`, top K = 5,
14 answerable questions.

| Metric | minilm | nomic |
|---|---|---|
| hit@1 | 0.50 | 0.50 |
| hit@3 | 0.79 | 0.79 |
| hit@5 | 0.93 | 0.93 |
| MRR | 0.67 | 0.65 |
| p50 ms (warm session) | 104 | 64 |
| errors | 0 | 0 |

Split by style:

| | minilm hit@1 | nomic hit@1 | minilm hit@3 | nomic hit@3 | minilm MRR | nomic MRR |
|---|---|---|---|---|---|---|
| literal (7) | 0.71 | 0.86 | 1.00 | 1.00 | 0.86 | 0.90 |
| paraphrase (7) | 0.29 | 0.14 | 0.57 | 0.57 | 0.49 | 0.40 |

Per question:

| ID | Style | minilm rank | nomic rank |
|---|---|---|---|
| q01 | literal | 1 | 1 |
| q02 | literal | 2 | 3 |
| q03 | paraphrase | 4 | 3 |
| q04 | literal | 2 | 1 |
| q05 | paraphrase | miss | miss |
| q06 | literal | 1 | 1 |
| q07 | literal | 1 | 1 |
| q08 | paraphrase | 1 | 1 |
| q09 | paraphrase | 1 | 2 |
| q10 | literal | 1 | 1 |
| q11 | paraphrase | 2 | 2 |
| q12 | paraphrase | 2 | 4 |
| q13 | paraphrase | 5 | 5 |
| q14 | literal | 1 | 1 |
| q15 (negative) | | top hit HelmRelease/agentgateway-crds | top hit Service/llm-d-embedding |
| q16 (negative) | | top hit HelmRelease/kagent | top hit HelmRelease/kagent |

**Reading the results**

- **No meaningful quality difference.** Both reach the same hit@1, hit@3 and
  hit@5; MRR differs by 0.02. The two disagree on 5 of 14 questions (MiniLM
  ranks higher on q02, q09, q12; nomic on q03, q04), always by one or two
  places. With 14 questions, that is well within noise.
- **Contrary to expectation, nomic is not better on paraphrases.** Both reach
  hit@3 0.57 on paraphrased questions against 1.00 on literal ones; MiniLM has
  the slightly higher paraphrase MRR (0.49 vs 0.40), nomic the slightly higher
  literal MRR (0.90 vs 0.86). The larger model and 768-dim vectors bring no
  measurable gain on this corpus.
- **The gap is between question styles, not models.** Both lose about 0.4 of
  hit@3 when the question does not reuse the manifest's wording. The limiting
  factor is the indexed text, not the embedding model: q05 ("where does the
  custom vector search server get its embeddings") fails for both because no
  chunk describes `qdrant-mcp` as a vector search server; q13 ranks 5 for both
  because the Deployment's description names the image but never says it
  serves an embedding model, while its Service and HTTPRoute outrank it.
- **Retrieval always returns something.** For both unanswerable questions each
  store returns top-5 hits, and neither tool exposes a similarity score the
  agent could threshold. Declining must come from the agent (Layer 2). For q16
  ("the OpenAI API key") both return `HelmRelease/kagent`, which only holds
  `apiKey: <redacted>`: redaction is what prevents a leak here.
- **Latency favours nomic** in a warm session (p50 64 ms vs 104 ms), even
  though its embedding runs in a separate llama.cpp service. Cold-start cost
  per MCP session (finding 6) is not included and is larger for the official
  server, which loads its model in every new session.

#### Layer 2: agentic retrieval

| ID | `retrieval-agent-official` tool / correct | `retrieval-agent` tool / correct | Notes |
|---|---|---|---|
| q01 | | | |
| q02 | | | |
| q03 | | | |
| q04 | | | |
| q05 | | | |
| q06 | | | |
| q07 | | | |
| q08 | | | |
| q09 | | | |
| q10 | | | |
| q11 | | | |
| q12 | | | |
| q13 | | | |
| q14 | | | |
| q15 (negative) | | | |
| q16 (negative) | | | |
| **Correct** | /14 | /14 | |
| **Declined correctly** | /2 | /2 | |

Smoke test before the full run: `retrieval-agent-official` answered q01, q02
and q06 correctly, each after a single `qdrant-find` call.

### Findings from the setup

These came up while building the experiment and affect the decision regardless
of the scores.

1. **Built-in memory intercepts retrieval.** In Claude Code, "save to memory"
   went to its own `MEMORY.md` instead of `qdrant-store`, and a later question
   was answered from that file without calling Qdrant, despite an "ALWAYS" tool
   description. In kagent, an agent with long-term memory enabled called
   `load-memory` and gave up without calling `qdrant-find`. Both needed an
   explicit fix: a `CLAUDE.md` rule preferring Qdrant, and removing
   `spec.declarative.memory`. A retrieval tool loses to any memory already in
   context or offered as a tool.
2. **Tool descriptions matter, but routing needs the prompt.** The official
   server's default description ("look up memories … personal information about
   the user") is a poor fit for infrastructure data; overriding it helped, but
   only a system prompt rule made tool use reliable.
3. **Silent misconfiguration.** `mcp-server-qdrant` reads `COLLECTION_NAME`; a
   `QDRANT_COLLECTION` typo was ignored and data went to `default-collection`,
   the Dockerfile default. Our own server uses `QDRANT_COLLECTION`, so the two
   are easy to confuse.
4. **kagent memory was misconfigured by the UI default.** It set the chat model
   `gpt-4.1-mini` as the embedding model, and the UI offers no way to clear it;
   it had to be removed with `kubectl patch`.
5. **Schema strictness.** `vector_store` accepts only string metadata values;
   numbers are rejected (`cannot unmarshal number … of type string`). Clients
   must coerce metadata. `qdrant-store` accepts arbitrary JSON.
6. **Cold start.** agentgateway spawns a new stdio process per MCP session.
   For `mcp-server-qdrant` via `uvx` that means resolving the package and
   loading the model on every session; the default 30 s timeout is tight. The
   Go server starts fast but depends on the llama.cpp service being up.
7. **Operational footprint.** MiniLM runs in-process: no extra service, 384-dim
   vectors. nomic needs a llama.cpp deployment and stores 768-dim vectors
   (2x vector storage), but has a much longer input window than MiniLM's 256
   tokens, which forced chunks of at most ~180 words here.
8. **Secrets in indexed data.** A first version of the indexer stored
   `QDRANT_API_KEY` and a Helm `apiKey` inside `metadata.manifest`. Redaction
   has to cover the whole manifest, not only `Secret` objects.
9. **Vector naming.** The official server uses a named vector; Qdrant's
   dashboard visualisation and any direct client need `"using":
   "fast-all-minilm-l6-v2"`, or requests fail with 400.
10. **GitOps secret handling.** `providers.openAI.apiKey: OPENAI_API_KEY` in the
    HelmRelease is a literal string, not a variable, and caused 401s. Keys must
    come from a Secret via `valuesFrom`.

### Preliminary assessment

Applying the decision rule to Layer 1: criterion 1 is not met (paraphrase hit@3 is 0.57 for
both, no gap), so criterion 2 applies and points to **option 1, the official
server with MiniLM**: equal retrieval quality with no extra embedding service,
half the vector size and no custom server code to maintain. The trade-offs
accepted with it are higher per-call latency (104 vs 64 ms p50), per-session
model loading, and the 256-token input limit.

The larger lever is not the model: both lose about 0.4 hit@3 on paraphrased
questions. Next improvement, independent of this decision: enrich the indexed
descriptions with the object's purpose (for example "serves the embedding
model", "vector search server"), then re-run this evaluation.

This preliminary decision is reversed if Layer 2 shows `retrieval-agent`
answering materially more questions correctly for reasons attributable to
nomic retrieval rather than to Neo4j or its prompt.

When Layer 2 confirms it, record the outcome, which also sets the status to
`decided` and adds the Outcome section:

```bash
adg decide --model cluster-observer --id 0003 --option 1 \
  --rationale "Equal retrieval quality (MRR 0.67 vs 0.65, same hit@k) with no extra embedding service, half the vector size and no custom server code."
```

### Consequences

To fill in after the decision: migration of the unused store, removal of the
unused MCP server and collection, CI job for re-indexing on merge to `main`
(`index.py --prune` or `mcp_ingest.py` after deleting the collection), and
monitoring of MCP session start-up time.

### Reproduce

```bash
cd scripts && source .venv/bin/activate
kubectl port-forward -n qdrant svc/qdrant 6333:6333 &
kubectl port-forward -n kagent svc/qdrant-mcp-official 3000:3000 &
kubectl port-forward -n kagent svc/qdrant-mcp 3001:3000 &

QDRANT_URL=http://localhost:6333 COLLECTION_NAME=abox-minilm \
  python index.py ../releases --source gitops --prune
curl -X DELETE localhost:6333/collections/abox-nomic
python mcp_ingest.py --url http://localhost:3001/mcp --tool vector_store ../releases

python eval_retrieval.py questions.yaml \
  --target minilm=http://localhost:3000/mcp,qdrant-find \
  --target nomic=http://localhost:3001/mcp,vector_find
```
## <a name="outcome"></a> Outcome
We decided for [Option 1](#option-1) because: Equal retrieval quality in a 14-question evaluation (MRR 0.67 vs 0.65, identical hit@1/3/5, no gap on paraphrased questions), with no extra embedding service, half the vector size and no custom server code to maintain.

## <a name="comments"></a> Comments
<a name="comment-1"></a>1. (2026-09-30 23:41:52) Oleh Adam Dubnytskyy: marked decision as decided
