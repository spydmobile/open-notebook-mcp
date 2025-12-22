.PHONY: run dev run-http inspect

run:
	uv run open-notebook-mcp

dev:
	mcp dev src/open_notebook_mcp/server.py

run-http:
	MCP_TRANSPORT=streamable-http HOST=0.0.0.0 PORT=8000 uv run open-notebook-mcp

inspect:
	npx @modelcontextprotocol/inspector uv --directory ./src/open_notebook_mcp "run" "server.py"
