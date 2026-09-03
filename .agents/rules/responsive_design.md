---
description: Project rule to ensure all code and UI changes work seamlessly across desktop, tablet, and mobile screens
---

# Responsive Design & Multi-Device Compatibility

For every code or user interface (UI/UX) modification on this project:

- **Multi-Resolution & Multi-Device Support**: Systematically ensure changes are fully responsive and function optimally across:
  - **PC / Desktop** (standard and widescreen displays)
  - **Tablets** (portrait and landscape orientations)
  - **Smartphones / Mobile Devices** (small screens, appropriate touch targets, smooth scrolling, no undesirable horizontal overflow)
- **Topbar Architecture & Action Buttons Layout**:
  - Always keep the page title (`<h1>`) on the far left inside `.topbar-left`.
  - Place all action buttons (e.g. "+ Add Listing", "Refresh", modals, triggers) exclusively inside `<div class="topbar-right">` aligned to the far right. Never place action buttons immediately next to `<h1>` in `.topbar-left`.
  - When a search bar is included in the topbar (`.topbar-search`), place it immediately after `<h1>` inside `.topbar-left` (or between left and right containers) with `flex: 1` so it expands dynamically to occupy all available horizontal space up to `.topbar-right`.
  - On mobile (`<= 768px`), topbar layout collapses cleanly, title and search scale gracefully, and action buttons in `.topbar-right` remain easily accessible (touch target $\ge 44\text{px}$).
- **Listing Filters & Multi-Selection**:
  - Status filter chips (`Nouvelle`, `Active`, `Disparue`, `Rejetée`) must support parallel multi-selection with `Nouvelle` + `Active` active by default on initial load across all listing views.
- **Standalone Public / Magic-Link Pages Isolation (e.g. `/v/{token}`)**:
  - Standalone public, shared, or collaborative workspaces (such as the visit workspace `/v/{token}`, public share links, login, etc.) MUST NEVER import the dashboard-specific `mobile.css` stylesheet.
  - `mobile.css` applies fixed viewport constraints (`body { position: fixed !important; overflow: hidden !important; height: 100dvh !important; }`) tailored exclusively for the sidebar+main dashboard layout. Importing it into standalone views breaks vertical scrolling on mobile devices.
  - Standalone views MUST rely on dedicated mobile-first stylesheets with natural vertical body scrolling, sticky tabs/toolbars docked at `top: 0` on mobile viewports (`position: sticky; top: 0; z-index: 95; backdrop-filter: blur(16px);`), touch targets $\ge 44\text{px}$, and responsive collapsible grids.

