#!/usr/bin/env python3
"""A command-line MCP client, for using a server from a shell or a script.

Speaks the protocol over stdio to whatever server command it is given, does one thing, and
exits: lists the tools and prompts, fetches a prompt, or calls a tool with JSON arguments
and prints the text that comes back. It exists so that an agent whose only interface is a
shell -- which is what every blind writer in `bench/` is -- can be given a server and
nothing else, and so that a server can be poked at by hand.

    client.py --server "python3 mcp/server.py --config db.json" list
    client.py --server "..." prompt writing_brief '{"language": "sql"}'
    client.py --server "..." call describe_schema '{"database": "chinook", "question": "..."}'

Each invocation starts the server, so a call costs its start-up; a session that stays open
is what a real client does, and what `tests/test_server.py` checks.
"""
import argparse
import asyncio
import json
import os
import shlex
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def text_of(result):
    parts = []
    for c in getattr(result, "content", None) or getattr(result, "messages", None) or []:
        content = getattr(c, "content", c)               # a prompt message wraps its content
        t = getattr(content, "text", None)
        if t is not None:
            parts.append(t)
    return "\n".join(parts)


async def run(server, action, name, args):
    argv = shlex.split(server)
    params = StdioServerParameters(command=argv[0], args=argv[1:])
    # the server logs every request to its stderr; a shell user wants the answer alone
    async with stdio_client(params, errlog=open(os.devnull, "w")) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            if action == "list":
                tools = (await session.list_tools()).tools
                prompts = (await session.list_prompts()).prompts
                out = ["tools:"]
                for t in tools:
                    out.append("  %-18s %s" % (t.name, " ".join((t.description or "").split())))
                    props = (t.inputSchema or {}).get("properties", {})
                    if props:
                        out.append("  %18s   arguments: %s" % ("", ", ".join(
                            "%s%s" % (k, "" if k in (t.inputSchema.get("required") or []) else "?")
                            for k in props)))
                out.append("prompts:")
                for p in prompts:
                    out.append("  %-18s %s" % (p.name, " ".join((p.description or "").split())))
                return "\n".join(out)
            if action == "prompt":
                result = await session.get_prompt(name, args)
                return text_of(result)
            result = await session.call_tool(name, args)
            text = text_of(result)
            if getattr(result, "isError", False):
                return "error: " + text
            return text


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--server", required=True, help="the server command, quoted")
    p.add_argument("action", choices=["list", "prompt", "call"])
    p.add_argument("name", nargs="?", help="the tool or prompt")
    p.add_argument("args", nargs="?", default="{}", help="its arguments, as JSON")
    a = p.parse_args(argv)
    if a.action != "list" and not a.name:
        p.error("%s needs a name" % a.action)
    try:
        args = json.loads(a.args)
    except ValueError as e:
        p.error("arguments must be JSON: %s" % e)
    print(asyncio.run(run(a.server, a.action, a.name, args)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
