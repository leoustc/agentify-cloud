# Agent Instructions

## Required Project Files

- Before planning, coding, or reviewing, read `PROJECT.md`.
- Architect converts the user-facing `PROJECT.md` into an agent-executable implementation plan in `EXECUTION.md`.
- Backend codes from `EXECUTION.md`, not from guesswork. If `EXECUTION.md` is missing or unclear, ask Architect for clarification before coding.
- Review checks the code against both `PROJECT.md` and `EXECUTION.md`.

## Agent Workflow

1. **Architect planning**
   - Read `PROJECT.md`.
   - Create or update `EXECUTION.md` with concrete implementation tasks, files/modules, API behavior, validation, and test expectations.
   - Send a mailbox message to Backend with the coding task and relevant project context.

2. **Backend implementation**
   - Read `PROJECT.md`, `EXECUTION.md`, and this `AGENTS.md`.
   - Implement the requested code changes.
   - Run relevant verification.
   - When coding is finished, send a summary to Review including files changed, verification results, and known risks.

3. **Review validation**
   - Read `PROJECT.md`, `EXECUTION.md`, and the Backend summary.
   - Review code changes only; do not modify code by default.
   - Run a basic feasible test/verification pass, such as existing tests, compile/syntax checks, or the project-provided test command.
   - Send findings, review summary, and a test report back to Architect.

4. **Architect decision**
   - Decide whether fixes are needed.
   - If application/code fixes are needed, route a focused follow-up task to Backend.
   - If release, packaging, publish, registry, build artifact, or release toolchain issues are found, route them to Release.
   - If no fixes are needed, report completion to Manager/user.

5. **Release handling**
   - Release owns PyPI/npm publishing, package build issues, release metadata/manifests, registry authentication/config, release toolchain fixes, and release git commit/push work.
   - Release may fix build/release configuration needed for packaging or publishing.
   - Release may set or verify git remotes, commit release-ready changes, and push with SSH when explicitly authorized.
   - Release must inspect `git status` before committing and avoid secrets, virtualenvs, caches, `node_modules`, and generated artifacts that should remain ignored.
   - Release must verify package/build commands before publishing or pushing release changes and must not expose secrets.
   - Release publishes, commits, or pushes only when explicitly authorized by the user or Manager for that run.

## Boundaries

- Keep code changes focused on the requested task.
- Reviews report findings only unless explicitly asked to modify code.
- Preserve `workdir`, `project_key`, and the project object in mailbox handoffs when available.
