---
description: Future feature roadmap and technical optimizations
---

# Project Roadmap: Immo-Boussole

The future of Immo-Boussole is to evolve from a simple aggregator to an **Intelligent Property Advisor**.

## 🚀 Future Features (3-5 items)

### 1. 📈 Price Trend Analysis (Short Term)
- **Goal**: Visualize the price-per-square-meter trend of similar listings over time.
- **DNA Alignment**: Data-rich interactions + functional dashboard.
- **Implementation**: High-quality charts (using Chart.js or Plotly) using the Deep-Dark design system colors (`var(--accent)`).

### 2. 🗺️ Map-Centric Decision Layer (Medium Term)
- **Goal**: Integrate a Leaflet or MapLibre view to visualize listings geographically with heatmap overlays (e.g., proximity to public transit).
- **DNA Alignment**: Focused user flow + "Orienting" the user.
- **Colors**: Deep dark map tiles (e.g., Stadia Alidade Smooth Dark) to match the `#0b0f1a` background.

### 3. 📄 "Investor Canvas" PDF Report (Short Term)
- **Goal**: Generate a professional PDF one-pager for a specific listing, including all custom reviews and photos.
- **DNA Alignment**: Premium feel + Collaborative intelligence.
- **Use Case**: Sending a "Boussole-verified" opportunity to a bank or partner.

### 4. 🔔 Intelligent "Compass Alerts" (Medium Term)
- **Goal**: Use a webhook or email system to notify the user when a new listing matches "Gold Star" criteria (price/area ratio > X).
- **DNA Alignment**: Efficiency via automation.
- **Personalization**: Unique user-defined weighting of criteria.

---

## 🛠️ Technical Optimizations

### 1. 📂 Media Asset Management
- Implement automatic image optimization/resizing for downloaded photos to save disk space in the `media-data` volume.
- Shift to WebP format for improved dashboard loading speeds.

### 2. 🛡️ Scraper Reliability (V2)
- Implement a more robust "Retry-with-Proxy" logic for the most difficult listing sources.
- Add "Listing Lifecycle" tracking (detecting when a listing is removed and calculating its "time on market").

### 🧪 Design Polish (Ongoing)
- Implement subtle micro-interactions on the `.card` hover state using `Lottie` or custom SVG animations for "Boussole" (Compass) themes.
- Expand the `mobile.css` to support tablet-specific multi-column layouts.
