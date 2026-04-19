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

### 3. 🔔 Intelligent "Compass Alerts" (Medium Term)
- **Goal**: Use a webhook or email system to notify the user when a new listing matches "Gold Star" criteria (price/area ratio > X).
- **DNA Alignment**: Efficiency via automation.
- **Personalization**: Unique user-defined weighting of criteria.

### 4. 👔 Real Estate Agent Role (Medium Term)
- **Goal**: Add a third role (`agent`) that can view imported listings, user reviews, and the Ideal Property Profile.
- **Restriction**: Cannot import or delete listings; read-only access.

### 5. ⭐ Favorites System (Short Term)
- **Goal**: Allow users to star/bookmark both listings and ready searches.

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
