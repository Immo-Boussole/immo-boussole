# Testing Framework

Immo-Boussole includes a unified testing framework designed to ensure stability and prevent regressions across the backend, scrapers, and frontend templates.

## Architecture

The framework is built around a central runner that orchestrates multiple types of tests:

- **Smoke Tests**: Quick checks to ensure basic components (like Jinja templates) are functional and syntactically correct.
- **Core Tests**: Verify business logic, API endpoints, and database interactions.
- **Network Tests**: Ensure connectivity and TLS configurations are compatible with target platforms (e.g., LeBonCoin).
- **External API Tests**: Validate integrations with third-party services like OpenStreetMap (Geocoding) and Georisques.
- **Scraper Tests**: High-level integration tests that perform actual scraping to verify parser accuracy.

## Usage

### Local Execution

Use the `run_tests.py` script located in the `tests/` directory:

```bash
# Run the full test suite
python tests/run_tests.py

# Run in CI mode (skips heavy scrapers and external APIs)
python tests/run_tests.py --ci
```

### Continuous Integration (CI)

A GitHub Actions workflow is configured in `.github/workflows/ci.yml`. It automatically runs the **Smoke** and **Core** test groups on every push and pull request to the `main` branch. It can also be triggered **manually** from the GitHub Actions tab.

## Adding New Tests

1. Create a new python file in the `tests/` directory (e.g., `test_feature.py`).
2. Ensure the script returns a non-zero exit code on failure (usually via `assert` or `sys.exit(1)`).
3. Register the script in the `TEST_GROUPS` dictionary inside `tests/run_tests.py`.

## Key Files

- `tests/run_tests.py`: The main orchestration script.
- `.github/workflows/ci.yml`: GitHub Actions configuration.
- `tests/check_template.py`: Utility to verify Jinja2 template syntax.
- `tests/test_jinja.py`: Unit tests for custom Jinja2 logic/filters.
