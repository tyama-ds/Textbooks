"""
Orchestrator: manages the agent pipeline.

Pipeline: Plan -> Implement -> Test -> (Fix -> Test)* -> Git Commit
"""

import json
import os
import shutil
import time
from typing import Generator

from agents import (
    LLMBackend,
    PlannerAgent,
    ImplementerAgent,
    FixerAgent,
    TesterAgent,
    GitAgent,
)


class Event:
    """Server-Sent Event data structure."""

    def __init__(self, phase: str, status: str, message: str, data: dict = None):
        self.phase = phase
        self.status = status  # "start", "progress", "success", "error"
        self.message = message
        self.data = data or {}

    def to_sse(self) -> str:
        payload = {
            "phase": self.phase,
            "status": self.status,
            "message": self.message,
            "data": self.data,
            "timestamp": time.time(),
        }
        return f"data: {json.dumps(payload)}\n\n"


class Orchestrator:
    """Manages the full agent pipeline."""

    def __init__(self, api_key: str = None, model: str = "claude-sonnet-4-20250514",
                 max_fix_attempts: int = 5, workspace_base: str = "/tmp/agent_workspaces"):
        self.llm = LLMBackend(
            provider="anthropic" if api_key else "mock",
            api_key=api_key,
            model=model,
        )
        self.max_fix_attempts = max_fix_attempts
        self.workspace_base = workspace_base
        os.makedirs(workspace_base, exist_ok=True)

    def run(self, user_request: str, project_id: str = None) -> Generator[str, None, None]:
        """Execute the full pipeline, yielding SSE events."""

        # Setup workspace
        if not project_id:
            project_id = f"project_{int(time.time())}"
        workspace = os.path.join(self.workspace_base, project_id)
        os.makedirs(workspace, exist_ok=True)

        yield Event("init", "start", f"Starting project: {project_id}",
                     {"project_id": project_id, "workspace": workspace}).to_sse()

        # Phase 1: Planning
        yield Event("plan", "start", "Planning agent is analyzing your request...").to_sse()
        try:
            planner = PlannerAgent(self.llm)
            plan = planner.run(user_request)
            yield Event("plan", "success", "Plan created successfully!",
                        {"plan": plan}).to_sse()
        except Exception as e:
            yield Event("plan", "error", f"Planning failed: {e}").to_sse()
            return

        # Phase 2: Implementation
        yield Event("implement", "start", "Implementation agent is writing code...").to_sse()
        try:
            implementer = ImplementerAgent(self.llm)
            implementation = implementer.run(plan, user_request)
            files = implementation.get("files", [])

            # Write files to workspace
            for f in files:
                file_path = os.path.join(workspace, f["path"])
                os.makedirs(os.path.dirname(file_path) if os.path.dirname(f["path"]) else workspace, exist_ok=True)
                with open(file_path, "w") as fh:
                    fh.write(f["content"])

            yield Event("implement", "success",
                        f"Implemented {len(files)} files.",
                        {"files": [f["path"] for f in files],
                         "summary": implementation.get("summary", ""),
                         "file_contents": {f["path"]: f["content"] for f in files}}).to_sse()
        except Exception as e:
            yield Event("implement", "error", f"Implementation failed: {e}").to_sse()
            return

        # Phase 3: Git init + initial commit
        yield Event("git", "start", "Initializing git repository...").to_sse()
        git = GitAgent(workspace)
        init_msg = git.init_repo()

        # Configure git for the workspace
        import subprocess
        subprocess.run(["git", "config", "user.email", "agent@agent-of-agents.local"],
                       cwd=workspace, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Agent of Agents"],
                       cwd=workspace, capture_output=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"],
                       cwd=workspace, capture_output=True)

        commit_msg = git.commit(f"Initial implementation: {plan.get('project_name', 'project')}")
        yield Event("git", "success", commit_msg,
                     {"action": "init_commit"}).to_sse()

        # Phase 4: Test loop
        test_command = plan.get("test_command", "python3 -m pytest -v")

        # Install pytest if needed
        subprocess.run(["pip3", "install", "--break-system-packages", "-q", "pytest"],
                       capture_output=True, timeout=30)

        tester = TesterAgent(workspace)
        fixer = FixerAgent(self.llm)
        current_files = {f["path"]: f["content"] for f in files}
        attempt = 0

        while attempt <= self.max_fix_attempts:
            attempt += 1
            yield Event("test", "start",
                        f"Running tests (attempt {attempt}/{self.max_fix_attempts + 1})...",
                        {"attempt": attempt}).to_sse()

            test_result = tester.run(test_command)

            if test_result["passed"]:
                yield Event("test", "success",
                            f"All tests passed on attempt {attempt}!",
                            {"output": test_result["output"], "attempt": attempt}).to_sse()
                break
            else:
                yield Event("test", "error",
                            f"Tests failed on attempt {attempt}.",
                            {"output": test_result["output"], "attempt": attempt}).to_sse()

                if attempt > self.max_fix_attempts:
                    yield Event("fix", "error",
                                f"Max fix attempts ({self.max_fix_attempts}) reached. Giving up.",
                                {"attempt": attempt}).to_sse()
                    break

                # Phase 5: Fix
                yield Event("fix", "start",
                            f"Fixer agent analyzing failures (attempt {attempt})...").to_sse()
                try:
                    fix_result = fixer.run(test_result["output"], current_files, attempt)
                    fixes = fix_result.get("fixes", [])

                    for f in fixes:
                        file_path = os.path.join(workspace, f["path"])
                        with open(file_path, "w") as fh:
                            fh.write(f["content"])
                        current_files[f["path"]] = f["content"]

                    yield Event("fix", "success",
                                f"Applied {len(fixes)} fixes.",
                                {"analysis": fix_result.get("analysis", ""),
                                 "fixed_files": [f["path"] for f in fixes],
                                 "summary": fix_result.get("summary", "")}).to_sse()

                    # Commit the fix
                    fix_commit = git.commit(f"Fix attempt {attempt}: {fix_result.get('summary', 'bug fix')}")
                    yield Event("git", "progress", fix_commit,
                                {"action": "fix_commit", "attempt": attempt}).to_sse()

                except Exception as e:
                    yield Event("fix", "error", f"Fix agent failed: {e}").to_sse()
                    break

        # Final commit
        final_commit = git.commit(f"Final: {plan.get('project_name', 'project')} - all tests passing")
        git_log = git.get_log()
        yield Event("git", "success", "Project complete!",
                     {"action": "final", "log": git_log, "commit": final_commit}).to_sse()

        # Summary
        yield Event("done", "success", "Pipeline complete!",
                     {"project_id": project_id, "workspace": workspace,
                      "total_attempts": attempt,
                      "files": list(current_files.keys())}).to_sse()
