# Response Formatting & Step Progress Tracking Guidelines

This document outlines the mandatory formatting rules for AI agent responses, step progress tracking, and technology/action emoji usage across the Immo-Boussole project.

---

## 1. Step Title Structure & Numbering

Every response or multi-step execution turn must clearly indicate progress and current execution context using standardized Level 3 Markdown headings:

```markdown
### [X/Y] <EMOJI> <Descriptive Step Title>
```
*Where `X` is the current step index (integer) and `Y` is the total number of steps (integer).*

> [!IMPORTANT]
> **Single Bracket Pair Only**: Use single outer square brackets surrounding the fraction `[X/Y]` (e.g. `[1/5]`, `[2/2]`). Never use nested or double brackets such as `[[1]/[5]]` or `[[2]/[2]]`.

### Examples:
- `### [1/5] 🔍 Codebase Analysis & Investigation`
- `### [2/5] 🐍 Python Backend Implementation`
- `### [3/5] 🧪 Local Non-Regression Tests`
- `### [4/5] 🐙 Git Commit & Push`
- `### [5/5] ⚙️ GitHub Actions Workflow Verification`

---

## 2. Standard Emoji / Logo Taxonomy

AI agents must use standard Unicode emojis corresponding to the technology or action being performed:

| Domain / Technology / Action | Emoji | Usage & Context |
| :--- | :---: | :--- |
| **Python Backend** | 🐍 | Core backend Python code, FastAPI endpoints, scripts, scraping logic |
| **Tests & Quality** | 🧪 | Unit tests, pytest runs, test fixes, regression checks |
| **Docker & Containers** | 🐳 | Dockerfiles, compose files, container management, orchestrator runtime |
| **GitHub / Git** | 🐙 | Git commits, branch operations, pull requests, issue tracking |
| **GitHub Actions / CI-CD** | ⚙️ | Workflow runs, CI builds, artifact publishing, status monitoring |
| **Browser Extension** | 🧩 | Manifest V3, WebExtension polyfill, content scripts, popup UI |
| **Frontend / Web / CSS** | 🌐 | HTML, CSS/responsive layout, browser DOM, DevTools validation |
| **Investigation / Research** | 🔍 | Codebase exploration, diagnosis, root-cause analysis, search |
| **Documentation & i18n** | 📝 | README, Wiki, guides, EN/FR translations, changelogs |
| **Deployment & Releases** | 🚀 | Dev/Prod environment auto-update commands, tag releases |
| **Security & Authentication** | 🛡️ | Auth flows, tokens, secret protection, credential masking |
| **Immo-Boussole Business Logic** | 🧭 | Real estate algorithms, search queries, visit management, scoring |

---

## 3. General Response Rules

1. **Clear Progression**: Whenever a task involves multiple stages, define the total number of steps and maintain consistent numbering across updates.
2. **Visual Clues**: Place the designated emoji immediately after the step fraction (`[X/Y] 🐍 ...`) to provide instant visual context.
3. **Concise Status Summary**: Keep the description under each heading informative and direct.
