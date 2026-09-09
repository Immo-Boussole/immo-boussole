"""
Module de détection des biens "Sous compromis" pour Immo-Boussole.
Analyse le texte de description et effectue une reconnaissance optique de caractères (OCR)
sur la première photo pour repérer les bandeaux et mentions d'offres ou de compromis en cours.
"""

import os
import re
import unicodedata
import logging
from pathlib import Path
from typing import Optional, Tuple, Union

logger = logging.getLogger(__name__)


def normalize_text_for_detection(text: str) -> str:
    """
    Normalise le texte :
    - Décomposition Unicode (suppression des accents : 'é' -> 'e')
    - Passage en minuscules
    - Harmonisation des apostrophes et des tirets
    - Remplacement des retours à la ligne et espaces multiples
    """
    if not text:
        return ""
    # Normalisation NFKD pour séparer les diacritiques
    nfkd = unicodedata.normalize("NFKD", text)
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    lower = no_accents.lower()
    # Remplacer apostrophes courbes et tirets
    clean = re.sub(r"['’`]", "'", lower)
    clean = re.sub(r"[\r\n\t]+", " ", clean)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


# Expressions cibles de faux positifs fréquents dans les annonces immobilières
FALSE_POSITIVE_PATTERNS = [
    re.compile(r"\b(?:sans(?:\s+aucun)?|aucun|sans\s+faire\s+de)\s+compromis\b", re.IGNORECASE),
    re.compile(r"\b(?:le\s+|un\s+)?(?:bon|parfait|ideal|meilleur)\s+compromis\b", re.IGNORECASE),
    re.compile(r"\b(?:trouver|faire)\s+un\s+compromis\b", re.IGNORECASE),
    re.compile(r"\bcompromis\s+entre\b", re.IGNORECASE),
]

# Expressions cibles indiquant qu'un bien est sous compromis de vente ou sous offre
COMPROMIS_TEXT_PATTERNS = [
    (re.compile(r"\bsous\s+compromis(?:\s+de\s+vente)?\b", re.IGNORECASE), "sous compromis"),
    (re.compile(r"\bcompromis(?:\s+de\s+vente)?\s+en\s+cours\b", re.IGNORECASE), "compromis en cours"),
    (re.compile(r"\bcompromis\s+signe(?:e)?s?\b", re.IGNORECASE), "compromis signé"),
    (re.compile(r"\boffre(?:\s+d\s*'?\s*achat)?\s+acceptee?s?\b", re.IGNORECASE), "offre acceptée"),
    (re.compile(r"\boffre\s+au\s+prix\s+(?:en\s+cours\s+d\s*'?\s*etude|acceptee?s?)\b", re.IGNORECASE), "offre au prix"),
    (re.compile(r"\bvendu(?:e)?s?\s+sous\s+reserve(?:\s+d\s*'?\s*obtention\s+de\s+pret)?\b", re.IGNORECASE), "vendu sous réserve"),
    (re.compile(r"\bsous\s+offre(?:\s+d\s*'?\s*achat)?\b", re.IGNORECASE), "sous offre"),
    (re.compile(r"\b(?:bien|logement|maison|appartement|terrain)\s+actuellement\s+reservee?s?\b", re.IGNORECASE), "bien réservé"),
    (re.compile(r"\b(?:deja|actuellement)\s+reservee?s?\b", re.IGNORECASE), "déjà réservé"),
]

# Mots-clés cibles spécifiques pour l'OCR de bannières sur la première photo
OCR_BANNER_PATTERNS = [
    (re.compile(r"\bsous\s+compromis\b", re.IGNORECASE), "SOUS COMPROMIS"),
    (re.compile(r"\bcompromis\s+en\s+cours\b", re.IGNORECASE), "COMPROMIS EN COURS"),
    (re.compile(r"\bcompromis\b", re.IGNORECASE), "COMPROMIS"),
    (re.compile(r"\bsous\s+offre\b", re.IGNORECASE), "SOUS OFFRE"),
    (re.compile(r"\boffre\s+acceptee?s?\b", re.IGNORECASE), "OFFRE ACCEPTÉE"),
    (re.compile(r"\breservee?s?\b", re.IGNORECASE), "RÉSERVÉ"),
    (re.compile(r"\bvendue?s?\b", re.IGNORECASE), "VENDU"),
]


