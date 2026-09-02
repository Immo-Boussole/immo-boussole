#!/usr/bin/env python3
import os

def test_listing_detail_responsive_markup_and_css():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    listing_template_path = os.path.join(base_dir, "templates", "listing_detail.html")
    mobile_css_path = os.path.join(base_dir, "static", "css", "mobile.css")

    # 1. Verify listing_detail.html template
    assert os.path.exists(listing_template_path), "listing_detail.html must exist"
    with open(listing_template_path, "r", encoding="utf-8") as f:
        html = f.read()

    assert '<link href="/static/css/mobile.css?' in html
    assert 'class="layout"' in html
    assert 'class="left-col"' in html
    assert 'class="right-panel"' in html
    assert 'class="timeline-wrapper"' in html
    assert 'class="timeline-scroll-container"' in html
    assert '.left-col, .right-panel, .right-col' in html
    assert '.timeline-wrapper' in html
    assert 'min-width: 0' in html
    assert 'overflow-x: hidden' in html

    # 2. Verify mobile.css responsive overrides
    assert os.path.exists(mobile_css_path), "mobile.css must exist"
    with open(mobile_css_path, "r", encoding="utf-8") as f:
        css = f.read()

    assert ".layout" in css
    assert ".left-col, .right-panel, .right-col" in css
    assert ".timeline-wrapper" in css
    assert ".timeline-scroll-container" in css
    assert ".zone-repair-banner" in css
    assert ".topbar" in css
    assert "overflow-x: auto" in css

    print("Responsive design validation tests for listing_detail passed successfully!")

if __name__ == "__main__":
    test_listing_detail_responsive_markup_and_css()
