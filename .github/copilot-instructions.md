# Copilot Instructions

## 1. Language & Environment Requirement
*   **Strictly English Only:** All code, comments, documentation, commit messages, and internal notes must be written in English.
*   **No Exceptions:** Even if the user communicates in another language, the output artifacts (files, code) must remain in English.
*   **Environment Activation:** Before running ANY python script or terminal command, you MUST activate the CUDA environment:
Command: `& .\.venv\Scripts\Activate.ps1`

## 2. Git & Commit Protocol
*   **User Approval Required:** You are NOT allowed to push any commits without explicit user approval.
*   **Propose Commits:** When a commit is necessary, you must propose it to the user first.
*   **Commit Message:** Always suggest a clear and concise commit message (in English) when proposing a commit.
*   **Update Docs Before Commit:** If a change requires updating project docs/status (e.g., `docs/implementation_status.md`, `README.md`, API docs), do that update before proposing or creating the commit.

### 2.1 Commit Message Naming Convention (Required)
When proposing a commit, always use this convention and keep it consistent across the project.

**Format (Conventional Commits):**
`<type>(<scope>): <subject>`

**Rules:**
* **Language:** English only.
* **Type:** Must be one of: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, `chore`.
* **Scope:** Required. Use a short module/area name, e.g.:
    `core`, `cli`, `data`, `model`, `training`, `chat`, `benchmarks`, `analysis`, `web`, `docs`, `tests`, `deps`, `build`, `ci`.
* **Subject:** Imperative mood, concise, no trailing period. Prefer lowercase (unless a proper noun).
* **Length:** Keep the subject line <= 72 characters when practical.
* **Breaking changes:** Use `!` after type/scope (e.g. `feat(cli)!: ...`) and explain in the body.
* **Body:** Optional, but recommended when the change is non-trivial. Use bullet points.
* **No “WIP” commits** in proposals.

**Examples:**
* `fix(cli): register commands after registry init`
* `chore(tests): align sys.path bootstrap for repo root + src`
* `docs(implementation): update sprint 2 exit criteria`
* `refactor(data): simplify validator imports`

## 3. Workflow & Execution
*   **Propose Next Steps:** Always propose logical next steps after completing a task or chat activity.
*   **Long-Running Tasks:** For tasks expected to take longer than 15 minutes (e.g., model training):
    *   Inform the user about the estimated duration.
    *   Ask for explicit permission to proceed.
    *   Offer the choice to run it within the chat session or as a background process.

## 4. Instruction Maintenance
*   **Update Instructions:** Any new suggestion or rule regarding how the agent should execute commands or tasks that needs to be remembered MUST be added to `.github/copilot-instructions.md`.

## 5. Code Quality Standards

### 5.1 Code Style & Formatting
*   **Line Length:** Maximum 100 characters.
*   **Formatter:** Use `ruff format` for automatic formatting.
*   **Import Order:** Standard library → third-party → local (separated by blank lines).
*   **Trailing Commas:** Use trailing commas in multi-line structures.

### 5.2 File Size & Structure
*   **File Size Limit:** Prefer ~300 lines per file, maximum 500 lines.
*   **Large Modules:** Split into submodules with `__init__.py` re-exports.
*   **Class Files:** One main class per file for complex classes.
*   **Function Grouping:** Group related functions by responsibility.

### 5.3 Type Hints & Annotations
*   **Future Annotations:** Always use `from __future__ import annotations`.
*   **Modern Syntax:** Use PEP 604 style: `X | None`, `list[str]`, `dict[str, int]` (not `Optional`, `List`, `Dict`).
*   **Return Types:** Required for all public functions and methods.
*   **Avoid `Any`:** Use specific types; `Any` only as last resort.

### 5.4 Documentation Standards
*   **Module Docstrings:** Required for all modules (one-liner describing purpose).
*   **Function/Class Docstrings:** Required for public functions and classes.
*   **Format:** Google-style docstrings with `Args:`, `Returns:`, `Raises:` sections.
*   **Template:**
    ```python
    def function_name(param: str) -> bool:
        """Short description of function.

        Args:
            param: Description of the parameter.

        Returns:
            Description of return value.

        Raises:
            ValueError: When param is invalid.
        """
    ```

### 5.5 Error Handling & Logging
*   **Custom Exceptions:** Use exceptions from `core.exceptions`.
*   **Logger Pattern:** Always use `logger = get_logger(__name__)`.
*   **Log Levels:** DEBUG (internals), INFO (operations), WARNING (issues), ERROR (failures).
*   **Log Before Raise:** Always log errors before raising exceptions.

### 5.6 Testing Conventions
*   **Markers:** Use `@pytest.mark.slow`, `@pytest.mark.cuda`, `@pytest.mark.integration`.
*   **Naming:** `test_<function>_<scenario>_<expected>` (e.g., `test_load_model_invalid_path_raises_error`).
*   **Fixtures:** Place shared fixtures in `conftest.py`.
*   **Coverage:** Aim for >80% coverage on new code.

### 5.7 UI/UX Standards
*   **Background Loading:** Whenever data is being loaded or calculated in the background, provide clear visual feedback in the GUI (e.g., spinners, loading skeletons, or "Loading..." text).
*   **Immediate Feedback:** Ensure the UI remains responsive during background tasks. Show placeholders for values that are not yet available.

