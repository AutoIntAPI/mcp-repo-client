"""
Module for cloning GitHub repositories.
"""

import logging
import os
import shutil
import subprocess
import stat
from pathlib import Path

logger = logging.getLogger(__name__)


class RepoCloner:
    """Handles cloning and cleaning up GitHub repositories."""

    def __init__(self, repo_url: str, clone_dir: str):
        self.repo_url = repo_url
        self.clone_dir = Path(clone_dir)
        self.repo_path = None

    def clone(self) -> Path:
        """Clone the repository. Returns Path to the cloned directory."""
        self.clone_dir.mkdir(parents=True, exist_ok=True)

        repo_name = self._extract_repo_name(self.repo_url)
        self.repo_path = self.clone_dir / repo_name

        if self.repo_path.exists():
            logger.info(f"Removing existing repository at {self.repo_path}")
            self._force_remove(self.repo_path)

        logger.info(f"Cloning repository from {self.repo_url}")

        try:
            subprocess.run(
                ["git", "clone", self.repo_url, str(self.repo_path)],
                capture_output=True,
                text=True,
                check=True,
            )
            logger.info(f"Repository cloned successfully to {self.repo_path}")
            return self.repo_path

        except subprocess.CalledProcessError as e:
            raise Exception(f"Failed to clone repository: {e.stderr}")
        except FileNotFoundError:
            raise Exception("Git is not installed or not in PATH")

    def cleanup(self):
        """Remove the cloned repository."""
        if self.repo_path and self.repo_path.exists():
            logger.info(f"Cleaning up repository at {self.repo_path}")
            self._force_remove(self.repo_path)

    def _force_remove(self, path: Path):
        """Force remove a directory, handling read-only files."""

        def handle_remove_readonly(func, path, exc):
            try:
                os.chmod(path, stat.S_IWRITE)
                func(path)
            except Exception as e:
                logger.warning(f"Could not remove {path}: {e}")

        try:
            shutil.rmtree(path, onerror=handle_remove_readonly)
        except Exception as e:
            logger.warning(f"Standard removal failed, trying system commands: {e}")
            try:
                if os.name == "nt":
                    subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(path)],
                                   check=True, capture_output=True, text=True)
                else:
                    subprocess.run(["rm", "-rf", str(path)],
                                   check=True, capture_output=True, text=True)
            except Exception as e2:
                logger.error(f"Could not remove directory with any method: {e2}")

    def _extract_repo_name(self, url: str) -> str:
        """Extract repository name from GitHub URL."""
        parts = url.rstrip("/").split("/")
        repo_name = parts[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]
        return repo_name
