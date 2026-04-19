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

## 007: Scheduled Scraping Strategy — CronTrigger
**Status**: Accepted  
**Decision**: Replace `IntervalTrigger` with **`CronTrigger`** (APScheduler) for two jobs: `hour='6-22', minute='0'` and `hour='22', minute='30'`.  
**Context**: The original `IntervalTrigger(hours=N)` ran from startup time, meaning the schedule drifted and could fire during nighttime if the app was restarted late at night. Users wanted reliable hourly scraping only during active hours (6h–22h30).  
**Justification**:
- `CronTrigger` fires at fixed wall-clock times regardless of when the app started.
- Two jobs (hourly 6h–22h + one at 22h30) cover the full desired window with 18 daily executions.
- The schedule description is exposed as `SCRAPING_SCHEDULE` in `.env`, decoupling the human-readable label from the actual cron expression — allowing the label to be changed without touching Python code.

## 008: ReadySearch → Listing Traceability
**Status**: Accepted  
**Decision**: Add `source_ready_search_id` (FK) and `source_criteria` (String) columns to the `Listing` model.  
**Context**: The "Automatic Searches" view needed to display the originating platform and criteria (matching the "Ready to Search" column structure) for each auto-discovered listing.  
**Justification**:
- A FK to `ready_searches` provides a live join if the ReadySearch still exists.
- A denormalized `source_criteria` column is kept as a copy for persistence — if a ReadySearch is deleted, the listing retains its original criteria label.
- Migration is handled automatically by the existing `run_migrations()` function on startup (v8 migration).
- Fallback: listings without a `source_ready_search_id` (e.g., created before this feature) display the `source` enum value and a dash, ensuring backward compatibility.