def detect_compromis_in_text(text: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Analyse le texte de description pour détecter la mention de bien sous compromis ou offre.
    Élimine au préalable les faux positifs de type 'sans compromis' ou 'compromis idéal'.
    
    Returns:
        (is_detected: bool, matched_label: Optional[str])
    """
    if not text:
        return False, None

    normalized = normalize_text_for_detection(text)
    if not normalized:
        return False, None

    # Masquer les faux positifs connus en les remplaçant par des espaces neutres
    cleaned_for_search = normalized
    for fp_pattern in FALSE_POSITIVE_PATTERNS:
        cleaned_for_search = fp_pattern.sub(" [FP_EXCLU] ", cleaned_for_search)

    # Vérifier la présence des expressions cibles
    for pattern, label in COMPROMIS_TEXT_PATTERNS:
        if pattern.search(cleaned_for_search):
            logger.info(f"[Compromis] Détecté dans le texte ('{label}')")
            return True, label

    return False, None


def detect_compromis_in_image(image_path: Union[str, Path]) -> Tuple[bool, Optional[str]]:
    """
    Effectue un OCR via Tesseract sur l'image passée en paramètre pour détecter les bandeaux
    'SOUS COMPROMIS', 'SOUS OFFRE', 'COMPROMIS', 'OFFRE ACCEPTÉE', 'VENDU' ou 'RÉSERVÉ'.
    
    Gestion d'erreur gracieuse si Tesseract ou pytesseract n'est pas disponible.
    
    Returns:
        (is_detected: bool, matched_label: Optional[str])
    """
    if not image_path:
        return False, None

    path_obj = Path(image_path)
    if not path_obj.is_file():
        # Essayer avec le préfixe relatif au workspace ou static
        clean_name = str(image_path).lstrip("/\\")
        alt_paths = [
            Path(clean_name),
            Path("static") / clean_name,
        ]
        found = False
        for p in alt_paths:
            if p.is_file():
                path_obj = p
                found = True
                break
        if not found:
            return False, None

    try:
        from PIL import Image
        import pytesseract
    except ImportError:
        logger.debug("[Compromis OCR] Pillow ou pytesseract non installé, passage de l'OCR.")
        return False, None

    try:
        with Image.open(path_obj) as img:
            # Redimensionner si très grande image pour accélérer l'OCR
            max_dimension = 1400
            w, h = img.size
            if max(w, h) > max_dimension:
                scale = max_dimension / max(w, h)
                img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.BILINEAR)

            # Convertir en niveaux de gris pour améliorer le contraste du texte
            try:
                if getattr(img, "mode", None) != "L":
                    img_gray = img.convert("L")
                else:
                    img_gray = img
            except Exception:
                img_gray = img

            ocr_passes = [
                (img_gray, "--psm 11"),
                (img_gray, ""),
            ]

            try:
                from PIL import ImageEnhance
                enhancer = ImageEnhance.Contrast(img_gray)
                img_contrast = enhancer.enhance(1.8)
                if img_contrast is not None:
                    ocr_passes.insert(1, (img_contrast, "--psm 11"))
                    ocr_passes.append((img_contrast, ""))
            except Exception as e_enh:
                logger.debug(f"[Compromis OCR] ImageEnhance contrast non appliqué: {e_enh}")

            for image_variant, config_flag in ocr_passes:
                try:
                    if config_flag:
                        extracted_text = pytesseract.image_to_string(image_variant, lang="fra+eng", config=config_flag)
                    else:
                        extracted_text = pytesseract.image_to_string(image_variant, lang="fra+eng")
                except Exception as e_lang:
                    # Fallback sur la langue par défaut si fra n'est pas installé
                    logger.debug(f"[Compromis OCR] Langue 'fra+eng' non disponible ({e_lang}), fallback langue par défaut")
                    if config_flag:
                        extracted_text = pytesseract.image_to_string(image_variant, config=config_flag)
                    else:
                        extracted_text = pytesseract.image_to_string(image_variant)

                if extracted_text:
                    normalized_ocr = normalize_text_for_detection(extracted_text)
                    for pattern, label in OCR_BANNER_PATTERNS:
                        if pattern.search(normalized_ocr):
                            logger.info(f"[Compromis OCR] Bandeau '{label}' détecté sur l'image {path_obj.name} (config='{config_flag}')")
                            return True, label

        return False, None

    except Exception as e:
        logger.warning(f"[Compromis OCR] Erreur lors de l'analyse de l'image {path_obj}: {e}")
        return False, None


def analyze_listing_compromis(
    description: Optional[str],
    first_photo_path: Optional[Union[str, Path]] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Point d'entrée unifié pour qualifier si un bien est sous compromis :
    1. Analyse textuelle de la description (très rapide).
    2. Si non concluant et qu'une première photo existe, exécution de l'OCR.
    
    Returns:
        (is_under_compromis: bool, detection_source: Optional[str])
        où detection_source est 'description', 'ocr' ou None.
    """
    # 1. Vérification dans la description
    detected_text, label_text = detect_compromis_in_text(description)
    if detected_text:
        return True, "description"

    # 2. Vérification sur la première photo
    if first_photo_path:
        detected_ocr, label_ocr = detect_compromis_in_image(first_photo_path)
        if detected_ocr:
            return True, "ocr"

    return False, None
