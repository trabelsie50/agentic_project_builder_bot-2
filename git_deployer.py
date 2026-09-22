import os
import json
import logging
import subprocess
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, Tuple, List

from config import settings

logger = logging.getLogger(__name__)


class GitDeployer:
    """
    Manages local Git repositories, commits, and deployment to
    external hosts such as GitHub and Hugging Face Spaces.
    """

    def __init__(
        self,
        github_token: Optional[str] = None,
        github_username: Optional[str] = None,
        hf_token: Optional[str] = None,
        hf_username: Optional[str] = None
    ):
        self.github_token = github_token or getattr(settings, "github_token", "") or os.getenv("GITHUB_TOKEN", "")
        self.github_username = github_username or getattr(settings, "github_username", "") or os.getenv("GITHUB_USERNAME", "")
        self.hf_token = hf_token or getattr(settings, "huggingface_token", "") or os.getenv("HUGGINGFACE_TOKEN", "")
        self.hf_username = hf_username or getattr(settings, "huggingface_username", "") or os.getenv("HUGGINGFACE_USERNAME", "")

    def _run_cmd(self, cmd: List[str], cwd: str) -> Tuple[int, str, str]:
        """
        Executes a command using subprocess and returns returncode, stdout, stderr.
        """
        try:
            res = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False
            )
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except Exception as e:
            logger.error(f"Error executing command '{' '.join(cmd)}': {str(e)}")
            return -1, "", str(e)

    def init_repository(self, project_dir: str) -> bool:
        """
        Initializes a Git repository in project_dir if not already initialized.
        Also configures user settings and creates a default .gitignore if missing.
        """
        if not os.path.exists(project_dir):
            os.makedirs(project_dir, exist_ok=True)

        git_dir = os.path.join(project_dir, ".git")
        if not os.path.exists(git_dir):
            code, out, err = self._run_cmd(["git", "init"], cwd=project_dir)
            if code != 0:
                logger.error(f"Failed to initialize git repository: {err}")
                return False
            logger.info(f"Initialized empty Git repository in {project_dir}")

        self._run_cmd(["git", "config", "user.name", "Agentic Builder Bot"], cwd=project_dir)
        self._run_cmd(["git", "config", "user.email", "agent@builder.bot"], cwd=project_dir)

        gitignore_path = os.path.join(project_dir, ".gitignore")
        if not os.path.exists(gitignore_path):
            default_gitignore = (
                "__pycache__/\n"
                "*.py[cod]\n"
                "*$py.class\n"
                ".venv/\n"
                "env/\n"
                "venv/\n"
                ".env\n"
                "*.sqlite3\n"
                ".DS_Store\n"
            )
            try:
                with open(gitignore_path, "w", encoding="utf-8") as f:
                    f.write(default_gitignore)
            except Exception as e:
                logger.warning(f"Could not write default .gitignore: {e}")

        return True

    def commit_changes(self, project_dir: str, message: str = "Auto-generated project code") -> bool:
        """
        Stages all files and commits them in the local git repository.
        """
        if not self.init_repository(project_dir):
            return False

        code, out, err = self._run_cmd(["git", "add", "."], cwd=project_dir)
        if code != 0:
            logger.error(f"Git add failed: {err}")
            return False

        code_status, out_status, _ = self._run_cmd(["git", "status", "--porcelain"], cwd=project_dir)
        if not out_status:
            logger.info("No changes to commit in repository.")
            return True

        code_commit, out_commit, err_commit = self._run_cmd(["git", "commit", "-m", message], cwd=project_dir)
        if code_commit != 0:
            logger.error(f"Git commit failed: {err_commit}")
            return False

        logger.info(f"Successfully committed changes with message: '{message}'")
        return True

    def create_github_repository(self, repo_name: str, private: bool = True) -> Optional[str]:
        """
        Creates a new remote repository on GitHub using REST API.
        Returns the repository HTTP URL if successful.
        """
        if not self.github_token:
            logger.error("GitHub token is not configured.")
            return None

        url = "https://api.github.com/user/repos"
        headers = {
            "Authorization": f"Bearer {self.github_token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "AgenticProjectBuilderBot"
        }
        payload = json.dumps({
            "name": repo_name,
            "private": private,
            "description": "Project automatically generated by Agentic Builder Bot",
            "auto_init": False
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req) as response:
                if response.status in (200, 201):
                    data = json.loads(response.read().decode("utf-8"))
                    html_url = data.get("html_url")
                    logger.info(f"Created GitHub repository successfully: {html_url}")
                    return html_url
        except urllib.error.HTTPError as e:
            if e.code == 422:
                logger.info(f"GitHub repository '{repo_name}' already exists or name invalid.")
                if self.github_username:
                    return f"https://github.com/{self.github_username}/{repo_name}"
            else:
                logger.error(f"HTTP Error creating GitHub repo: {e.code} {e.reason}")
        except Exception as e:
            logger.error(f"Error creating GitHub repository: {str(e)}")

        if self.github_username:
            return f"https://github.com/{self.github_username}/{repo_name}"
        return None

    def push_to_github(
        self,
        project_dir: str,
        repo_name: str,
        private: bool = True,
        commit_message: str = "Deploy project code"
    ) -> Dict[str, Any]:
        """
        Commits local changes, creates remote GitHub repo if needed, and pushes code.
        """
        result = {
            "success": False,
            "repo_url": None,
            "error": None
        }

        if not os.path.exists(project_dir):
            result["error"] = f"Directory not found: {project_dir}"
            return result

        if not os.path.exists(os.path.join(project_dir, ".git")):
            init_success = self.init_git_repo(project_dir)
            if not init_success:
                result["error"] = "Failed to initialize Git repository."
                return result

        repo_url = self.create_github_repo(repo_name, private=private)
        if not repo_url:
            result["error"] = "Failed to create or retrieve GitHub repository URL."
            return result

        result["repo_url"] = repo_url
        auth_repo_url = self._format_authenticated_url(repo_url)

        ok, remotes = self._run_command(["git", "remote"], cwd=project_dir)
        if "origin" in remotes.splitlines():
            self._run_command(["git", "remote", "set-url", "origin", auth_repo_url], cwd=project_dir)
        else:
            self._run_command(["git", "remote", "add", "origin", auth_repo_url], cwd=project_dir)

        self._run_command(["git", "config", "user.name", "AI Bot"], cwd=project_dir)
        self._run_command(["git", "config", "user.email", "bot@ai-agent.local"], cwd=project_dir)

        ok, add_out = self._run_command(["git", "add", "."], cwd=project_dir)
        if not ok:
            result["error"] = f"Failed to stage files: {add_out}"
            return result

        ok, status = self._run_command(["git", "status", "--porcelain"], cwd=project_dir)
        if status.strip():
            ok, commit_out = self._run_command(["git", "commit", "-m", commit_message], cwd=project_dir)
            if not ok and "nothing to commit" not in commit_out:
                result["error"] = f"Failed to commit changes: {commit_out}"
                return result

        ok, branch_out = self._run_command(["git", "branch", "--show-current"], cwd=project_dir)
        branch = branch_out.strip()
        if not branch:
            self._run_command(["git", "branch", "-M", "main"], cwd=project_dir)
            branch = "main"

        ok, push_out = self._run_command(["git", "push", "-u", "origin", branch], cwd=project_dir)
        if not ok:
            ok_force, force_out = self._run_command(["git", "push", "-u", "origin", branch, "--force"], cwd=project_dir)
            if not ok_force:
                result["error"] = f"Failed to push to GitHub: {push_out} | Force push error: {force_out}"
                return result

        result["success"] = True
        return result

    def _format_authenticated_url(self, repo_url: str) -> str:
        """
        Formats repository URL with authentication token if present.
        """
        if not repo_url:
            return repo_url
        if self.github_token and repo_url.startswith("https://"):
            clean_url = repo_url.replace("https://", "")
            if clean_url.endswith(".git"):
                return f"https://x-access-token:{self.github_token}@{clean_url}"
            return f"https://x-access-token:{self.github_token}@{clean_url}.git"
        if not repo_url.endswith(".git"):
            return f"{repo_url}.git"
        return repo_url

    def deploy_project(
        self,
        project_dir: str,
        repo_name: str,
        private: bool = True,
        commit_message: str = "Deploy project code"
    ) -> Dict[str, Any]:
        """
        Deploy project directory to GitHub.
        """
        return self.push_to_github(
            project_dir=project_dir,
            repo_name=repo_name,
            private=private,
            commit_message=commit_message
        )


def deploy_to_github(
    project_dir: str,
    repo_name: str,
    github_token: Optional[str] = None,
    github_username: Optional[str] = None,
    private: bool = True
) -> Dict[str, Any]:
    """
    Convenience function to deploy a local project directory to GitHub.
    """
    deployer = GitDeployer(github_token=github_token, github_username=github_username)
    return deployer.deploy_project(
        project_dir=project_dir,
        repo_name=repo_name,
        private=private
    )
