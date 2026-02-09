"""
Agent implementations for the agent-of-agents system.
Each agent is a specialized wrapper around an LLM call with specific system prompts.
"""

import json
import subprocess
import os
import re
from typing import Generator


class LLMBackend:
    """Abstraction over LLM providers."""

    def __init__(self, provider="anthropic", api_key=None, model="claude-sonnet-4-20250514"):
        self.provider = provider
        self.api_key = api_key
        self.model = model

    def call(self, system_prompt: str, user_message: str) -> str:
        if self.provider == "anthropic" and self.api_key:
            return self._call_anthropic(system_prompt, user_message)
        else:
            return self._call_mock(system_prompt, user_message)

    def _call_anthropic(self, system_prompt: str, user_message: str) -> str:
        import anthropic
        client = anthropic.Anthropic(api_key=self.api_key)
        response = client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text

    def _call_mock(self, system_prompt: str, user_message: str) -> str:
        """Demo mode: generates realistic structured responses based on agent role."""
        if "planner" in system_prompt.lower() or "planning" in system_prompt.lower():
            return self._mock_plan(user_message)
        elif "implement" in system_prompt.lower():
            return self._mock_implement(user_message)
        elif "fix" in system_prompt.lower() or "debug" in system_prompt.lower():
            return self._mock_fix(user_message)
        else:
            return f"[Agent Response] Processed: {user_message[:200]}"

    def _mock_plan(self, user_message: str) -> str:
        return json.dumps({
            "project_name": self._extract_project_name(user_message),
            "description": f"Implementation plan for: {user_message[:100]}",
            "steps": [
                {"step": 1, "action": "Create project structure", "details": "Set up directories and configuration files"},
                {"step": 2, "action": "Implement core logic", "details": "Build the main functionality as described"},
                {"step": 3, "action": "Add tests", "details": "Write unit tests for core functionality"},
                {"step": 4, "action": "Add error handling", "details": "Implement proper error handling and validation"},
            ],
            "files_to_create": [
                {"path": "main.py", "purpose": "Main application entry point"},
                {"path": "lib.py", "purpose": "Core library functions"},
                {"path": "test_main.py", "purpose": "Unit tests"},
            ],
            "test_command": "python3 -m pytest test_main.py -v",
        }, indent=2)

    def _mock_implement(self, user_message: str) -> str:
        project_name = self._extract_project_name(user_message)
        return json.dumps({
            "files": [
                {
                    "path": "main.py",
                    "content": f'"""Main module for {project_name}."""\n\nfrom lib import process\n\n\ndef main():\n    result = process("input")\n    print(f"Result: {{result}}")\n    return result\n\n\nif __name__ == "__main__":\n    main()\n',
                },
                {
                    "path": "lib.py",
                    "content": f'"""Core library for {project_name}."""\n\n\ndef process(data: str) -> str:\n    """Process input data and return result."""\n    if not data:\n        raise ValueError("Input data cannot be empty")\n    return f"processed_{{data}}"\n\n\ndef validate(data: str) -> bool:\n    """Validate input data."""\n    return isinstance(data, str) and len(data) > 0\n',
                },
                {
                    "path": "test_main.py",
                    "content": f'"""Tests for {project_name}."""\nimport pytest\nfrom lib import process, validate\nfrom main import main\n\n\ndef test_process():\n    assert process("hello") == "processed_hello"\n\n\ndef test_process_empty_raises():\n    with pytest.raises(ValueError):\n        process("")\n\n\ndef test_validate():\n    assert validate("test") is True\n    assert validate("") is False\n\n\ndef test_main(capsys):\n    result = main()\n    captured = capsys.readouterr()\n    assert "Result:" in captured.out\n    assert result == "processed_input"\n',
                },
            ],
            "summary": f"Implemented {project_name} with main module, core library, and tests.",
        }, indent=2)

    def _mock_fix(self, user_message: str) -> str:
        return json.dumps({
            "analysis": "Identified failing test due to edge case in validation logic.",
            "fixes": [
                {
                    "path": "lib.py",
                    "content": '"""Core library (fixed)."""\n\n\ndef process(data: str) -> str:\n    """Process input data and return result."""\n    if not data:\n        raise ValueError("Input data cannot be empty")\n    return f"processed_{data}"\n\n\ndef validate(data: str) -> bool:\n    """Validate input data."""\n    return isinstance(data, str) and len(data) > 0\n',
                }
            ],
            "summary": "Fixed validation logic to handle edge cases properly.",
        }, indent=2)

    def _extract_project_name(self, text: str) -> str:
        words = re.sub(r'[^\w\s]', '', text).split()[:3]
        return "_".join(w.lower() for w in words) if words else "project"


