"""
Unit tests for community catalog GitHub issue automation and visit_templates JSON loading.
"""
import os
import sys
import json
import pytest
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.visit_templates import (
    load_default_catalog_questions,
    get_default_inspection_pack,
    DEFAULT_INSPECTION_PACK,
    DEFAULT_INSPECTION_PACK_EN
)
from scripts.process_catalog_question_issue import (
    parse_issue_form,
    process_catalog_issue,
    load_questions,
    save_questions,
    JSON_PATH
)


def test_visit_templates_loads_from_json():
    """Verifies that visit_templates correctly loads 42 default questions from default_catalog_questions.json."""
    all_qs = load_default_catalog_questions()
    assert len(all_qs) >= 42
    
    fr_pack = get_default_inspection_pack("fr")
    assert len(fr_pack) >= 21
    assert all(q["language"] == "fr" for q in fr_pack)

    en_pack = get_default_inspection_pack("en")
    assert len(en_pack) >= 21
    assert all(q["language"] == "en" for q in en_pack)


def test_parse_issue_form_add_action():
    issue_body = """
### Action / Type de proposition
Ajouter une nouvelle question / Add a new question

### Language / Langue
fr (Français)

### Category / Catégorie
Structure & Gros œuvre / Structure & Shell

### Themes / Thématiques
Charpente, Traitement bois, Termites

### Proposed Question Text / Intitulé de la question proposée
Le bois de charpente a-t-il subi un traitement préventif ou curatif contre les termites et capricornes ?

### Target Existing Question / Intitulé de la question existante ciblée
_No response_

### Verification Advice / Conseils d'inspection ou points de contrôle
Demander l'attestation de garantie décennale du traitement et inspecter les combles.

### Motivation / Justification
Indispensable dans les zones soumises à un arrêté préfectoral termites.
"""
    parsed = parse_issue_form(issue_body)
    assert parsed["action"] == "add"
    assert parsed["language"] == "fr"
    assert parsed["category"] == "Structure & Gros œuvre"
    assert "Charpente" in parsed["themes"]
    assert "Traitement bois" in parsed["themes"]
    assert "termites" in parsed["question_text"].lower()
    assert parsed["target_existing_text"] == ""
    assert "garantie décennale" in parsed["advice_notes"]


def test_process_catalog_issue_add_modify_remove_lifecycle(tmp_path, monkeypatch):
    """
    Tests full lifecycle of adding, modifying, and removing questions on a temporary copy of default_catalog_questions.json.
    """
    temp_json = tmp_path / "test_catalog.json"
    initial_data = [
        {
            "id": 1,
            "question_text": "Quel est l'état de la toiture ?",
            "themes": ["Toiture"],
            "category": "Structure & Gros œuvre",
            "advice_notes": "Vérifier combles.",
            "language": "fr"
        },
        {
            "id": 2,
            "question_text": "What is the roof condition?",
            "themes": ["Roof"],
            "category": "Structure & Shell",
            "advice_notes": "Check attic.",
            "language": "en"
        }
    ]
    with open(temp_json, "w", encoding="utf-8") as f:
        json.dump(initial_data, f, ensure_ascii=False)

    import scripts.process_catalog_question_issue as script_mod
    monkeypatch.setattr(script_mod, "JSON_PATH", temp_json)

    # 1. Test ADD action
    add_issue = """
### Action / Type de proposition
Ajouter une nouvelle question / Add a new question

### Language / Langue
fr (Français)

### Category / Catégorie
Énergie & Chauffage

### Themes / Thématiques
DPE, Pompe à chaleur

### Proposed Question Text / Intitulé de la question proposée
Quel est le COP (coefficient de performance) réel de la pompe à chaleur ?

### Verification Advice / Conseils d'inspection ou points de contrôle
Vérifier la plaque signalétique de l'unité extérieure.

### Motivation / Justification
Vérification énergétique.
"""
    add_res = script_mod.process_catalog_issue(add_issue)
    assert add_res["success"] is True
    assert "add question (fr)" in add_res["commit_title"]

    with open(temp_json, "r", encoding="utf-8") as f:
        qs = json.load(f)
    assert len(qs) == 3
    added_item = next(q for q in qs if "COP" in q["question_text"])
    assert added_item["id"] == 3
    assert added_item["language"] == "fr"
    assert "Pompe à chaleur" in added_item["themes"]

    # 2. Test duplicate ADD prevention
    dup_res = script_mod.process_catalog_issue(add_issue)
    assert dup_res["success"] is False
    assert "existe déjà" in dup_res["error"]

    # 3. Test TRANSLATE action (Spanish)
    translate_issue = """
### Action / Type de proposition
Traduire une question existante / Translate an existing question

### Language / Langue
es (Español)

### Category / Catégorie
Estructura y Obra gruesa

### Themes / Thématiques
Tejado, Mantenimiento

### Proposed Question Text / Intitulé de la question proposée
¿Cuál es el estado general del tejado y la estructura?

### Target Existing Question / Intitulé de la question existante ciblée
Quel est l'état de la toiture ?

### Verification Advice / Conseils d'inspection ou points de contrôle
Inspeccionar el ático.
"""
    trans_res = script_mod.process_catalog_issue(translate_issue)
    assert trans_res["success"] is True
    with open(temp_json, "r", encoding="utf-8") as f:
        qs = json.load(f)
    assert len(qs) == 4
    es_item = next(q for q in qs if q["language"] == "es")
    assert "¿Cuál es el estado" in es_item["question_text"]

    # 4. Test MODIFY action
    modify_issue = """
### Action / Type de proposition
Modifier une question existante / Modify an existing question

### Language / Langue
fr (Français)

### Category / Catégorie
Énergie, Chauffage & Climatisation

### Themes / Thématiques
DPE, Pompe à chaleur, Climatisation réversible

### Proposed Question Text / Intitulé de la question proposée
Quel est le COP réel et la puissance thermique de la pompe à chaleur ?

### Target Existing Question / Intitulé de la question existante ciblée
Quel est le COP (coefficient de performance) réel de la pompe à chaleur ?

### Verification Advice / Conseils d'inspection ou points de contrôle
Consulter la fiche technique fabricant et le contrat d'entretien.
"""
    mod_res = script_mod.process_catalog_issue(modify_issue)
    assert mod_res["success"] is True
    with open(temp_json, "r", encoding="utf-8") as f:
        qs = json.load(f)
    assert len(qs) == 4
    mod_item = next(q for q in qs if q["id"] == 3)
    assert "puissance thermique" in mod_item["question_text"]
    assert "Climatisation réversible" in mod_item["themes"]

    # 5. Test REMOVE action
    remove_issue = """
### Action / Type de proposition
Supprimer une question / Remove a question

### Language / Langue
es (Español)

### Category / Catégorie
Estructura

### Proposed Question Text / Intitulé de la question proposée
¿Cuál es el estado general del tejado y la estructura?

### Target Existing Question / Intitulé de la question existante ciblée
4

### Motivation / Justification
Doublon.
"""
    rem_res = script_mod.process_catalog_issue(remove_issue)
    assert rem_res["success"] is True
    with open(temp_json, "r", encoding="utf-8") as f:
        qs = json.load(f)
    assert len(qs) == 3
    assert not any(q["language"] == "es" for q in qs)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
