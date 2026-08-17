# General Guidelines for AI Agents (Immo-Boussole)

This document centralizes all mandatory rules and best practices for any AI agent working on this repository.

---

## 1. Responsive Design & Multi-Device Compatibility

For every code or user interface (UI/UX) modification:

- **Mandatory Multi-Device Support**: Always ensure interfaces render and function optimally across:
  - **PC / Desktop** (standard and widescreen displays)
  - **Tablets** (portrait and landscape orientations)
  - **Smartphones / Mobile Devices** (narrow vertical viewports, touch targets $\ge 44\text{px}$, no undesirable horizontal overflow)
- **CSS & Layout Checks**:
  - Use fluid flexbox/grid layouts and appropriate media queries.
  - Maintain component legibility, accessibility, and responsiveness (modals, banners, forms, tables, lists).

---

## 2. Git Commit Message Format

For every code change:

- Always provide a concise, clear Git commit message in **English** at the end of the response / task summary, adhering to the **Conventional Commits** standard (e.g. `feat(...)`, `fix(...)`, `refactor(...)`, `test(...)`, `docs(...)`).

---

## 3. Code Quality, Performance & Testing

- **Unit and Integration Tests**: Run and validate tests (`pytest`) to prevent regressions.
- **Python 3.10+ & Performance**: Prefer optimized native operations (e.g. `int.bit_count()` and bitwise operations for perceptual hash distance calculations).
- **Documentation Integrity**: Preserve docstrings, comments, and documented architectures located in the `.ai/` directory.

---

## 4. Frontend QA, Security & Responsive Validation via Chrome DevTools MCP

For any change affecting the UI, CSS, JavaScript, templates, or frontend routes:

- **Responsive Multi-Viewport Verification**: Test and capture screenshots across Mobile (e.g. $375\times 667$ px), Tablet (e.g. $768\times 1024$ px), and Desktop (e.g. $1280\times 800$ px) viewports using `resize_page` / `emulate` / `take_screenshot`. Ensure touch targets $\ge 44\text{px}$ and no horizontal overflow.
- **Regression Detection (Zero Error Policy)**: Verify with `list_console_messages` that there are 0 unhandled JS errors, and with `list_network_requests` that there are no unexpected HTTP $4\text{xx}/5\text{xx}$ errors.
- **Security & Integrity**: Inspect console and DOM for CSP violations, security warnings, and sensitive data leakage. Ensure proper XSS sanitization.
- **Quality & Accessibility Audits**: Run `lighthouse_audit` on modified pages to check accessibility, performance, and best practices.
- **Detailed Reference**: See [.agents/rules/chrome_devtools_qa.md](file:///c:/tools/GitHub/Immo-Boussole/immo-boussole/.agents/rules/chrome_devtools_qa.md).
