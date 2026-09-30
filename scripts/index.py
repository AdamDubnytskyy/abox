#!/usr/bin/env python3
"""
Index Kubernetes manifests (and any text files) into Qdrant so that
mcp-server-qdrant's `qdrant-find` tool can search them.

Compatible with mcp-server-qdrant 0.8.x:
  - named vector  "fast-all-minilm-l6-v2", size 384, cosine
  - payload       {"document": <text>, "metadata": {...}}
  - embeddings    fastembed TextEmbedding.passage_embed

Usage:
  python index.py ./manifests ./docs
  kubectl get deploy,sts,svc,ing,cm -A -o yaml | python index.py -
  python index.py ./manifests --source gitops --prune
"""

import argparse
import hashlib
import os
import sys
import uuid
from pathlib import Path

import yaml
from fastembed import TextEmbedding
from qdrant_client import QdrantClient, models

MODEL = os.environ.get("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
VECTOR_NAME = f"fast-{MODEL.split('/')[-1].lower()}"  # same rule as the MCP server
ID_NAMESPACE = uuid.UUID("5b1c6f0e-8f5a-4c4e-9a53-2f3d1b7a9c10")

YAML_EXT = {".yaml", ".yml"}
TEXT_EXT = {".md", ".txt", ".rst"}
MAX_WORDS = 180      # all-MiniLM-L6-v2 truncates at 256 tokens; stay under it
OVERLAP_WORDS = 30

DROP_ANNOTATIONS = ("kubectl.kubernetes.io/last-applied-configuration",)


# ---------------------------------------------------------------- k8s parsing

def iter_k8s_objects(docs):
    """Yield k8s objects, unwrapping `kind: List` from `kubectl get -o yaml`."""
    for doc in docs:
        if not isinstance(doc, dict) or "kind" not in doc:
            continue
        if doc["kind"].endswith("List") and "items" in doc:
            yield from iter_k8s_objects(doc["items"])
        else:
            yield doc


def sanitize(obj):
    """Remove noise and never index secret values."""
    obj = dict(obj)
    obj.pop("status", None)
    meta = dict(obj.get("metadata") or {})
    for key in ("managedFields", "uid", "resourceVersion", "generation",
                "creationTimestamp", "selfLink"):
        meta.pop(key, None)
    ann = {k: v for k, v in (meta.get("annotations") or {}).items()
           if k not in DROP_ANNOTATIONS}
    if ann:
        meta["annotations"] = ann
    else:
        meta.pop("annotations", None)
    obj["metadata"] = meta
    if obj.get("kind") == "Secret":
        for field in ("data", "stringData"):
            if field in obj:
                obj[field] = {k: "<redacted>" for k in obj[field]}
    # API keys, tokens and passwords in env maps, Helm values, etc.
    return redact(obj)


def pod_spec(obj):
    spec = obj.get("spec") or {}
    if obj.get("kind") == "CronJob":
        return (((spec.get("jobTemplate") or {}).get("spec") or {})
                .get("template") or {}).get("spec") or {}
    if "template" in spec:
        return (spec["template"] or {}).get("spec") or {}
    if obj.get("kind") == "Pod":
        return spec
    return {}


def fmt_kv(d):
    return ", ".join(f"{k}={v}" for k, v in (d or {}).items())


def describe(obj):
    """Build short natural-language chunks. MiniLM matches prose much better than raw YAML."""
    kind = obj.get("kind", "?")
    meta = obj.get("metadata") or {}
    name = meta.get("name", "?")
    ns = meta.get("namespace", "default" if kind not in CLUSTER_SCOPED else "")
    spec = obj.get("spec") or {}
    where = f" in namespace {ns}" if ns else " (cluster-scoped)"
    if str(obj.get("apiVersion", "")).startswith("kustomize.config"):
        name, where = "kustomization.yaml", ""  # a build file, not a cluster object

    head = [f"Kubernetes {kind} named {name}{where}."]
    if meta.get("labels"):
        head.append(f"Labels: {fmt_kv(meta['labels'])}.")
    if "replicas" in spec:
        head.append(f"Replicas: {spec['replicas']}.")
    if kind == "Service":
        ports = ", ".join(f"{p.get('port')}->{p.get('targetPort', p.get('port'))}/{p.get('protocol', 'TCP')}"
                          for p in spec.get("ports") or [])
        head.append(f"Service type {spec.get('type', 'ClusterIP')}, ports {ports}, "
                    f"selector {fmt_kv(spec.get('selector'))}.")
    if kind == "Ingress":
        for rule in spec.get("rules") or []:
            for path in ((rule.get("http") or {}).get("paths")) or []:
                svc = ((path.get("backend") or {}).get("service")) or {}
                head.append(f"Routes {rule.get('host', '*')}{path.get('path', '/')} "
                            f"to service {svc.get('name')} port {(svc.get('port') or {}).get('number')}.")
    if kind in ("ConfigMap", "Secret"):
        keys = list((obj.get("data") or {}).keys()) + list((obj.get("stringData") or {}).keys())
        head.append(f"Keys: {', '.join(keys)}.")
    if kind == "CronJob":
        head.append(f"Schedule: {spec.get('schedule')}.")

    extra_chunks = []
    handler = KIND_HANDLERS.get(kind)
    if kind == "Kustomization" and str(obj.get("apiVersion", "")).startswith("kustomize.config"):
        handler = describe_kustomize_file
    if handler:
        sentences, extra_chunks = handler(obj, spec, name, ns, where)
        head.extend(sentences)
    elif spec and kind not in BUILTIN_KINDS and not pod_spec(obj):
        # Unknown CRD: list its scalar spec fields so the chunk still says something.
        leaves = flatten(spec)[:25]
        if leaves:
            head.append("Spec: " + "; ".join(leaves) + ".")

    chunks = [" ".join(head)]
    label = f"{kind} {name}{where}"
    chunks += [f"{title} of {label}: {text}" for title, text in extra_chunks]

    # One extra chunk per container: images/env/resources are what people search for.
    ps = pod_spec(obj)
    for c in (ps.get("initContainers") or []) + (ps.get("containers") or []):
        parts = [f"Container {c.get('name')} of {kind} {name}{where} runs image {c.get('image')}."]
        if c.get("command") or c.get("args"):
            parts.append(f"Command: {' '.join(map(str, (c.get('command') or []) + (c.get('args') or [])))}.")
        if c.get("ports"):
            parts.append("Ports: " + ", ".join(str(p.get("containerPort")) for p in c["ports"]) + ".")
        env = [e.get("name") for e in c.get("env") or []]
        if env:
            parts.append(f"Env vars: {', '.join(env)}.")
        refs = [ (e.get("configMapRef") or e.get("secretRef") or {}).get("name") for e in c.get("envFrom") or []]
        if any(refs):
            parts.append(f"Env from: {', '.join(r for r in refs if r)}.")
        res = c.get("resources") or {}
        if res:
            parts.append(f"Requests {fmt_kv(res.get('requests'))}; limits {fmt_kv(res.get('limits'))}.")
        chunks.append(" ".join(parts))

    return [truncate_words(ch) for ch in chunks]


CLUSTER_SCOPED = {"Namespace", "ClusterRole", "ClusterRoleBinding", "CustomResourceDefinition",
                  "PersistentVolume", "StorageClass", "Node", "PriorityClass", "IngressClass"}

BUILTIN_KINDS = {"Namespace", "Service", "Ingress", "ConfigMap", "Secret", "ServiceAccount",
                 "Role", "RoleBinding", "ClusterRole", "ClusterRoleBinding"}

SECRETISH = ("key", "token", "password", "secret", "credential")


# ---------------------------------------------------------------- CRD handlers
# Each returns (sentences for the head chunk, [(title, text), ...] extra chunks).

def ref(r, default_ns=None):
    if not isinstance(r, dict):
        return str(r)
    ns = r.get("namespace", default_ns)
    kind = f"{r['kind']} " if r.get("kind") else ""
    return f"{kind}{ns + '/' if ns else ''}{r.get('name')}"


REFERENCE_SUFFIXES = ("secret", "secretkey", "secretref", "secretname", "valueskey", "ref", "keyref")


def is_secretish(name):
    """True for fields that hold a secret value, not for fields that name a Secret."""
    n = str(name).lower()
    return any(s in n for s in SECRETISH) and not n.endswith(REFERENCE_SUFFIXES)


def redact(value):
    if isinstance(value, dict):
        return {k: ("<redacted>" if is_secretish(k) and not isinstance(v, (dict, list)) else redact(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def flatten(value, prefix="", depth=0):
    """Scalar leaves as 'path=value'; secret-looking keys are redacted."""
    out = []
    if depth > 6:
        return out
    if isinstance(value, dict):
        for k, v in value.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            if is_secretish(k) and not isinstance(v, (dict, list)):
                out.append(f"{path}=<redacted>")
            else:
                out += flatten(v, path, depth + 1)
    elif isinstance(value, list):
        if all(not isinstance(v, (dict, list)) for v in value):
            if value:
                out.append(f"{prefix}=[{', '.join(map(str, value))}]")
        else:
            for i, v in enumerate(value):
                out += flatten(v, f"{prefix}[{i}]", depth + 1)
    elif value is not None:
        text = str(value)
        if len(text) > 80 or "\n" in text:
            text = text[:77].replace("\n", " ") + "..."
        out.append(f"{prefix}={text}")
    return out


def as_chunks(title, lines, words=150):
    return [(title, ch) for ch in chunk_text(" ".join(lines), words)]


def describe_helmrelease(obj, spec, name, ns, where):
    s = []
    chart = ((spec.get("chart") or {}).get("spec")) or {}
    if chart:
        s.append(f"Installs Helm chart {chart.get('chart')} version {chart.get('version', 'latest')} "
                 f"from {ref(chart.get('sourceRef'), ns)}.")
    if spec.get("chartRef"):
        s.append(f"Chart comes from {ref(spec['chartRef'], ns)}.")
    if spec.get("releaseName"):
        s.append(f"Release name {spec['releaseName']}.")
    if spec.get("targetNamespace"):
        s.append(f"Target namespace {spec['targetNamespace']}.")
    if spec.get("dependsOn"):
        s.append("Depends on HelmRelease " + ", ".join(ref(d, ns) for d in spec["dependsOn"]) + ".")
    if spec.get("valuesFrom"):
        s.append("Values from " + ", ".join(f"{v.get('kind')} {v.get('name')}" for v in spec["valuesFrom"]) + ".")
    values = spec.get("values") or {}
    extra = as_chunks("Helm values", flatten(values)) if values else []
    if values:
        s.append("Top-level values: " + ", ".join(values.keys()) + ".")
    return s, extra


def describe_source(obj, spec, name, ns, where):
    s = [f"Flux source pointing to {spec.get('url')}."]
    r = spec.get("ref") or {}
    if r:
        s.append("Reference " + fmt_kv(r) + ".")
    if spec.get("type"):
        s.append(f"Repository type {spec['type']}.")
    if spec.get("interval"):
        s.append(f"Checked every {spec['interval']}.")
    return s, []


def describe_flux_kustomization(obj, spec, name, ns, where):
    s = [f"Flux Kustomization applying path {spec.get('path', '/')} from {ref(spec.get('sourceRef'), ns)}."]
    if "prune" in spec:
        s.append(f"Prune {spec['prune']}.")
    if spec.get("targetNamespace"):
        s.append(f"Target namespace {spec['targetNamespace']}.")
    if spec.get("dependsOn"):
        s.append("Depends on " + ", ".join(ref(d, ns) for d in spec["dependsOn"]) + ".")
    return s, []


def describe_kustomize_file(obj, spec, name, ns, where):
    res = obj.get("resources") or []
    s = [f"kustomization.yaml listing resources: {', '.join(map(str, res))}."] if res else []
    if obj.get("namespace"):
        s.append(f"Sets namespace {obj['namespace']}.")
    return s, []


def describe_mcpserver(obj, spec, name, ns, where):
    d = spec.get("deployment") or {}
    s = [f"MCP server using {spec.get('transportType', 'stdio')} transport, "
         f"image {d.get('image', 'default')}, command {d.get('cmd')} {' '.join(map(str, d.get('args') or []))}, "
         f"port {d.get('port')}."]
    env = d.get("env") or {}
    extra = []
    if env:
        s.append("Env vars: " + ", ".join(env.keys()) + ".")
        lines = []
        for k, v in env.items():
            if is_secretish(k):
                lines.append(f"{k}=<redacted>.")
            else:
                lines.append(f"{k}={v}.")
        extra = as_chunks("Environment", lines)
    if spec.get("timeout"):
        s.append(f"Timeout {spec['timeout']}.")
    return s, extra


def describe_httproute(obj, spec, name, ns, where):
    s = []
    if spec.get("parentRefs"):
        s.append("Attached to gateway " + ", ".join(ref(p, ns) for p in spec["parentRefs"]) + ".")
    if spec.get("hostnames"):
        s.append("Hostnames " + ", ".join(spec["hostnames"]) + ".")
    for rule in spec.get("rules") or []:
        paths = [((m.get("path") or {}).get("value", "/")) for m in rule.get("matches") or []] or ["/"]
        backends = [f"{ref(b, ns)} port {b.get('port')}" for b in rule.get("backendRefs") or []]
        s.append(f"Routes {', '.join(paths)} to {', '.join(backends)}.")
    return s, []


def describe_gateway(obj, spec, name, ns, where):
    s = [f"Gateway of class {spec.get('gatewayClassName')}."]
    for lst in spec.get("listeners") or []:
        s.append(f"Listener {lst.get('name')} on port {lst.get('port')} {lst.get('protocol')}"
                 f"{' host ' + lst['hostname'] if lst.get('hostname') else ''}.")
    return s, []


def describe_referencegrant(obj, spec, name, ns, where):
    frm = ", ".join(f"{f.get('kind')} in namespace {f.get('namespace')}" for f in spec.get("from") or [])
    to = ", ".join(f"{t.get('kind')}{' ' + t['name'] if t.get('name') else ''}" for t in spec.get("to") or [])
    return [f"Allows {frm} to reference {to} in namespace {ns}."], []


def describe_agent(obj, spec, name, ns, where):
    decl = spec.get("declarative") or {}
    s = [f"kagent agent of type {spec.get('type')}."]
    if spec.get("description"):
        s.append(f"Description: {spec['description']}")
    if decl.get("modelConfig"):
        s.append(f"Uses ModelConfig {decl['modelConfig']}.")
    tools = []
    for t in decl.get("tools") or []:
        if t.get("mcpServer"):
            m = t["mcpServer"]
            tools.append(f"MCP server {m.get('name')} ({', '.join(m.get('toolNames') or [])})")
        elif t.get("agent"):
            tools.append(f"agent {t['agent'].get('name')}")
    if tools:
        s.append("Tools: " + "; ".join(tools) + ".")
    if decl.get("memory"):
        s.append("Long-term memory enabled.")
    extra = as_chunks("System prompt", [decl["systemMessage"]]) if decl.get("systemMessage") else []
    return s, extra


def describe_modelconfig(obj, spec, name, ns, where):
    return [f"Model configuration for provider {spec.get('provider')}, model {spec.get('model')}, "
            f"API key from secret {spec.get('apiKeySecret')}."], []


def describe_remotemcp(obj, spec, name, ns, where):
    return [f"Remote MCP server at {spec.get('url')} using {spec.get('protocol', 'streamable HTTP')}."], []


KIND_HANDLERS = {
    "HelmRelease": describe_helmrelease,
    "OCIRepository": describe_source,
    "HelmRepository": describe_source,
    "GitRepository": describe_source,
    "Kustomization": describe_flux_kustomization,
    "MCPServer": describe_mcpserver,
    "HTTPRoute": describe_httproute,
    "Gateway": describe_gateway,
    "ReferenceGrant": describe_referencegrant,
    "Agent": describe_agent,
    "ModelConfig": describe_modelconfig,
    "RemoteMCPServer": describe_remotemcp,
}


# ---------------------------------------------------------------- generic text

def truncate_words(text, limit=MAX_WORDS):
    words = text.split()
    return text if len(words) <= limit else " ".join(words[:limit]) + " ..."


def chunk_text(text, size=MAX_WORDS):
    words = text.split()
    if not words:
        return []
    step = size - OVERLAP_WORDS
    return [" ".join(words[i:i + size]) for i in range(0, max(len(words) - OVERLAP_WORDS, 1), step)]


# ---------------------------------------------------------------- collect

def build_entries(inputs, source):
    """Return list of (point_id, document, metadata)."""
    entries = []

    def add(key, doc, meta):
        pid = str(uuid.uuid5(ID_NAMESPACE, f"{source}|{key}"))
        entries.append((pid, doc, {**meta, "source": source}))

    def handle_yaml(text, origin):
        try:
            docs = list(yaml.safe_load_all(text))
        except yaml.YAMLError as e:
            print(f"skip {origin}: {e}", file=sys.stderr)
            return
        for obj in iter_k8s_objects(docs):
            obj = sanitize(obj)
            m = obj.get("metadata") or {}
            base = {"type": "k8s", "kind": obj.get("kind"), "name": m.get("name"),
                    "namespace": m.get("namespace"), "api_version": obj.get("apiVersion"),
                    "file": origin}
            raw = yaml.safe_dump(obj, sort_keys=False)
            ident = f"{obj.get('kind')}/{m.get('namespace', '')}/{m.get('name') or origin}"
            for i, doc in enumerate(describe(obj)):
                meta = dict(base, chunk=i)
                if i == 0:
                    meta["manifest"] = raw  # full YAML comes back with the search hit
                add(f"{ident}#{i}", doc, meta)

    for inp in inputs:
        if inp == "-":
            handle_yaml(sys.stdin.read(), "stdin")
            continue
        root = Path(inp)
        files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        for f in files:
            ext = f.suffix.lower()
            if ext in YAML_EXT:
                handle_yaml(f.read_text(encoding="utf-8", errors="replace"), str(f))
            elif ext in TEXT_EXT:
                for i, ch in enumerate(chunk_text(f.read_text(encoding="utf-8", errors="replace"))):
                    add(f"{f}#{i}", ch, {"type": "text", "file": str(f), "chunk": i})
    return entries


# ---------------------------------------------------------------- qdrant

def ensure_collection(client, name, dim):
    if client.collection_exists(name):
        info = client.get_collection(name)
        vectors = info.config.params.vectors
        if not isinstance(vectors, dict) or VECTOR_NAME not in vectors:
            sys.exit(f"Collection '{name}' has no vector '{VECTOR_NAME}'. "
                     f"It was created with a different model or tool.")
        return
    client.create_collection(
        name,
        vectors_config={VECTOR_NAME: models.VectorParams(size=dim, distance=models.Distance.COSINE)},
    )
    for field in ("metadata.source", "metadata.type", "metadata.kind", "metadata.namespace"):
        client.create_payload_index(name, field, models.PayloadSchemaType.KEYWORD)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="files, directories, or '-' for stdin")
    ap.add_argument("--source", default="manifests", help="tag for this data set (used by --prune)")
    ap.add_argument("--prune", action="store_true", help="delete points of this source not seen in this run")
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--dry-run", action="store_true", help="print chunks, do not write")
    args = ap.parse_args()

    entries = build_entries(args.inputs, args.source)
    print(f"{len(entries)} chunks from {args.inputs}", file=sys.stderr)
    if args.dry_run:
        for pid, doc, meta in entries:
            print(f"- [{meta.get('kind') or meta.get('type')}] {doc}")
        return
    if not entries:
        return

    collection = os.environ["COLLECTION_NAME"]
    client = QdrantClient(url=os.environ["QDRANT_URL"], api_key=os.environ.get("QDRANT_API_KEY") or None)
    model = TextEmbedding(MODEL)
    dim = len(next(iter(model.passage_embed(["probe"]))))
    ensure_collection(client, collection, dim)

    run_id = hashlib.sha1(os.urandom(16)).hexdigest()[:12]
    for i in range(0, len(entries), args.batch):
        batch = entries[i:i + args.batch]
        vectors = list(model.passage_embed([doc for _, doc, _ in batch]))
        client.upsert(collection, points=[
            models.PointStruct(id=pid, vector={VECTOR_NAME: vec.tolist()},
                               payload={"document": doc, "metadata": {**meta, "run": run_id}})
            for (pid, doc, meta), vec in zip(batch, vectors)
        ])
        print(f"upserted {i + len(batch)}/{len(entries)}", file=sys.stderr)

    if args.prune:
        client.delete(collection, points_selector=models.FilterSelector(filter=models.Filter(
            must=[models.FieldCondition(key="metadata.source", match=models.MatchValue(value=args.source))],
            must_not=[models.FieldCondition(key="metadata.run", match=models.MatchValue(value=run_id))],
        )))
        print("pruned stale points", file=sys.stderr)


if __name__ == "__main__":
    main()