class PlannerAgent:
    """Creates an implementation plan from a user request."""

    SYSTEM_PROMPT = """You are a Planning Agent. Your job is to analyze a user's request and create a detailed implementation plan.

You MUST respond with a JSON object containing:
{
  "project_name": "short_name",
  "description": "What will be built",
  "steps": [{"step": 1, "action": "...", "details": "..."}],
  "files_to_create": [{"path": "filename.py", "purpose": "..."}],
  "test_command": "command to run tests"
}

Keep plans practical and focused. Prefer Python for implementation unless specified otherwise."""

    def __init__(self, llm: LLMBackend):
        self.llm = llm

    def run(self, user_request: str) -> dict:
        response = self.llm.call(self.SYSTEM_PROMPT, user_request)
        try:
            # Try to extract JSON from the response
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
        return {"raw_plan": response, "project_name": "project", "files_to_create": [], "test_command": "echo 'no tests'", "steps": []}


class ImplementerAgent:
    """Implements code based on a plan."""

    SYSTEM_PROMPT = """You are an Implementation Agent. Given a plan, write the actual code files.

You MUST respond with a JSON object containing:
{
  "files": [{"path": "filename.py", "content": "full file content"}],
  "summary": "Brief summary of what was implemented"
}

Write clean, working, tested code. Include proper error handling.
Always include test files with pytest-compatible tests."""

    def __init__(self, llm: LLMBackend):
        self.llm = llm

    def run(self, plan: dict, user_request: str) -> dict:
        prompt = f"""Original request: {user_request}

Plan to implement:
{json.dumps(plan, indent=2)}

Implement all files listed in the plan. Write complete, working code."""
        response = self.llm.call(self.SYSTEM_PROMPT, prompt)
        try:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
        return {"files": [], "summary": response[:500]}


class FixerAgent:
    """Fixes code based on test failures."""

    SYSTEM_PROMPT = """You are a Bug-Fixing Agent. Given test failures and the current code, fix the issues.

You MUST respond with a JSON object containing:
{
  "analysis": "What went wrong",
  "fixes": [{"path": "filename.py", "content": "full corrected file content"}],
  "summary": "Brief summary of fixes applied"
}

Only fix what's broken. Keep changes minimal and targeted."""

    def __init__(self, llm: LLMBackend):
        self.llm = llm

    def run(self, test_output: str, current_files: dict, attempt: int) -> dict:
        prompt = f"""Test failure (attempt {attempt}):
{test_output}

Current files:
{json.dumps(current_files, indent=2)}

Fix the failing tests. Return corrected file contents."""
        response = self.llm.call(self.SYSTEM_PROMPT, prompt)
        try:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
        return {"analysis": response[:500], "fixes": [], "summary": "Could not parse fix response"}


class TesterAgent:
    """Runs tests and returns results."""

    def __init__(self, workspace_dir: str):
        self.workspace_dir = workspace_dir

    def run(self, test_command: str) -> dict:
        """Run tests and return structured results."""
        try:
            result = subprocess.run(
                test_command,
                shell=True,
                cwd=self.workspace_dir,
                capture_output=True,
                text=True,
                timeout=60,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            passed = result.returncode == 0
            output = result.stdout + "\n" + result.stderr
            return {
                "passed": passed,
                "return_code": result.returncode,
                "output": output.strip(),
                "summary": "All tests passed!" if passed else "Some tests failed.",
            }
        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "return_code": -1,
                "output": "Test execution timed out after 60 seconds.",
                "summary": "Tests timed out.",
            }
        except Exception as e:
            return {
                "passed": False,
                "return_code": -1,
                "output": str(e),
                "summary": f"Error running tests: {e}",
            }


class GitAgent:
    """Handles git operations."""

    def __init__(self, workspace_dir: str):
        self.workspace_dir = workspace_dir

    def init_repo(self) -> str:
        """Initialize a git repo if not already one."""
        try:
            subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=self.workspace_dir,
                capture_output=True,
                check=True,
            )
            return "Repository already initialized."
        except subprocess.CalledProcessError:
            subprocess.run(
                ["git", "init"],
                cwd=self.workspace_dir,
                capture_output=True,
                check=True,
            )
            return "Initialized new git repository."

    def commit(self, message: str) -> str:
        """Stage all changes and commit."""
        try:
            subprocess.run(
                ["git", "add", "-A"],
                cwd=self.workspace_dir,
                capture_output=True,
                check=True,
            )
            result = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=self.workspace_dir,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return f"Committed: {message}\n{result.stdout.strip()}"
            else:
                return f"Nothing to commit or error: {result.stderr.strip()}"
        except Exception as e:
            return f"Git error: {e}"

    def get_log(self, n: int = 5) -> str:
        """Get recent git log."""
        try:
            result = subprocess.run(
                ["git", "log", f"--oneline", f"-{n}"],
                cwd=self.workspace_dir,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip() or "No commits yet."
        except Exception:
            return "No git history available."

    def get_diff(self) -> str:
        """Get current diff."""
        try:
            result = subprocess.run(
                ["git", "diff", "--stat"],
                cwd=self.workspace_dir,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip() or "No changes."
        except Exception:
            return "Cannot generate diff."
