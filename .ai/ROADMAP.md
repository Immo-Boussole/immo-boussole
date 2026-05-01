---
description: Future feature roadmap and technical optimizations
---

# Project Roadmap: Immo-Boussole

The future of Immo-Boussole is to evolve from a simple aggregator to an **Intelligent Property Advisor**.

## 🚀 Future Features

### 1. 📈 Price Trend Analysis (Short Term)
- **Goal**: Visualize the price-per-square-meter trend of similar listings over time.
- **DNA Alignment**: Data-rich interactions + functional dashboard.
- **Implementation**: High-quality charts (using Chart.js or Plotly) using the Deep-Dark design system colors (`var(--accent)`).

### 2. 📄 "Investor Canvas" PDF Report (Short Term)
- **Goal**: Generate a professional PDF one-pager for a specific listing, including all custom reviews and photos.
- **DNA Alignment**: Premium feel + Collaborative intelligence.
- **Use Case**: Sending a "Boussole-verified" opportunity to a bank or partner.

### 3. 👔 Real Estate Agent Role (Medium Term)
- **Goal**: Add a third role (`agent`) that can view imported listings, user reviews, and the Ideal Property Profile.
- **Restriction**: Cannot import or delete listings; read-only access.

### 4. ⭐ Favorites System (Short Term)
- **Goal**: Allow users to star/bookmark both listings and ready searches.

### 5. 🌐 New Scrapers: Century21, Orpi, PAP (Medium Term)
- **Goal**: Expand source coverage with major French real estate networks currently missing from the aggregator.
- **Priority targets**: `Century21.fr`, `Orpi.com`, `PAP.fr` (particulier à particulier — no agent fee).
- **Approach**: Use DevTools Network tab to identify REST/JSON APIs for each site; fall back to Playwright for JS-heavy pages.
- **Impact**: ~30–40% more listings coverage versus current 9-source baseline.
- **Effort**: High — each scraper requires independent reverse engineering, anti-bot bypass evaluation, and field mapping.

### 6. 🤖 AI Listing Summary (Medium Term)
- **Goal**: Auto-generate a concise bullet-point summary of each listing's description to save reading time.
- **Approach**: Call a local LLM via Ollama (e.g. `llama3`) or the OpenAI API. Add `ai_summary = Column(Text, nullable=True)` to `Listing`.
- **Secondary benefit**: Use the LLM to extract missing structured fields (DPE, surface terrain, etc.) directly from the raw description when the scraper did not capture them.
- **Config**: `OLLAMA_URL` / `OPENAI_API_KEY` env vars; disabled if neither is set.
- **UI**: Display the AI summary as a collapsible section on the listing detail page, styled with `var(--surface-2)` background and a `🤖` icon.

### 7. 🩺 Scraper Error Monitoring (Short Term)
- **Goal**: Surface scraping failures to admins instead of only printing to console logs.
- **Approach**:
  - Add a `ScrapingLog` DB model (`source`, `query_name`, `status`, `error_msg`, `listings_found`, `duration_s`, `ran_at`).
  - Wrap `scrape_and_diff()` in a try/except that writes a log entry on success **and** failure.
  - Add an admin-only page `/admin/scraping-logs` listing the last N runs per source, with color-coded status badges.
  - Optional: Send an Apprise alert if a source fails 3 consecutive times.
- **Impact**: Immediate visibility into broken scrapers without SSH log access.

### 8. 📄 Multi-page Pagination in Scrapers (Medium Term)
- **Goal**: Retrieve all pages of results from a source, not just the first page.
- **Approach**: Add a `max_pages: int = 1` parameter to `BaseScraper.get_listings()`. Each scraper subclass implements a `_next_page_url()` helper that extracts the "next page" link or increments an offset parameter.
- **Priority**: Apply first to `LeBonCoin`, `BienIci`, and `SeLoger` which regularly have 5–20 result pages.
- **Guard**: Respect a configurable `SCRAPER_MAX_PAGES` env variable (default: `3`) to avoid runaway loops.

### 9. 🎯 Matching Score Visible Everywhere (Short Term)
- **Goal**: Show how well each listing matches the user's Ideal Profile directly on the map markers and in the listings table — not only on the detail page.
- **Approach**:
  - Compute a `match_score` (0–100%) server-side in a shared `compute_match_score(listing, ideal_profile)` function in `services.py`.
  - Store the score in a non-persisted property or compute it at render time and inject it into the template context.
  - **Map**: Color-code Leaflet markers (green = high match, orange = medium, red = low).
  - **Table**: Add a sortable "Match" column with a colored percentage badge.
  - **Dashboard**: Add a "Best matches today" mini-widget on `index.html`.

---

## 🛠️ Technical Optimizations

### 1. 📂 Media Asset Management
- Implement automatic image optimization/resizing for downloaded photos to save disk space in the `media-data` volume.
- Shift to WebP format for improved dashboard loading speeds.

### 2. 🛡️ Scraper Reliability (V2)
- Implement a more robust "Retry-with-Proxy" logic for the most difficult listing sources.
- Add "Listing Lifecycle" tracking (detecting when a listing is removed and calculating its "time on market").

### 3. 🧪 Design Polish (Ongoing)
- Implement subtle micro-interactions on the `.card` hover state using `Lottie` or custom SVG animations for "Boussole" (Compass) themes.
- Expand the `mobile.css` to support tablet-specific multi-column layouts.

---

## ✅ Completed Milestones

### 🔔 Apprise Push Notifications (May 2026)
- **Per-user Apprise URL**: Each user can configure their own `apprise_url` in Mon Profil (Telegram, Discord, ntfy, Pushover, email, etc.).
- **Global fallback**: `APPRISE_URL` env variable acts as a system-wide notification channel if no per-user URL is set.
- **Trigger**: After each `scrape_and_diff()` run, all genuinely new (non-duplicate) listings are bundled and sent as a single grouped notification per user.
- **Test endpoint**: `POST /api/notifications/test` allows users to validate their URL from the profile page without waiting for a scrape cycle.
- **DB Migration v9**: `ALTER TABLE users ADD COLUMN apprise_url TEXT`.

### 🗺️ Navigation Harmonization (April 2026)
- **Universal Sidebar**: Replaced hybrid navigation with a persistent sidebar across all views.
- **Scrolling Fixes**: Implemented 100vh locked-body layouts with internal scrolling.
- **I18N Access**: Centralized language switching in the sidebar footer.

### 🤖 Automatic Scheduled Searches (April 2026)
- **Hourly CronTrigger**: Replaced `IntervalTrigger` with `CronTrigger(hour='6-22', minute='0')` + a 22:30 job, ensuring scraping runs 18 times per day in the 6h–22h30 window.
- **ReadySearch → Listing traceability**: New listings produced by the scheduler now store `source_ready_search_id` and `source_criteria`, enabling the "Automatic Searches" view to display the originating platform and search criteria as the first two columns (mirroring the "Ready to Search" column structure).
- **Force Search**: `POST /api/searches/force` endpoint triggers `scraping_job()` instantly via FastAPI `BackgroundTasks`, with UI feedback (spinner + toast + auto-reload).
- **Configurable Schedule Label**: `SCRAPING_SCHEDULE` env variable provides a human-readable description of the cron schedule, displayed in the "Automatic Searches" topbar.
- **DB Migration v8**: Automatic `ALTER TABLE` adds `source_ready_search_id` and `source_criteria` columns on startup.
