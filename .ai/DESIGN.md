---
description: Immo-Boussole Design System and Guidelines
---

# Immo-Boussole

Immo-Boussole's design features a modern, deep-dark dashboard aesthetic designed for data-rich interactions. It prioritizes clarity and focus by using a very dark blue background (`#0b0f1a`) combined with varied surface elevations (`#131929`, `#1a2236`) rather than pure black or flat colors. Bright, saturated accents (`#4f8ef7`, `#10d9a4`, `#f25c69`) are used purposefully to highlight interactive elements and status indicators against the dark canvas, yielding a high-contrast, premium, but functional feel.

The typography relies on **Inter**, a highly legible geometric sans-serif that scales impeccably from compact data tables to strong headings. The interface employs soft, plush border radii (`14px` for prominent cards) and subtle, smooth hover transitions controlled by a custom cubic-bezier curve (`cubic-bezier(0.4, 0, 0.2, 1)`) to provide a fluid, satisfying user experience.

### Primary Colors
- **Background** (`var(--bg)`, `#0b0f1a`): The foundational deep night-blue canvas.
- **Surface Level 1** (`var(--surface)`, `#131929`): Main cards, layout containers, and sidebars. Provides mild elevation above the background.
- **Surface Level 2** (`var(--surface-2)`, `#1a2236`): Interactive inner cards, form inputs, and slight highlights.
- **Text Primary** (`var(--text)`, `#eef2ff`): High-contrast off-white for headings, values, and primary body content. 
- **Text Secondary** (`var(--text-2)`, `#8b9cc8`): Muted blue-gray for labels, metadata, captions, and secondary info.

### Accent & Semantic Colors
- **Accent Primary** (`var(--accent)`, `#4f8ef7`): Primary action buttons, active navigational states, and vital links.
- **Accent Secondary** (`var(--accent-2)`, `#6366f1`): Indigo used in gradients (e.g., logo text) to pair with the primary accent.
- **Success / New** (`var(--green)`, `#10d9a4`): Vibrant teal-green for positive trends or indicating "new" listings.
- **Danger / Removed** (`var(--red)`, `#f25c69`): Soft but clear red for deleted, unavailable, or error states.
- **Warning / Duplicate** (`var(--orange)`, `#f8a84b`): Orange for warnings or duplicates.
- **Highlight** (`var(--yellow)`, `#f9d04f`): Yellow specifically for star ratings and review highlights.

### Borders
- **Standard Border** (`var(--border)`, `rgba(255, 255, 255, 0.07)`): A very subtle, barely-there translucent white line used globally to delineate surfaces without adding harsh visual noise.

### Font Family
- **Primary**: `Inter`, with fallback `sans-serif`.
- **Weights**: `300` (Light), `400` (Regular), `500` (Medium), `600` (Semi-bold), `700` (Bold), `800` (Extra-bold).

### Hierarchy & Sizing (Base 16px root)
| Role | Size | Weight | Properties | Use |
|------|------|--------|------------|-----|
| **Brand/Logo** | `1.3rem` | `800` | Gradient text (`135deg`, accent to accent-2) | Header logo |
| **Page Titles** | `1.25rem` | `700` | Default spacing | Topbar headers |
| **Stats Values** | `1.8rem` | `800` | Default spacing | High-priority dashboard metrics |
| **Card Titles** | `0.95rem` | `700` | Line-height `1.4`, clamped to 2 lines | Listing names, box headers |
| **Buttons** | `0.8rem` | `600` | Flex aligned | Button labels |
| **Category Labels** | `0.65rem` - `0.7rem`| `700`-`800` | Uppercase, `0.05em` to `0.08em` letter-spacing | Badges, small sub-headers |

### Buttons (`.btn`)
- **Primary** (`.btn.primary`): 
  - Background: `var(--accent)`
  - Border: `var(--accent)` 
  - Text: `#fff`
  - Hover: Shifts to `var(--accent-2)` background and border.
- **Secondary/Standard** (`.btn`): 
  - Background: `var(--surface-2)`
  - Border: `var(--border)`
  - Text: `var(--text)`
  - Hover: Adopts Primary styles (`var(--accent)` background).
