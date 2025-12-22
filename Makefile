.PHONY: run dev run-http inspect test bump-patch bump-minor bump-major

run:
	uv run open-notebook-mcp

dev:
	mcp dev src/open_notebook_mcp/server.py

run-http:
	MCP_TRANSPORT=streamable-http HOST=0.0.0.0 PORT=8000 uv run open-notebook-mcp

inspect:
	npx @modelcontextprotocol/inspector uv --directory ./src/open_notebook_mcp "run" "server.py"

test:
	uv run pytest

bump-patch:
	@echo "Bumping patch version..."
	@python3 -c "import re; \
	content = open('pyproject.toml').read(); \
	match = re.search(r'version = \"(\d+)\.(\d+)\.(\d+)\"', content); \
	new_version = f'{match.group(1)}.{match.group(2)}.{int(match.group(3))+1}'; \
	content = re.sub(r'version = \"\d+\.\d+\.\d+\"', f'version = \"{new_version}\"', content); \
	open('pyproject.toml', 'w').write(content); \
	print(f'Updated pyproject.toml to {new_version}'); \
	content = open('server.json').read(); \
	content = re.sub(r'\"version\": \"\d+\.\d+\.\d+\"', f'\"version\": \"{new_version}\"', content); \
	open('server.json', 'w').write(content); \
	print(f'Updated server.json to {new_version}')"

bump-minor:
	@echo "Bumping minor version..."
	@python3 -c "import re; \
	content = open('pyproject.toml').read(); \
	match = re.search(r'version = \"(\d+)\.(\d+)\.(\d+)\"', content); \
	new_version = f'{match.group(1)}.{int(match.group(2))+1}.0'; \
	content = re.sub(r'version = \"\d+\.\d+\.\d+\"', f'version = \"{new_version}\"', content); \
	open('pyproject.toml', 'w').write(content); \
	print(f'Updated pyproject.toml to {new_version}'); \
	content = open('server.json').read(); \
	content = re.sub(r'\"version\": \"\d+\.\d+\.\d+\"', f'\"version\": \"{new_version}\"', content); \
	open('server.json', 'w').write(content); \
	print(f'Updated server.json to {new_version}')"

bump-major:
	@echo "Bumping major version..."
	@python3 -c "import re; \
	content = open('pyproject.toml').read(); \
	match = re.search(r'version = \"(\d+)\.(\d+)\.(\d+)\"', content); \
	new_version = f'{int(match.group(1))+1}.0.0'; \
	content = re.sub(r'version = \"\d+\.\d+\.\d+\"', f'version = \"{new_version}\"', content); \
	open('pyproject.toml', 'w').write(content); \
	print(f'Updated pyproject.toml to {new_version}'); \
	content = open('server.json').read(); \
	content = re.sub(r'\"version\": \"\d+\.\d+\.\d+\"', f'\"version\": \"{new_version}\"', content); \
	open('server.json', 'w').write(content); \
	print(f'Updated server.json to {new_version}')"
