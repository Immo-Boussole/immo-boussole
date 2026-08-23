---
description: Project rule to ensure all code and UI changes work seamlessly across desktop, tablet, and mobile screens
---

# Responsive Design & Multi-Device Compatibility

For every code or user interface (UI/UX) modification on this project:

- **Multi-Resolution & Multi-Device Support**: Systematically ensure changes are fully responsive and function optimally across:
  - **PC / Desktop** (standard and widescreen displays)
  - **Tablets** (portrait and landscape orientations)
  - **Smartphones / Mobile Devices** (small screens, appropriate touch targets, smooth scrolling, no undesirable horizontal overflow)
- **UI / CSS Checks**:
  - Use appropriate media queries (`@media (max-width: ...)` or mobile-first approach).
  - Check text legibility, grid/flexbox layouts, and touch target sizes ($\ge 44\text{px}$).
  - Avoid fixed widths that risk truncating content on mobile viewports.
