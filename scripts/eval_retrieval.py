#!/usr/bin/env python3
"""
Layer 1 evaluation: send the same questions straight to each MCP server's
find tool (no agent, no LLM) and measure where the expected manifest ranks.

Requires the 1.x MCP SDK:  pip install "mcp<2" pyyaml

Usage:
  # 1. check that results are parsed correctly
  python eval_retrieval.py questions.yaml \
      --target minilm=http://localhost:3000/mcp,qdrant-find \
      --target nomic=http://localhost:3001/mcp,vector_find --show-raw q01

  # 2. full run -> results/<timestamp>.md and .json
  python eval_retrieval.py questions.yaml \
      --target minilm=http://localhost:3000/mcp,qdrant-find \
      --target nomic=http://localhost:3001/mcp,vector_find

A hit counts as correct when its metadata has the expected kind AND name
(any of the listed targets). Metrics use answerable questions only:
hit@1, hit@3, hit@5 and MRR (mean of 1/rank, 0 when not found in top K).
"""

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

K = 5
LIST_KEYS = ("results", "points", "hits", "matches", "items", "data", "entries")


# ---------------------------------------------------------------- parsing

def extract_hits(texts):
    """Split a find tool's response into individual hits, whatever its format."""
    joined = "\n".join(texts)
    entries = re.findall(r"<entry>(.*?)</entry>", joined, re.S)  # mcp-server-qdrant
    if entries:
        return entries
    for t in texts:
        try:
            data = json.loads(t)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            data = next((data[k] for k in LIST_KEYS if isinstance(data.get(k), list)), None)
        if isinstance(data, list):
            return [json.dumps(x) if not isinstance(x, str) else x for x in data]
    return [t for t in texts if t.strip() and not t.startswith("Results for the query")]


def field(hit, key):
    """Value of a JSON string field, also when metadata is itself an escaped JSON string."""
    norm = hit.replace('\\"', '"')
    return re.findall(rf'"{key}"\s*:\s*"([^"]*)"', norm)


def matches(hit, target):
    return target["kind"] in field(hit, "kind") and target["name"] in field(hit, "name")


def rank_of(hits, targets):
    for i, hit in enumerate(hits[:K], 1):
        if any(matches(hit, t) for t in targets):
            return i
    return None


def label(hit):
    kinds, names = field(hit, "kind"), field(hit, "name")
    return f"{kinds[0] if kinds else '?'}/{names[0] if names else '?'}"


# ---------------------------------------------------------------- running

async def query_target(name, url, tool, questions, show_raw):
    out = {}
    async with streamablehttp_client(url, timeout=120) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {t.name: t for t in (await session.list_tools()).tools}
            if tool not in tools:
                sys.exit(f"[{name}] tool '{tool}' not found. Available: {', '.join(tools)}")
            props = (tools[tool].inputSchema or {}).get("properties") or {}
            for q in questions:
                if show_raw and q["id"] != show_raw:
                    continue
                call = {"query": q["question"]}
                if "limit" in props:
                    call["limit"] = K
                start = time.perf_counter()
                result = await session.call_tool(tool, call)
                ms = round((time.perf_counter() - start) * 1000)
                texts = [getattr(c, "text", "") for c in result.content]
                if show_raw:
                    print(f"===== {name} raw response =====")
                    print("\n".join(texts)[:3000])
                    hits = extract_hits(texts)
                    print(f"----- parsed {len(hits)} hits: {[label(h) for h in hits[:K]]}\n")
                    continue
                if result.isError:
                    out[q["id"]] = {"error": " ".join(texts)[:300], "ms": ms}
                    continue
                hits = extract_hits(texts)
                out[q["id"]] = {
                    "rank": rank_of(hits, q.get("expected") or []),
                    "top": [label(h) for h in hits[:K]],
                    "ms": ms,
                }
                print(f"[{name}] {q['id']} rank={out[q['id']]['rank']} {ms}ms", file=sys.stderr)
    return out


def metrics(questions, res):
    answerable = [q for q in questions if q.get("answerable", True)]
    ranks = [(res.get(q["id"]) or {}).get("rank") for q in answerable]
    n = len(ranks) or 1
    lat = sorted(r["ms"] for r in res.values() if "ms" in r)
    return {
        "hit@1": sum(1 for r in ranks if r and r <= 1) / n,
        "hit@3": sum(1 for r in ranks if r and r <= 3) / n,
        "hit@5": sum(1 for r in ranks if r and r <= 5) / n,
        "MRR": sum(1 / r for r in ranks if r) / n,
        "p50 ms": lat[len(lat) // 2] if lat else None,
        "errors": sum(1 for r in res.values() if "error" in r),
    }


def to_markdown(questions, targets, results):
    names = [t[0] for t in targets]
    lines = [f"Evaluated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC, top K={K}.", "",
             "| Metric | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    ms = {n: metrics(questions, results[n]) for n in names}
    for key in ("hit@1", "hit@3", "hit@5", "MRR", "p50 ms", "errors"):
        cells = []
        for n in names:
            v = ms[n][key]
            cells.append(f"{v:.2f}" if isinstance(v, float) else str(v))
        lines.append(f"| {key} | " + " | ".join(cells) + " |")
    lines += ["", "| ID | Question | " + " | ".join(f"{n} rank" for n in names) + " |",
              "|---|---|" + "---|" * len(names)]
    for q in questions:
        cells = []
        for n in names:
            r = results[n].get(q["id"]) or {}
            if "error" in r:
                cells.append("error")
            elif not q.get("answerable", True):
                cells.append(f"n/a (top: {r.get('top', ['-'])[0] if r.get('top') else '-'})")
            else:
                cells.append(str(r.get("rank") or "miss"))
        lines.append(f"| {q['id']} | {q['question']} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("questions")
    ap.add_argument("--target", action="append", required=True, help="name=url,tool")
    ap.add_argument("--show-raw", metavar="QUESTION_ID", help="print raw responses for one question")
    ap.add_argument("--out", default="results")
    args = ap.parse_args()

    questions = yaml.safe_load(Path(args.questions).read_text())["questions"]
    targets = []
    for t in args.target:
        name, rest = t.split("=", 1)
        url, tool = rest.rsplit(",", 1)
        targets.append((name, url, tool))

    results = {}
    for name, url, tool in targets:
        results[name] = asyncio.run(query_target(name, url, tool, questions, args.show_raw))
    if args.show_raw:
        return

    md = to_markdown(questions, targets, results)
    print(md)
    out = Path(args.out)
    out.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (out / f"eval-{stamp}.md").write_text(md)
    (out / f"eval-{stamp}.json").write_text(json.dumps(
        {"targets": targets, "questions": questions, "results": results}, indent=2))
    print(f"saved {out}/eval-{stamp}.md and .json", file=sys.stderr)


if __name__ == "__main__":
    main()
