"""Expose the knowledge base as an MCP server (stdio).  Any MCP client (Claude Desktop, IDEs, your own agent)
can now discover and call these tools - you wrote the integration ONCE.

    python mcp_server.py                 # speaks MCP over stdin/stdout (clients launch it for you)

Client config example (e.g. Claude Desktop / Claude Code):
    {"mcpServers": {"policy-kb": {"command": "python", "args": ["<abs path>/mcp_server.py"]}}}

Uses mcp>=2 (`MCPServer`). On mcp 1.x the class was `mcp.server.fastmcp.FastMCP` - same decorators.
SECURITY: this server is READ-ONLY by design. Never log to stdout (it is the protocol channel); use stderr.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from research.retrieval import HybridIndex  # noqa: E402

DOCS = Path(__file__).parent / "data" / "docs"
index = HybridIndex.from_directory(DOCS)
mcp = MCPServer("policy-kb")


@mcp.tool()
def search_policies(query: str, k: int = 3) -> list[dict]:
    """Search company policy documents (remote work, expenses, security, leave).
    Returns the best passages with citation ids like remote_work#1."""
    k = max(1, min(k, 5))   # clamp untrusted argument
    return [{"cite": h.chunk.cite, "text": h.chunk.text} for h in index.search(query, k)]


@mcp.tool()
def list_policy_documents() -> list[str]:
    """List available policy document ids."""
    return sorted({c.doc_id for c in index.chunks})


@mcp.resource("policy://{doc_id}")
def read_policy(doc_id: str) -> str:
    """Read a whole policy document."""
    if doc_id not in {c.doc_id for c in index.chunks}:   # validate: no path traversal via doc_id
        raise ValueError("unknown document")
    return (DOCS / f"{doc_id}.md").read_text(encoding="utf-8")


if __name__ == "__main__":
    mcp.run()  # stdio transport
