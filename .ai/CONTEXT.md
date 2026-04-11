---
description: Project context, mission, and guiding principles
---

# Project Context: Immo-Boussole

## Mission Statement
**Immo-Boussole** (Real Estate Compass) is designed to be the ultimate navigator in the often-turbulent sea of real estate listings. Our mission is to provide users with an **objective, data-driven, and collaborative tool** to evaluate property opportunities with surgical precision. 

Like a true compass, the application doesn't tell you *where* to go, but provides the reliable coordinates and orientation needed to make an informed decision.

## Core Values (The "Boussole" DNA)
1. **Objectivity Above All**: We prioritize raw data and verified facts over marketing fluff found in listings.
2. **Collaborative Intelligence**: Real estate decisions are rarely made alone. The platform facilitates shared analysis and reviews.
3. **Visual Clarity**: Using our "Deep-Dark" design system, we transform overwhelming data tables into a premium, focused experience.
4. **Efficiency via Automation**: We leverage advanced scraping and scheduling to ensure the user's "compass" is always synchronized with the latest market reality.

## Development Constraints (Non-Negotiable)
- **Privacy First**: All data is stored locally in a Dockerized SQLite database. No external cloud tracking.
- **Design Integrity**: Every new component MUST adhere to the [DESIGN.md](./DESIGN.md) specification. The application follows a **Universal Sidebar Navigation** pattern for consistency across all views.
- **Internationalization**: The app must maintain 100% parity between French and English supporting the `locales/` JSON structure. Persistent language switching must be available in the sidebar footer.
- **Resilience**: Scraping logic must handle dynamic content and anti-bot measures gracefully (using Browserless and Playwright).

## User Flow Philosophy
1. **Discover**: Aggregate listings from multiple sources into a unified view.
2. **Analyze**: Enrich raw data with custom reviews, ratings, and statuses.
3. **Orient**: Use filters and "Boussole Logic" to identify the best value-for-money opportunities.
4. **Decide**: Transition from data-gathering to action with confidence.
