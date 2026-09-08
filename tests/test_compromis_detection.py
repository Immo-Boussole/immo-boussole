"""
Unit and integration tests for 'Sous compromis' detection engine:
- Text description semantic detection and strict exclusion of false positives ('sans compromis')
- Image OCR detection logic with mocked Tesseract output and error handling
- Database columns and automatic scanning task
"""

import sys
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile

# Ensure pytesseract is available in sys.modules for mock-based testing across all environments
if "pytesseract" not in sys.modules:
    mock_pytesseract = MagicMock()
    sys.modules["pytesseract"] = mock_pytesseract

from app.compromis import (
    normalize_text_for_detection,
    detect_compromis_in_text,
    detect_compromis_in_image,
    analyze_listing_compromis,
)
from app.models import Listing, ListingStatus, Source
from app.db_maintenance import scan_all_listings_for_compromis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import Base


# ── 1. Text Semantic Detection & False Positive Tests ─────────────────────────

def test_detect_compromis_in_text_positive_cases():
    positive_samples = [
        ("Maison 5 pièces - SOUS COMPROMIS DE VENTE - Visites suspendues.", "sous compromis"),
        ("Bel appartement T3. Compromis en cours avec notre agence.", "compromis en cours"),
        ("Compromis signé la semaine passée, dossier en cours.", "compromis signé"),
        ("Offre d'achat acceptée par les vendeurs hier soir.", "offre acceptée"),
        ("Offre acceptée au prix demandé.", "offre acceptée"),
        ("Offre au prix en cours d'étude par le propriétaire.", "offre au prix"),
        ("Vendu sous réserve d'obtention de prêt bancaire.", "vendu sous réserve"),
        ("Ce pavillon est sous offre.", "sous offre"),
        ("Maison actuellement réservée.", "bien réservé"),
        ("Appartement déjà réservé.", "déjà réservé"),
    ]
    for text, expected_label in positive_samples:
        detected, label = detect_compromis_in_text(text)
        assert detected is True, f"Failed to detect compromis in: {text}"
        assert label is not None


def test_detect_compromis_in_text_false_positive_exclusions():
    false_positive_samples = [
        "Rénovation haut de gamme sans compromis sur la qualité des matériaux.",
        "Un confort moderne sans aucun compromis.",
        "Ce bien représente le compromis idéal entre la vie citadine et le calme champêtre.",
        "Le parfait compromis pour une première acquisition immobilière.",
        "Un bon compromis volume/prix à deux pas de la gare.",
        "Une opportunité à saisir sans faire de compromis sur la localisation.",
        "Emplacement de stationnement privatif réservé aux résidents de l'immeuble.",
        "Espace réservé pour la création d'une buanderie ou cellier.",
        "Magnifique villa contemporaine avec piscine et vue dégagée.",
        "",
        None,
    ]
    for text in false_positive_samples:
        detected, label = detect_compromis_in_text(text)
        assert detected is False, f"False positive incorrectly flagged for: {text!r} (detected as {label})"


def test_detect_compromis_in_text_mixed_case():
    # If a listing contains both 'sans compromis' AND 'sous compromis', it must be detected!
    text = "Rénovation de standing sans compromis. Sous compromis de vente depuis ce matin."
    detected, label = detect_compromis_in_text(text)
    assert detected is True
    assert label == "sous compromis"


# ── 2. OCR Detection Tests ───────────────────────────────────────────────────

def test_detect_compromis_in_image_mocked():
    with patch("PIL.Image.open") as mock_open, \
         patch("pytesseract.image_to_string") as mock_tess:
        
        # Mock PIL image
        mock_img = MagicMock()
        mock_img.size = (800, 600)
        mock_img.mode = "RGB"
        mock_open.return_value.__enter__.return_value = mock_img

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            fake_path = Path(tf.name)

        try:
            # Case 1: Banner says "SOUS COMPROMIS"
            mock_tess.return_value = "IMMOBILIER DE FRANCE\nSOUS COMPROMIS\n05 56 00 00 00"
            detected, label = detect_compromis_in_image(fake_path)
            assert detected is True
            assert label == "SOUS COMPROMIS"

            # Case 2: Banner says "OFFRE ACCEPTÉE"
            mock_tess.return_value = "AGENCE DU CENTRE - OFFRE ACCEPTÉE"
            detected, label = detect_compromis_in_image(fake_path)
            assert detected is True
            assert label == "OFFRE ACCEPTÉE"

            # Case 3: Banner says "VENDU"
            mock_tess.return_value = "VENDU PAR NOTRE EQUIPE"
            detected, label = detect_compromis_in_image(fake_path)
            assert detected is True
            assert label == "VENDU"

            # Case 4: Normal image without banner
            mock_tess.return_value = "Salon séjour lumineux 35m2"
            detected, label = detect_compromis_in_image(fake_path)
            assert detected is False
            assert label is None

        finally:
            if fake_path.exists():
                fake_path.unlink()


