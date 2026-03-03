# mcp-repo-client

Shared Python package for accessing GitHub repositories via the GitHub API — no cloning required.

Provides `MCPRepoProvider` for identifying services and collecting source files from a repo, and `RepoCloner` for local cloning if needed.

---

## Installation

Add to your service's `requirements.txt`:

```
git+https://github.com/AutoIntAPI/mcp-repo-client.git@main
```

Then install:

```bash
pip install -r requirements.txt
```

For **local development** (editable install with Pylance support):

```bash
pip install -e . --config-settings editable_mode=compat
```

---

## Requirements

Set this environment variable in your service:

```env
GITHUB_PERSONAL_ACCESS_TOKEN=ghp_your_token_here
```

The token needs `repo` read access.

---

## Usage

```python
from github_repo_client import MCPRepoProvider, RepoCloner

mcp_provider = MCPRepoProvider(
    "https://github.com/your-org/your-repo",
    file_extensions={"python": [".py"], "typescript": [".ts"], ...},
    dependency_files={"python": ["requirements.txt"], ...},
    ignore_directories=[".git", "node_modules", ...],
)

await mcp_provider.initialize()

# Get services + their source files (for analysis)
services, service_files = await mcp_provider.get_services_and_files()

# Or just get services (for scanning)
services = await mcp_provider.identify_services_only()

await mcp_provider.cleanup()
```

`file_extensions`, `dependency_files`, and `ignore_directories` must be provided explicitly — the package has no built-in defaults. Pass them from your service's own config (e.g., `Config.FILE_EXTENSIONS`).

---

## Keeping It Up To Date in Docker

To always run the latest version without rebuilding the image, add this to your service's `entrypoint.sh`:

```sh
pip install --quiet --upgrade --force-reinstall --no-deps \
    "git+https://github.com/AutoIntAPI/mcp-repo-client.git@main" \
    || echo "Warning: could not update, using cached version"
```

---

## Package vs Import Name

| Context | Name |
|---|---|
| pip / requirements.txt | `github-repo-client` |
| Python import | `github_repo_client` |
