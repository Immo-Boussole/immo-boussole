---
description: Project rule to enforce automated QA, regression checks, security audits, and responsive validation using Chrome DevTools MCP
---

# Chrome DevTools MCP Quality Assurance, Security & Responsive Testing

This rule defines the mandatory validation protocol using the Chrome DevTools MCP for any modification to the user interface (UI), templates, CSS styles, JavaScript files, or frontend routes.

---

## 1. Triggers and Prerequisites

- **Triggers**: Any modification impacting visual rendering, frontend interactivity, accessibility, or client-side security.
- **Local Server**:
  - Check that the local development server is running (e.g. `http://localhost:5000` or configured port).
  - If the server is not running, start it in the background (`run_command` with `IsDaemon: true`).

---

## 2. Multi-Device Validation Protocol (Responsive Design)

In compliance with [responsive_design.md](file:///c:/tools/GitHub/Immo-Boussole/immo-boussole/.agents/rules/responsive_design.md):

1. **Test across a minimum of 3 viewports** using `resize_page` or `emulate`:
   - **Mobile**: $375 \times 667$ px or $390 \times 844$ px (verify hamburger / drawer menus, no horizontal overflow, touch targets $\ge 44$ px).
   - **Tablet**: $768 \times 1024$ px (verify grid/flexbox layouts and portrait/landscape adaptation).
   - **Desktop**: $1280 \times 800$ px and/or $1920 \times 1080$ px (verify wide layouts and legibility).
2. **Visual Screenshots**:
   - Use `take_screenshot` across critical views to validate visual rendering.

---

## 3. Regression Detection (Zero Error Policy)

1. **JavaScript Console**:
   - Call `list_console_messages` after navigating and interacting with modified components.
   - **Requirement**: Zero unhandled JavaScript errors (`console.error`, uncaught exceptions).
2. **Network & API Requests**:
   - Call `list_network_requests`.
   - **Requirement**: Zero unexpected HTTP error codes ($4\text{xx} / 5\text{xx}$), no missing static assets (CSS, JS, images, fonts).

---

## 4. Security & Integrity Checks

1. **Console Security & Headers**:
   - Verify the absence of security warnings and Content Security Policy (CSP) violations.
2. **Data & Secret Leaks**:
   - Ensure no sensitive information (API keys, raw passwords, auth tokens) is exposed in the console or accessible DOM attributes.
3. **XSS & Injection Prevention**:
   - Verify that user inputs displayed in the interface are consistently sanitized and escaped.

---

## 5. Quality & Accessibility Audits (Lighthouse)

- Run `lighthouse_audit` on major modified pages.
- Verify Accessibility indicators (color contrast, `aria` tags, semantic HTML) and Best Practices.

---

## 6. Corrective Actions & Reporting

- **Strict Blocking on Anomalies**: Any detected issue (console error, responsive glitch, network failure, or security risk) must be resolved immediately before completing the task.
- **Test Summary**: Summarize all verification steps and findings in the walkthrough or final task response.
