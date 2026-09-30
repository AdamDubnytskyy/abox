#!/usr/bin/env python3
"""
Send the exact chunks index.py produces through an MCP server's own store
tool (e.g. vector_store on your qdrant-mcp, or qdrant-store on the official
server). The server embeds and writes them itself, so the stored format is
always the one that server's find tool expects.

Requires the 1.x MCP SDK (2.x renamed the client API):
  pip install "mcp<2"

Usage:
  python mcp_ingest.py --url http://localhost:3001/mcp --show-tools
  python mcp_ingest.py --url http://localhost:3001/mcp --tool vector_store ../releases --dry-run
  python mcp_ingest.py --url http://localhost:3001/mcp --tool vector_store ../releases

Argument names are detected from the tool's input schema; override with
--text-arg / --metadata-arg if detection picks the wrong ones.
Note: most store tools assign random IDs, so running this twice duplicates
points. Delete the collection before re-running.
"""

import argparse
import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from index import build_entries

TEXT_CANDIDATES = ("information", "text", "content", "document", "data", "input")


def detect_args(schema):
    props = (schema or {}).get("properties") or {}
    required = (schema or {}).get("required") or []
    text = next((c for c in TEXT_CANDIDATES if c in props), None)
    if text is None:
        text = next((p for p in required if props.get(p, {}).get("type") == "string"), None)
    meta = "metadata" if "metadata" in props else None
    return text, meta, props.get(meta, {}).get("type") if meta else None


async def run(args):
    async with streamablehttp_client(args.url, timeout=args.timeout) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {t.name: t for t in (await session.list_tools()).tools}

            if args.show_tools or not args.tool:
                for t in tools.values():
                    print(f"{t.name}\n  {json.dumps(t.inputSchema)}\n")
                return
            if args.tool not in tools:
                sys.exit(f"Tool '{args.tool}' not found. Available: {', '.join(tools)}")

            text_arg, meta_arg, meta_type = detect_args(tools[args.tool].inputSchema)
            text_arg = args.text_arg or text_arg
            meta_arg = args.metadata_arg or meta_arg
            if not text_arg:
                sys.exit("Could not detect the text argument; pass --text-arg.")
            print(f"Using {args.tool}({text_arg}=..., {meta_arg or 'no metadata'})", file=sys.stderr)

            entries = build_entries(args.inputs, args.source)
            print(f"{len(entries)} chunks", file=sys.stderr)
            failed = 0
            for i, (_, doc, meta) in enumerate(entries, 1):
                call = {text_arg: doc}
                if meta_arg:
                    call[meta_arg] = json.dumps(meta) if meta_type == "string" else meta
                if args.dry_run:
                    print(json.dumps(call)[:200])
                    continue
                result = await session.call_tool(args.tool, call)
                if result.isError:
                    failed += 1
                    msg = " ".join(getattr(c, "text", "") for c in result.content)
                    print(f"[{i}] ERROR: {msg[:300]}", file=sys.stderr)
                elif i % 10 == 0 or i == len(entries):
                    print(f"stored {i}/{len(entries)}", file=sys.stderr)
            if failed:
                sys.exit(f"{failed} chunks failed")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="*", help="files, directories, or '-' for stdin")
    ap.add_argument("--url", required=True, help="MCP endpoint, e.g. http://localhost:3001/mcp")
    ap.add_argument("--tool", help="store tool name, e.g. vector_store")
    ap.add_argument("--source", default="gitops")
    ap.add_argument("--text-arg")
    ap.add_argument("--metadata-arg")
    ap.add_argument("--timeout", type=float, default=60)
    ap.add_argument("--show-tools", action="store_true", help="list tools and their input schemas")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.tool and not args.inputs and not args.show_tools:
        ap.error("inputs are required when --tool is given")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()