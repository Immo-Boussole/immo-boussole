---
description: Architectural Decision Records
---

# Architecture Decision Records (ADR)

This document tracks significant design and architectural choices for Immo-Boussole.

## 001: Backend Framework Choice
**Status**: Accepted
**Decision**: Use **FastAPI** with **Python 3.12**.
**Context**: We needed a high-performance framework to handle both the user-facing web interface and long-running background scraping tasks.
**Justification**: 
- Native `async/await` support is crucial for Playwright and I/O-bound scraping.
- Built-in Pydantic validation provides a robust schema for real estate listing data.
- Faster development and execution compared to traditional frameworks like Django.

## 002: Data Persistence Strategy
**Status**: Accepted
**Decision**: Use **SQLite** via **SQLAlchemy**.
**Context**: Immo-Boussole is primarily a personal or small-group tool (collaborative).
**Justification**: 
- **Zero-Configuration**: No separate database container (like Postgres) is strictly required for the core mission.
- **Portability**: The entire database is a single file (`immo_boussole.db`), making backups and migrations extremely simple.
- **Performance**: More than sufficient for the expected data volume (thousands of listings).

## 003: Headless Scraper Execution Environment
**Status**: Accepted
**Decision**: Use **Playwright** via a standalone **Browserless** container.
**Context**: Modern real estate websites use aggressive anti-bot protection and dynamic JavaScript rendering.
**Justification**: 
- **Separation of Concerns**: Keeping the browser in its own container prevents memory leaks from affecting the application.
- **Consistency**: Docker ensures the browser environment (fonts, drivers) is identical across development and production.
- **Stealth**: Playwright-stealth plugin combined with Browserless's advanced features significantly increases success rates.

## 004: Frontend & Templating Approach
**Status**: Accepted
**Decision**: Use **Jinja2** with **Vanilla CSS** and **No JavaScript Framework**.
**Context**: The application prioritizes high-quality design without the complexity of a frontend build system (like React/Vue).
**Justification**: 
- Simplifies the Dockerized deployment (no `npm build` in production stage).
- Leverages the "Deep-Dark" design system directly in HTML for maximum predictability and speed.
- Aligns with the "Boussole" DNA of being a lightweight, objective tool.

## 005: Internationalization (I18N)
**Status**: Accepted
**Decision**: Use a **Single-File JSON strategy** per language in `./locales/`.
**Context**: Multi-language support (EN/FR) is mandatory.
**Justification**: 
- Easy to maintain and translate via AI or human experts.
- Simple integration with Jinja2 via a custom filter or context processor.
- Lightweight and avoids the overhead of `.mo`/`.po` binary files.

## 006: Universal Sidebar Navigation
**Status**: Accepted
**Decision**: Adopt a **Universal Sidebar Layout** across all application views.
**Context**: Previously, the application used a mix of Sidebar and Topnav layouts, leading to inconsistent user experiences and scrolling issues.
**Justification**:
- **Consistency**: Provides a unified navigation experience regardless of the current view (Dashboard, Detail, Profile, Admin).
- **Accessibility**: Standardizes the position of the Language Selector and User Session info in a persistent footer.
- **Scroll Management**: Centralizing the sidebar allows for locked body scrolling (`height: 100vh; overflow: hidden`) with internal scrolling for both sidebar and main content, solving previous layout "cutoff" issues.
- **Mobile First**: Standardizes the responsive "off-canvas" drawer behavior for all pages.