- **Destructive outline** (`.btn-delete`): 
  - Background: transparent
  - Border: `rgba(242, 92, 105, 0.25)`
  - Text: `rgba(242, 92, 105, 0.55)`
  - Hover: Fills with `rgba(242, 92, 105, 0.15)`, text transitions to `var(--red)`, scales `1.1`.

### Cards & Listings (`.card`)
- **Container**: Background `var(--surface)`, border `var(--border)`, radius `var(--radius)` (14px).
- **Hover State**: Elevates upwards `transform: translateY(-4px)`, border glows `rgba(79, 142, 247, 0.4)`, shadow intensifies `var(--shadow), 0 0 0 1px rgba(79, 142, 247, 0.15)`.

### Badges / Pills (`.badge`)
- **Container**: Distinct `6px` radius. Padding usually `0.2rem 0.6rem`.
- **Typography**: `0.65rem` size, `800` weight, uppercase with `0.05em` letter-spacing.
- **Colors**: Typically pure black or white text sitting confidently on a semantic background color (`var(--green)`, `var(--red)`).

- **Global Layout System**: Full height CSS grid/flex hybrid (`100vh` layouts, locked scroll body). The application utilizes a **Universal Sidebar Navigation** pattern where every page consists of a fixed Sidebar (`aside.sidebar`) and a scrollable Main Content area (`main.main`). The body is set to `overflow: hidden` to enable independent scrolling for both the sidebar and the content area.
- **Spacing Scale**: Usually proportional by `rem` (`0.25rem`, `0.5rem`, `0.75rem`, `1rem`, `1.25rem`, `1.5rem`).
- **Gaps**: Grid layouts employ `1.25rem` gaps between display cards. Flex clusters use tighter `0.5rem` to `1rem` spacing.
- **CSS Custom Properties**: Hardcoded colors shouldn't exist in markup. Everything references standard custom props from `:root` (e.g. `var(--surface)`).
- **Transitions (`var(--trans)`)**: Interactive elements uniformly utilize `all 0.25s cubic-bezier(0.4, 0, 0.2, 1)` to coordinate an elegant snap-and-settle feeling.

- **Primary Shadow** (`var(--shadow)`): `0 8px 32px rgba(0, 0, 0, 0.5)`. Employed for hovered elements or overlaid floating surfaces.
- **Modals**: Utilize a backdrop with a `4px` blur and `rgba(0, 0, 0, 0.7)` tint. The modal itself surfaces at the `var(--surface)` level, receiving `var(--shadow)` and animating up softly (`translateY(20px)` to `0`).

- **Do** consistently apply the `var(--border)` for all generic internal dividers and strokes.
- **Do** assign `var(--trans)` to anything with a `:hover` or state change.
- **Do** use `var(--text-2)` for structural descriptive text so it doesn't shout at the user.
- **Don't** declare arbitrary hex codes in stylesheets. Stick to the defined palette.
- **Don't** use pure solid blacks (`#000000`) or whites (`#FFFFFF`) for large backdrop areas.
- **Don't** overuse `var(--accent)` — reserve it specifically for leading the user's eye to primary actions.

- A dedicated `mobile.css` manages fluid responsive collapsing.
- **Critical Breakpoint**: At screen widths `<= 768px`.
- **Behavior Changes**: 
  - Standard flex layouts shift to `flex-direction: column`.
  - Multi-column grids (like the `.stat-grid` and `.grid`) collapse uniformly into single `1fr` columns.
  - Sidebars transition into animated off-canvas drawers (`left: -280px` hiding) with a backdrop overlay.
  - Generous internal container padding drops universally to `1rem`. The `body` remains locked at `100vh` to allow internal scrolling.
  - Topbars (`.topbar`) employ `flex-wrap: wrap` and their sub-sections expand to `width: 100%` where necessary.
  - Full-screen modals like the photo gallery stack vertically.

- *"Implement a new dashboard metric card featuring a dark background (`var(--surface-2)`), unified border (`var(--border)`), and a 12px radius. Feature a large stat value at 1.8rem bold."*
- *"Create a standard interactive table row layout. Background rests at `var(--surface)`. On hover, the row should shift to `rgba(79, 142, 247, 0.12)`."*
- *"Design a filter chips cluster. Ensure gaps are set to `0.5rem`, chips have `var(--border)`, radius of `9px`, texts use `var(--text-2)` but toggle to `var(--accent)` on active."*
