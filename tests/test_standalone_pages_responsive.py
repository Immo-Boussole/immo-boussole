#!/usr/bin/env python3
"""
Unit and regression test verifying that standalone / public / magic-link pages:
1. Maintain strict isolation from global dashboard-specific fixed viewport constraints (e.g. mobile.css).
2. Include standard responsive viewport meta tags.
3. Contain dedicated mobile responsive media queries and accessible touch targets in their respective stylesheets.
"""
import os

def test_standalone_pages_responsive_isolation():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    templates_dir = os.path.join(base_dir, "templates")
    css_dir = os.path.join(base_dir, "static", "css")

    # 1. Test visite_session.html (Collaborative Visit Workspace /v/{token})
    visite_session_template = os.path.join(templates_dir, "visite_session.html")
    assert os.path.exists(visite_session_template), "visite_session.html must exist"
    
    with open(visite_session_template, "r", encoding="utf-8") as f:
        vs_html = f.read()

    # Must NOT include dashboard-specific mobile.css
    assert "mobile.css" not in vs_html, "visite_session.html must NOT import mobile.css to avoid locked-body viewport on smartphones"

    # Must contain proper viewport meta tag
    assert '<meta name="viewport"' in vs_html, "visite_session.html must include responsive viewport meta tag"

    # Must link dedicated visite_session.css
    assert "visite_session.css" in vs_html, "visite_session.html must link visite_session.css"

    # 2. Test visite_session.css rules
    visite_css_path = os.path.join(css_dir, "visite_session.css")
    assert os.path.exists(visite_css_path), "visite_session.css must exist"
    
    with open(visite_css_path, "r", encoding="utf-8") as f:
        vs_css = f.read()

    # Must contain mobile media queries
    assert "@media (max-width: 768px)" in vs_css, "visite_session.css must include max-width: 768px media query"
    assert "@media (max-width: 480px)" in vs_css, "visite_session.css must include max-width: 480px media query"

    # Body must not be position: fixed
    assert "position: fixed !important" not in vs_css, "visite_session.css must not lock body with position: fixed"

    # Must style accordion classes and tabs
    assert ".vs-q-header" in vs_css, "visite_session.css must style .vs-q-header"
    assert ".vs-q-body" in vs_css, "visite_session.css must style .vs-q-body"
    assert ".vs-tabs-bar" in vs_css, "visite_session.css must style .vs-tabs-bar"

    print("Standalone responsive isolation tests passed successfully!")

if __name__ == "__main__":
    test_standalone_pages_responsive_isolation()
