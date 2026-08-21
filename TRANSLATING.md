# Contributing Translations to Immo-Boussole

We welcome community contributions to translate Immo-Boussole into more languages!

---

## 🌍 How to Add a New Language

1. **Fork and Clone** the repository:
   ```bash
   git clone https://github.com/Immo-Boussole/immo-boussole.git
   cd immo-boussole
   ```

2. **Locate the Translations Directory**:
   All localization files are stored as JSON dictionaries in the `locales/` folder:
   - `locales/en.json` (English - Reference template)
   - `locales/fr.json` (French)

3. **Create your Language File**:
   Use the two-letter [ISO 639-1 language code](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes) (e.g., `de.json` for German, `es.json` for Spanish, `it.json` for Italian, `pt.json` for Portuguese, `nl.json` for Dutch):
   ```bash
   cp locales/en.json locales/<language_code>.json
   ```

4. **Translate the Strings**:
   Open `locales/<language_code>.json` and translate the values into your language.
   - Keep key names unchanged (e.g. `"nav.dashboard"`, `"app.title"`).
   - Preserve formatting placeholders such as `{count}` or `{name}`.

5. **Automatic Discovery**:
   Immo-Boussole automatically discovers any new `.json` file in `locales/` at startup and supports dynamic hot-reloading on disk changes. No code changes are required!

6. **Test Locally**:
   Run the test suite to verify i18n integrity:
   ```bash
   pytest tests/test_translations_i18n.py
   ```

7. **Submit a Pull Request**:
   Create a feature branch and open a PR with a title like:
   `i18n: add Spanish (es) translation`

---

Thank you for helping translate Immo-Boussole for users worldwide! 🚀
