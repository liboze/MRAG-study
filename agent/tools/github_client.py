"""GitHub client — search repositories, inspect code, clone and run projects.

Uses the GitHub REST API (v3) for metadata and ``git`` for cloning.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from agent.utils.logger import get_logger

logger = get_logger(__name__)

_GITHUB_API = "https://api.github.com"


class GitHubClient:
    """Interact with GitHub repositories.

    Parameters
    ----------
    config:
        The ``github`` section from ``config.yaml``.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        self._cfg = config
        self._token = os.environ.get(config.get("token_env", "GITHUB_TOKEN"), "")
        self._max_results = int(config.get("max_search_results", 10))
        self._clone_base = config.get("clone_base_dir", "workspace/repos")
        os.makedirs(self._clone_base, exist_ok=True)

    # ── Internal HTTP helper ──────────────────────────────────────────────────

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = _GITHUB_API + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers: Dict[str, str] = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            logger.warning("GitHub API request failed for %s: %s", path, exc)
            return {}

    # ── Repository search ─────────────────────────────────────────────────────

    def search_repos(
        self,
        query: str,
        max_results: Optional[int] = None,
        sort: str = "stars",
        order: str = "desc",
    ) -> List[Dict[str, Any]]:
        """Search GitHub repositories by *query*.

        Returns list of dicts with ``full_name``, ``description``,
        ``stars``, ``url``, ``topics``, ``language``.
        """
        n = max_results or self._max_results
        data = self._get(
            "/search/repositories",
            {"q": query, "sort": sort, "order": order, "per_page": min(n, 100)},
        )
        items = data.get("items", [])
        logger.info("GitHub repo search | query=%r hits=%d", query, len(items))
        return [
            {
                "full_name": r["full_name"],
                "description": r.get("description", ""),
                "stars": r.get("stargazers_count", 0),
                "url": r.get("html_url", ""),
                "topics": r.get("topics", []),
                "language": r.get("language", ""),
                "default_branch": r.get("default_branch", "main"),
                "clone_url": r.get("clone_url", ""),
            }
            for r in items[:n]
        ]

    def get_readme(self, full_name: str) -> str:
        """Return the decoded README of *full_name* (``owner/repo``)."""
        import base64
        data = self._get(f"/repos/{full_name}/readme")
        content = data.get("content", "")
        try:
            return base64.b64decode(content).decode("utf-8")
        except Exception:
            return content

    def list_files(self, full_name: str, path: str = "") -> List[Dict[str, str]]:
        """List files/dirs in the repository tree at *path*."""
        data = self._get(f"/repos/{full_name}/contents/{path}")
        if isinstance(data, list):
            return [
                {"name": f["name"], "type": f["type"], "path": f["path"]}
                for f in data
            ]
        return []

    # ── Clone / run ───────────────────────────────────────────────────────────

    def clone_repo(self, clone_url: str, repo_name: str) -> str:
        """Clone a repository into ``<clone_base>/<repo_name>``.

        Returns the local path.  Skips cloning if the directory already exists.
        """
        dest = os.path.join(self._clone_base, repo_name.replace("/", "_"))
        if os.path.isdir(dest):
            logger.info("Repo already cloned at %s; pulling latest.", dest)
            subprocess.run(["git", "-C", dest, "pull", "--ff-only"], check=False, timeout=120)
            return dest
        cmd = ["git", "clone", "--depth", "1", clone_url, dest]
        logger.info("Cloning %s → %s", clone_url, dest)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error("git clone failed: %s", result.stderr)
            raise RuntimeError(f"git clone failed:\n{result.stderr}")
        return dest

    def run_command(
        self,
        cwd: str,
        command: List[str],
        timeout: int = 600,
        env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Run *command* inside *cwd* and return a result dict.

        Result dict keys: ``returncode``, ``stdout``, ``stderr``.
        """
        run_env = {**os.environ, **(env or {})}
        logger.info("Running command in %s: %s", cwd, " ".join(command))
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=run_env,
            )
        except subprocess.TimeoutExpired:
            return {"returncode": -1, "stdout": "", "stderr": "Timed out."}
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
