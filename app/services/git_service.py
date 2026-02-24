import os
import subprocess
import shutil
import logging
from pathlib import Path
from datetime import datetime

class GitService:
    def __init__(self, repo_path):
        """
        Initialize the GitService.
        
        Args:
            repo_path (str): The absolute path to the repository (e.g., notion_output).
        """
        self.cwd = Path(repo_path).resolve()
        
        # Load configuration from environment variables
        self.git_remote_url = os.getenv("GIT_REMOTE_URL")
        self.git_branch = os.getenv("GIT_BRANCH", "main")
        self.git_user_name = os.getenv("GIT_USER_NAME")
        self.git_user_email = os.getenv("GIT_USER_EMAIL")

    def _run_git(self, args):
        """
        Helper to run git commands in the repo directory.
        
        Args:
            args (list): List of command arguments (e.g., ["init"]).
            
        Returns:
            subprocess.CompletedProcess: The result of the command execution.
        """
        try:
            # Ensure cwd exists before running command, although init_repo handles creation
            if not self.cwd.exists():
                self.cwd.mkdir(parents=True, exist_ok=True)

            logging.info(f"Running git command: git {' '.join(args)} in {self.cwd}")
            result = subprocess.run(
                ["git"] + args,
                cwd=self.cwd,
                capture_output=True,
                text=True,
                check=True
            )
            return result
        except subprocess.CalledProcessError as e:
            logging.error(f"Git command failed: git {' '.join(args)}")
            logging.error(f"Stdout: {e.stdout}")
            logging.error(f"Stderr: {e.stderr}")
            raise e

    def init_repo(self):
        """
        Initialize the git repository.
        If the directory exists but is not a git repo, prioritize clearing it and cloning from remote.
        Otherwise, initialize a new repo and configure it.
        """
        # Ensure the directory exists
        if not self.cwd.exists():
            self.cwd.mkdir(parents=True, exist_ok=True)
            
        git_dir = self.cwd / ".git"
        
        # Check if it's already a git repo
        if git_dir.exists():
            logging.info(f"Git repository already exists in {self.cwd}")
            # Optional: Verify remote URL matches?
            return

        logging.info(f"Initializing git repository in {self.cwd}...")

        # Strategy: If not a git repo, try to clone first if remote URL is provided
        if self.git_remote_url:
            try:
                # If directory is not empty, clear it to allow clone
                if any(self.cwd.iterdir()):
                    logging.warning(f"Directory {self.cwd} is not empty and not a git repo. Clearing it for fresh clone...")
                    shutil.rmtree(self.cwd)
                    self.cwd.mkdir(parents=True, exist_ok=True)
                
                logging.info(f"Cloning from {self.git_remote_url}...")
                subprocess.run(
                    ["git", "clone", self.git_remote_url, "."],
                    cwd=self.cwd,
                    check=True,
                    capture_output=True,
                    text=True
                )
                logging.info("Clone successful.")
                
                # Checkout the specific branch if needed
                try:
                    self._run_git(["checkout", self.git_branch])
                except subprocess.CalledProcessError:
                    # Branch might not exist locally, try creating it tracking remote
                    try:
                        self._run_git(["checkout", "-b", self.git_branch, f"origin/{self.git_branch}"])
                    except subprocess.CalledProcessError:
                         # If remote branch doesn't exist, just create local
                         self._run_git(["checkout", "-b", self.git_branch])

                # Configure user
                if self.git_user_name:
                    self._run_git(["config", "user.name", self.git_user_name])
                if self.git_user_email:
                    self._run_git(["config", "user.email", self.git_user_email])
                    
                return
            except subprocess.CalledProcessError as e:
                logging.warning(f"Git clone failed: {e.stderr}. Falling back to manual init.")
                # Re-create directory if it was deleted
                if not self.cwd.exists():
                    self.cwd.mkdir(parents=True, exist_ok=True)

        # Fallback: Manual Init
        self._run_git(["init"])
        
        if self.git_remote_url:
            try:
                self._run_git(["remote", "add", "origin", self.git_remote_url])
            except subprocess.CalledProcessError:
                # Remote might already exist if init was run before
                self._run_git(["remote", "set-url", "origin", self.git_remote_url])

        self._run_git(["branch", "-M", self.git_branch])

        # Configure user
        if self.git_user_name:
            self._run_git(["config", "user.name", self.git_user_name])
        if self.git_user_email:
            self._run_git(["config", "user.email", self.git_user_email])

        # Try to pull to sync history
        if self.git_remote_url:
            try:
                logging.info("Attempting to pull from remote...")
                self._run_git(["pull", "origin", self.git_branch])
            except subprocess.CalledProcessError as e:
                logging.warning(f"Git pull failed (normal for empty repo): {e.stderr}")

    def pull_latest(self):
        """
        Pull the latest changes from the remote repository.
        Should be called at startup before any Notion API operations.
        """
        if not self.git_remote_url:
            logging.warning("No remote URL configured. Skipping pull.")
            return

        try:
            logging.info(f"Pulling latest changes from origin {self.git_branch}...")
            self._run_git(["pull", "origin", self.git_branch])
            logging.info("Pull successful.")
        except subprocess.CalledProcessError as e:
            logging.warning(f"Pull failed (may be normal for empty repo): {e.stderr}")

    def sync_changes(self):
        """
        Sync changes to the remote repository.
        Adds all changes, commits with timestamp, and pushes.
        Uses auto-rebase with conflict resolution for multi-client scenarios.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            logging.info("Syncing changes...")
            self._run_git(["add", "."])
            
            status = self._run_git(["status", "--porcelain"])
            if not status.stdout.strip():
                logging.info("No changes to commit.")
                return

            commit_message = f"Backup: {timestamp}"
            self._run_git(["commit", "-m", commit_message])
            
            if self.git_remote_url:
                try:
                    logging.info(f"Pulling with rebase from origin {self.git_branch}...")
                    self._run_git([
                        "pull", "--rebase", "origin", self.git_branch,
                        "-s", "recursive", "-X", "theirs"
                    ])
                    logging.info("Rebase successful.")
                except subprocess.CalledProcessError as e:
                    logging.error(f"Rebase failed, attempting to abort: {e.stderr}")
                    try:
                        self._run_git(["rebase", "--abort"])
                    except subprocess.CalledProcessError:
                        pass
                    raise e

                logging.info(f"Pushing to origin {self.git_branch}...")
                self._run_git(["push", "-u", "origin", self.git_branch])
                logging.info("Push successful.")
            else:
                logging.warning("No remote URL configured. Skipping push.")
                
        except subprocess.CalledProcessError as e:
            logging.error(f"Sync failed: {e.stderr}")
            raise e