def test_detect_compromis_in_image_missing_tesseract_graceful():
    # Test that missing binary or library returns False without crashing
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
        fake_path = Path(tf.name)

    try:
        with patch("pytesseract.image_to_string", side_effect=Exception("tesseract is not installed")):
            detected, label = detect_compromis_in_image(fake_path)
            assert detected is False
            assert label is None
    finally:
        if fake_path.exists():
            fake_path.unlink()


def test_analyze_listing_compromis_orchestration():
    # 1. Text match takes precedence (fast path without touching image)
    with patch("app.compromis.detect_compromis_in_image") as mock_ocr:
        is_comp, source = analyze_listing_compromis(
            description="Maison coup de coeur - Sous compromis",
            first_photo_path="static/media/1/photo_0.jpg"
        )
        assert is_comp is True
        assert source == "description"
        mock_ocr.assert_not_called()

    # 2. Text fails but OCR succeeds
    with patch("app.compromis.detect_compromis_in_image", return_value=(True, "SOUS COMPROMIS")):
        is_comp, source = analyze_listing_compromis(
            description="Belle maison lumineuse sans compromis sur l'espace.",
            first_photo_path="static/media/1/photo_0.jpg"
        )
        assert is_comp is True
        assert source == "ocr"

    # 3. Neither text nor OCR match
    with patch("app.compromis.detect_compromis_in_image", return_value=(False, None)):
        is_comp, source = analyze_listing_compromis(
            description="Belle maison lumineuse sans compromis sur l'espace.",
            first_photo_path="static/media/1/photo_0.jpg"
        )
        assert is_comp is False
        assert source is None


# ── 3. Database & Retroactive Scan Tests ──────────────────────────────────────

def test_database_compromis_fields_and_retroactive_scan():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    db = TestingSession()

    try:
        # Create test listings
        l1 = Listing(
            url="https://example.com/ad1",
            title="Maison en vente",
            description_text="Charmante maison de village. Sous compromis de vente.",
            status=ListingStatus.ACTIVE,
            source=Source.LEBONCOIN,
        )
        l2 = Listing(
            url="https://example.com/ad2",
            title="Appartement standing",
            description_text="Un luxe sans compromis au coeur de la ville.",
            status=ListingStatus.ACTIVE,
            source=Source.SELOGER,
        )
        l3 = Listing(
            url="https://example.com/ad3",
            title="Terrain constructible",
            description_text="Beau terrain plat",
            is_under_compromis=False,
            compromis_detected_by="manual",  # User manually marked as NOT under compromis
            status=ListingStatus.ACTIVE,
            source=Source.MANUAL,
        )

        db.add_all([l1, l2, l3])
        db.commit()

        # Run retroactive scan
        results = scan_all_listings_for_compromis(db)

        db.refresh(l1)
        db.refresh(l2)
        db.refresh(l3)

        assert l1.is_under_compromis is True
        assert l1.compromis_detected_by == "description"

        assert l2.is_under_compromis is False
        assert l2.compromis_detected_by is None

        # Manual override on l3 must be preserved
        assert l3.is_under_compromis is False
        assert l3.compromis_detected_by == "manual"

        assert results["scanned"] == 3
        assert results["detected"] == 1

    finally:
        db.close()


if __name__ == "__main__":
    test_detect_compromis_in_text_positive_cases()
    test_detect_compromis_in_text_false_positive_exclusions()
    test_detect_compromis_in_text_mixed_case()
    test_detect_compromis_in_image_mocked()
    test_detect_compromis_in_image_missing_tesseract_graceful()
    test_analyze_listing_compromis_orchestration()
    test_database_compromis_fields_and_retroactive_scan()
    print("ALL COMPROMIS DETECTION TESTS PASSED!")
