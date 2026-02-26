"""
GitHub API client for accessing repositories without cloning.
Uses GitHub REST API directly with a personal access token.

Environment variable required:
    GITHUB_PERSONAL_ACCESS_TOKEN: GitHub personal access token with repo read access.
"""

import asyncio
import base64
import json
import logging
import os
import re
import yaml
import httpx

from github_repo_client import defaults

logger = logging.getLogger(__name__)


class MCPGitHubClient:
    """GitHub API client for repository access without cloning."""

    def __init__(self, repo_url: str, github_token: str | None = None):
        self.repo_url = repo_url
        self.owner, self.repo = self._parse_github_url(repo_url)
        # Accept token explicitly or fall back to environment variable
        self.token = github_token or os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN", "")
        self.base_url = "https://api.github.com"
        self._client = None

    @staticmethod
    def _parse_github_url(url: str) -> tuple[str, str]:
        """Extract owner and repo name from a GitHub URL."""
        url = url.rstrip("/")
        if url.endswith(".git"):
            url = url[:-4]
        match = re.match(r"https?://github\.com/([^/]+)/([^/]+)", url)
        if match:
            return match.group(1), match.group(2)
        raise ValueError(f"Invalid GitHub URL: {url}")

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def connect(self):
        """Initialize HTTP client."""
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"token {self.token}",
                "Accept": "application/vnd.github.v3+json",
            },
            timeout=30.0,
        )
        logger.info(f"GitHub API client initialized for {self.owner}/{self.repo}")
        logger.info("Using token authentication (no local clone needed)")

    async def disconnect(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Repository operations
    # ------------------------------------------------------------------

    async def get_file_contents(self, path: str = "") -> str:
        """
        Fetch file or directory contents from the repository via GitHub API.

        For a directory returns a JSON array describing its children.
        For a file returns the decoded content.
        """
        if not self._client:
            raise RuntimeError("Client not connected. Call connect() first.")

        url = f"{self.base_url}/repos/{self.owner}/{self.repo}/contents/{path}"

        try:
            response = await self._client.get(url)
            response.raise_for_status()
            data = response.json()

            # Directory - return as JSON array
            if isinstance(data, list):
                logger.debug(f"Fetched directory via GitHub API: {path} ({len(data)} items)")
                return json.dumps(data)

            # File - decode base64 content
            if isinstance(data, dict) and data.get("type") == "file":
                content_b64 = data.get("content", "")
                content_bytes = base64.b64decode(content_b64)
                logger.debug(f"Fetched file via GitHub API: {path} ({len(content_bytes)} bytes)")
                return content_bytes.decode("utf-8", errors="ignore")

            return json.dumps(data)

        except httpx.HTTPStatusError as e:
            logger.error(f"GitHub API error for {path}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to fetch {path}: {e}")
            raise

    async def get_multiple_files(
            self, paths: list[str], concurrency: int = 5
    ) -> dict[str, str]:
        """
        Fetch contents of several files concurrently.

        Returns:
            Dict mapping file path → content string.
        """
        results: dict[str, str] = {}
        semaphore = asyncio.Semaphore(concurrency)

        async def _fetch(p: str):
            async with semaphore:
                try:
                    content = await self.get_file_contents(p)
                    results[p] = content
                except Exception as e:
                    logger.warning(f"GitHub API: failed to fetch '{p}': {e}")

        await asyncio.gather(*[_fetch(p) for p in paths])
        return results


# ======================================================================
# High-level provider — replaces RepoCloner + ServiceIdentifier +
# CodeAnalyzer.collect_relevant_files() when using MCP
# ======================================================================

class MCPRepoProvider:
    """
    Browse a GitHub repository via the GitHub API and produce the same
    data structures that ServiceIdentifier and CodeAnalyzer produce
    from a local clone.

    Usage:
        provider = MCPRepoProvider("https://github.com/org/repo.git")
        await provider.initialize()
        services, service_files = await provider.get_services_and_files()
        await provider.cleanup()

    Custom config (optional):
        provider = MCPRepoProvider(
            repo_url="https://github.com/org/repo.git",
            file_extensions={"python": [".py"]},
            dependency_files={"python": ["requirements.txt"]},
            ignore_directories=["node_modules", ".git"],
        )
    """

    def __init__(
            self,
            repo_url: str,
            github_token: str | None = None,
            file_extensions: dict | None = None,
            dependency_files: dict | None = None,
            ignore_directories: list | None = None,
    ):
        self.repo_url = repo_url
        self.client = MCPGitHubClient(repo_url, github_token=github_token)
        self._dir_cache: dict[str, list[dict]] = {}

        # Use provided config or fall back to package defaults
        self.file_extensions = file_extensions or defaults.FILE_EXTENSIONS
        self.dependency_files = dependency_files or defaults.DEPENDENCY_FILES
        self.ignore_directories = ignore_directories or defaults.IGNORE_DIRECTORIES

    async def initialize(self):
        """Connect to the GitHub API."""
        await self.client.connect()

    async def cleanup(self):
        """Disconnect from the GitHub API."""
        await self.client.disconnect()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_services_and_files(self) -> tuple[dict, dict]:
        """
        Identify every microservice in the repo and collect its
        source files — all via GitHub API (no local clone).

        Returns:
            (services, service_files) where the shapes match
            ServiceIdentifier.identify_services() and
            CodeAnalyzer.collect_relevant_files().
        """
        services = await self._identify_services()

        if not services:
            raise ValueError("No services found in repository via MCP")

        logger.info(f"MCP: found {len(services)} services: {', '.join(services.keys())}")

        service_files = await self._collect_service_files(services)
        return services, service_files

    async def identify_services_only(self) -> dict:
        """Identify services without collecting their source files."""
        services = await self._identify_services()
        if not services:
            raise ValueError("No services found in repository via MCP")
        logger.info(f"MCP: found {len(services)} services: {', '.join(services.keys())}")
        return services

    # ------------------------------------------------------------------
    # Service identification
    # ------------------------------------------------------------------

    async def _identify_services(self) -> dict:
        services: dict = {}
        root_items = await self._list_directory("")
        logger.info(f"MCP: Found {len(root_items)} items in root directory")
        logger.debug(f"MCP: Root items: {[item.get('name') for item in root_items]}")

        await self._check_docker_compose(root_items, services)
        logger.info(f"MCP: After docker-compose check: {len(services)} services")

        await self._check_dockerfiles(root_items, services)
        logger.info(f"MCP: After dockerfiles check: {len(services)} services")

        await self._check_package_files(root_items, services)
        logger.info(f"MCP: After package files check: {len(services)} services")

        # Fill in any still-unknown languages
        for svc_info in services.values():
            if svc_info["language"] == "unknown":
                svc_info["language"] = await self._detect_language(svc_info["path"])

        logger.info(f"MCP: Final services identified: {list(services.keys())}")
        return services

    async def _check_docker_compose(self, root_items: list[dict], services: dict):
        compose_names = {"docker-compose.yml", "docker-compose.yaml"}
        logger.debug(f"MCP: Checking for docker-compose files in {len(root_items)} root items")

        for item in root_items:
            if item.get("name") not in compose_names:
                continue
            if item.get("type") != "file":
                continue

            logger.info(f"MCP: Found docker-compose file: {item.get('name')}")
            try:
                content = await self.client.get_file_contents(item["path"])
                compose_data = yaml.safe_load(content)

                if not compose_data or "services" not in compose_data:
                    logger.warning("MCP: docker-compose has no services section")
                    continue

                logger.info(f"MCP: docker-compose defines services: {list(compose_data['services'].keys())}")

                root_dirs = {i["name"] for i in root_items if i.get("type") == "dir"}
                logger.debug(f"MCP: Root directories: {root_dirs}")

                for svc_name, svc_cfg in compose_data["services"].items():
                    build_path = self._extract_build_path(svc_cfg)
                    dir_name = None

                    if build_path:
                        # Remove leading "./" prefix and trailing slashes
                        clean = build_path.removeprefix("./").rstrip("/")

                        if clean in root_dirs:
                            dir_name = clean
                        else:
                            # Verify nested path exists via API (e.g., "services/auth-service")
                            try:
                                nested_items = await self._list_directory(clean)
                                if nested_items:
                                    dir_name = clean
                                    logger.debug(f"MCP: Verified nested path exists: {clean}")
                            except Exception as e:
                                logger.debug(f"MCP: Could not verify path '{clean}': {e}")

                    # Fallback: service name matches a root directory
                    if not dir_name and svc_name in root_dirs:
                        dir_name = svc_name

                    if not dir_name:
                        logger.warning(
                            f"MCP: Could not find directory for service '{svc_name}' (build_path={build_path})")
                    elif svc_name in services:
                        logger.debug(
                            f"MCP: Service '{svc_name}' already exists, skipping duplicate from docker-compose")
                    else:
                        services[svc_name] = {
                            "path": dir_name,
                            "language": "unknown",
                            "source": "docker-compose",
                        }
                        logger.info(f"MCP: Added service '{svc_name}' from docker-compose (path: {dir_name})")

            except Exception as e:
                logger.warning(f"MCP: failed to parse docker-compose: {e}")

    async def _check_dockerfiles(self, root_items: list[dict], services: dict):
        ignore = set(self.ignore_directories)
        for item in root_items:
            if item.get("type") != "dir" or item["name"] in ignore:
                continue
            if item["name"] in services:
                continue

            sub_items = await self._list_directory(item["path"])
            if any(si.get("name") == "Dockerfile" for si in sub_items):
                language = self._detect_language_from_items(sub_items)
                services[item["name"]] = {
                    "path": item["path"],
                    "language": language,
                    "source": "dockerfile",
                }

    async def _check_package_files(self, root_items: list[dict], services: dict):
        """
        Look for dependency files to identify services.
        Checks root-level directories and recursively searches common
        service container directories (services/, apps/, packages/, microservices/).
        """
        ignore = set(self.ignore_directories)

        # Check root-level directories
        for item in root_items:
            if item.get("type") != "dir" or item["name"] in ignore:
                continue
            if item["name"] in services:
                continue

            sub_items = await self._list_directory(item["path"])
            sub_names = {si["name"] for si in sub_items}

            for language, dep_files in self.dependency_files.items():
                for dep_file in dep_files:
                    if dep_file in sub_names and item["name"] not in services:
                        services[item["name"]] = {
                            "path": item["path"],
                            "language": language,
                            "source": dep_file,
                        }
                        break
                if item["name"] in services:
                    break

        # Recursively scan common container directories
        common_containers = ["services", "apps", "packages", "microservices"]
        for container_name in common_containers:
            container_item = next(
                (item for item in root_items
                 if item.get("name") == container_name and item.get("type") == "dir"),
                None,
            )
            if container_item:
                await self._scan_for_services_recursive(container_item["path"], services)

    async def _scan_for_services_recursive(
            self, dir_path: str, services: dict, depth: int = 0, max_depth: int = 10
    ):
        """
        Recursively scan a directory for services based on dependency files.
        Avoids scanning subdirectories of already-identified services.
        """
        if depth > max_depth:
            logger.debug(f"MCP: Reached max_depth={max_depth} for service scan at '{dir_path}'")
            return

        items = await self._list_directory(dir_path)
        if not items:
            return

        ignore = set(self.ignore_directories)

        for item in items:
            if item.get("type") != "dir" or item.get("name") in ignore:
                continue

            service_name = item.get("name")
            service_path = item.get("path")

            if service_name in services:
                logger.debug(f"MCP: Skipping '{service_name}' - already identified")
                continue

            # Skip subdirectories of already-identified services
            is_subdirectory = any(
                service_path.startswith(info["path"].rstrip("/") + "/")
                for info in services.values()
            )
            if is_subdirectory:
                logger.debug(f"MCP: Skipping '{service_path}' - subdirectory of existing service")
                continue

            sub_items = await self._list_directory(service_path)
            sub_names = {si.get("name", "") for si in sub_items}

            service_found = False
            for language, dep_files in self.dependency_files.items():
                for dep_file in dep_files:
                    if dep_file in sub_names:
                        services[service_name] = {
                            "path": service_path,
                            "language": language,
                            "source": dep_file,
                        }
                        logger.info(f"MCP: Found service '{service_name}' via {dep_file} at {service_path}")
                        service_found = True
                        break
                if service_found:
                    break

            if not service_found:
                await self._scan_for_services_recursive(service_path, services, depth + 1)

    # ------------------------------------------------------------------
    # File collection
    # ------------------------------------------------------------------

    async def _collect_service_files(self, services: dict) -> dict:
        """Build a service_files dict identical to CodeAnalyzer output."""
        service_files: dict = {}

        for svc_name, svc_info in services.items():
            language = svc_info["language"]

            if language not in self.file_extensions:
                service_files[svc_name] = {"language": language, "files": []}
                continue

            extensions = set(self.file_extensions[language])
            skip_dirs = set(self.ignore_directories + ["tests", "test", "__tests__"])

            all_files = await self._list_files_recursive(svc_info["path"], skip_dirs, max_depth=50)

            matching_paths = [
                f["path"]
                for f in all_files
                if any(f["path"].endswith(ext) for ext in extensions)
            ]

            contents = await self.client.get_multiple_files(matching_paths)

            files_data = []
            svc_prefix = svc_info["path"].rstrip("/") + "/"
            for fpath, fcontent in contents.items():
                rel = fpath[len(svc_prefix):] if fpath.startswith(svc_prefix) else fpath
                files_data.append({"path": rel, "full_path": rel, "content": fcontent})

            service_files[svc_name] = {"language": language, "files": files_data}
            logger.info(f"MCP: collected {len(files_data)} files for '{svc_name}'")

        return service_files

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _list_directory(self, path: str) -> list[dict]:
        """List a directory's children (cached)."""
        if path in self._dir_cache:
            return self._dir_cache[path]

        try:
            raw = await self.client.get_file_contents(path)
            items = json.loads(raw)
            if isinstance(items, list):
                self._dir_cache[path] = items
                return items
        except (json.JSONDecodeError, TypeError):
            pass
        except Exception as e:
            logger.warning(f"MCP: failed to list directory '{path}': {e}")

        return []

    async def _list_files_recursive(
            self,
            path: str,
            skip_dirs: set[str],
            depth: int = 0,
            max_depth: int = 50,
    ) -> list[dict]:
        """
        Recursively collect all file entries under path.
        max_depth=50 matches the unlimited depth of local glob("**/*").
        """
        if depth > max_depth:
            logger.warning(f"MCP: Reached max_depth={max_depth} at '{path}', stopping recursion")
            return []

        items = await self._list_directory(path)
        files: list[dict] = []

        for item in items:
            if item.get("type") == "file":
                files.append(item)
            elif item.get("type") == "dir" and item.get("name") not in skip_dirs:
                sub = await self._list_files_recursive(item["path"], skip_dirs, depth + 1, max_depth)
                files.extend(sub)

        return files

    async def _detect_language(self, dir_path: str) -> str:
        items = await self._list_directory(dir_path)
        return self._detect_language_from_items(items)

    def _detect_language_from_items(self, items: list[dict]) -> str:
        names = {item.get("name", "") for item in items}
        for language, dep_files in self.dependency_files.items():
            for dep_file in dep_files:
                if dep_file in names:
                    return language
        return "unknown"

    @staticmethod
    def _extract_build_path(service_config: dict) -> str | None:
        build = service_config.get("build")
        if isinstance(build, str):
            return build
        if isinstance(build, dict):
            return build.get("context")
        return None
