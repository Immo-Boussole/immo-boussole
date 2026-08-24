# GitHub Workflow & Pull Request Verification Rule

This rule defines mandatory requirements for monitoring, diagnosing, and verifying all GitHub Actions workflows engaged by Git pushes, pull requests, and automated branch operations.

---

## 1. Mandatory Workflow Verification on Pushes and Pull Requests

Whenever any code, configuration, or documentation change is pushed to a remote repository or associated with a pull request:

- **Proactive Monitoring**:
  - The AI agent must never mark a task complete immediately after `git push`.
  - The agent must inspect the status of triggered GitHub Actions workflows using `gh run list` / `gh run view` / `gh pr checks`.
  - Monitor workflows until all jobs reach a completed terminal state (`success`, `failure`, `cancelled`).

- **Zero Tolerance for Workflow Failures**:
  - If any workflow job fails (e.g. `CI`, `Docker Build`, `Docker Compose Quality Check`, `I18n Sync Check`, `Publishing`), the task is considered **incomplete**.
  - The agent must immediately inspect failure logs (`gh run view <run-id> --log-failed`), identify the root cause, apply appropriate code/configuration fixes, commit and push the resolution.
  - Re-verify until all triggered workflow runs are 100% green (`success`).

---

## 2. Standard Verification Flow

```text
[Code / Config Changes]
         │
         ▼
[Run Local Tests (pytest / npm test)]
         │
         ▼
[Git Commit & Git Push / PR Creation]
         │
         ▼
[Monitor GitHub Actions via GitHub CLI]
  - gh run list --limit 5
  - gh run view <run-id> / gh pr checks
         │
    ┌────┴────────────────────────┐
    ▼                             ▼
[All Workflows Succeeded]   [Any Job Failed]
    │                             │
    │                             ▼
    │                       [Inspect Failure Logs]
    │                         gh run view <run-id> --log-failed
    │                             │
    │                             ▼
    │                       [Apply Fix & Push]
    │                             │
    │                       [Re-verify Workflows]
    │                             │
    └─────────────────────────────┘
         │
         ▼
[Task Complete / Ready for User Review]
```

---

## 3. Pull Request Check Protocol

For any pull request:
- Verify that all status checks and required CI checks pass (`gh pr checks <pr-number>`).
- Ensure no merge conflicts or branch-behind issues occur with `main` / `master`.
- If an automated bot or workflow pushed ref updates (e.g. `DOCKER_IMAGE.txt` or badge updates), run `git pull --rebase` to synchronize local tracking branches.
