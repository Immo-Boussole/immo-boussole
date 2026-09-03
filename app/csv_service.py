"""
Module de gestion des imports et exports CSV pour les questions de visite et le catalogue global.
Conforme aux spécifications Immo-Boussole :
- Encodage : UTF-8 avec BOM (UTF-8-SIG) pour compatibilité totale Excel / LibreOffice / Google Sheets.
- Séparateur : point-virgule (;)
- Gestion tolérante : déduplication automatique, support multi-thématiques séparées par virgules.
"""
from __future__ import annotations
import csv
import io
import json
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from app.models import VisitQuestion, GlobalQuestion, Visit, Listing
from app.visit_templates import record_in_global_catalog


def export_questions_to_csv(questions: List[VisitQuestion]) -> str:
    """
    Exporte une liste de questions de visite/bien au format CSV (UTF-8-SIG, séparateur ';').
    Colonnes : id;langue;thematiques;question;statut;reponse;auteur_question;auteur_reponse;date_creation;date_reponse
    """
    output = io.StringIO()
    # Write BOM for Excel UTF-8 compatibility
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_MINIMAL)

    headers = [
        "id",
        "langue",
        "thematiques",
        "question",
        "statut",
        "reponse",
        "auteur_question",
        "auteur_reponse",
        "date_creation",
        "date_reponse"
    ]
    writer.writerow(headers)

    for q in questions:
        themes = []
        if q.themes_json:
            try:
                parsed = json.loads(q.themes_json)
                if isinstance(parsed, list):
                    themes = parsed
            except Exception:
                pass
        
        themes_str = ", ".join(themes)
        created_str = q.created_at.strftime("%Y-%m-%d %H:%M:%S") if q.created_at else ""
        updated_str = q.updated_at.strftime("%Y-%m-%d %H:%M:%S") if q.updated_at else ""

        writer.writerow([
            q.id,
            q.language or "fr",
            themes_str,
            q.question_text or "",
            q.status or "en_attente",
            q.answer_text or "",
            q.created_by or "",
            q.answered_by or "",
            created_str,
            updated_str
        ])

    return output.getvalue()


def import_questions_from_csv(
    db: Session,
    listing_id: int,
    visit_id: int,
    csv_content: str,
    default_language: str = "fr",
    author: str = "Import CSV"
) -> Dict[str, Any]:
    """
    Importe des questions/réponses depuis un contenu CSV (séparateur ';' ou détecté automatiquement).
    Met à jour les questions existantes (par matching id ou texte de question) et crée les nouvelles.
    Enregistre également les nouvelles questions dans le catalogue global transverse avec leur langue.
    """
    # Strip potential BOM
    if csv_content.startswith('\ufeff'):
        csv_content = csv_content[1:]

    # Detect delimiter (; or ,)
    first_line = csv_content.strip().split('\n')[0] if csv_content.strip() else ""
    delimiter = ';' if ';' in first_line else ','

    reader = csv.DictReader(io.StringIO(csv_content), delimiter=delimiter)
    
    # Normalize headers
    fieldnames = reader.fieldnames or []
    header_map = {}
    for f in fieldnames:
        clean = f.strip().lower().replace(" ", "_").replace("é", "e").replace("è", "e").replace("à", "a")
        if clean in ("langue", "lang", "language") or "lang" in clean:
            header_map["language"] = f
        elif clean in ("thematiques", "thematique", "themes", "theme", "tags", "tag", "categorie", "categories") or "theme" in clean or "tag" in clean:
            header_map["themes"] = f
        elif clean in ("auteur_reponse", "auteur_rep", "repondu_par", "answered_by") or "auteur_rep" in clean:
            header_map["answered_by"] = f
        elif clean in ("auteur_question", "auteur_quest", "auteur", "createur", "user", "created_by") or "auteur" in clean or "createur" in clean:
            header_map["created_by"] = f
        elif clean in ("question", "titre", "libelle_question", "intitule") or "quest" in clean:
            header_map["question"] = f
        elif clean in ("statut", "status", "etat") or "stat" in clean:
            header_map["status"] = f
        elif clean in ("reponse", "reponses", "answer", "note", "notes", "constat") or "rep" in clean:
            header_map["answer"] = f
        elif clean == "id":
            header_map["id"] = f

    # Fetch existing questions for this listing
    existing_questions = db.query(VisitQuestion).filter(
        (VisitQuestion.listing_id == listing_id) | (VisitQuestion.visit_id == visit_id)
    ).all()
    
    by_id = {q.id: q for q in existing_questions}
    by_text_lang = {(q.question_text.strip().lower(), (q.language or "fr").lower()): q for q in existing_questions}

    created_count = 0
    updated_count = 0
    max_order = max([q.order_index for q in existing_questions], default=-1)

    for row in reader:
        raw_q_text = row.get(header_map.get("question", "question"), "").strip()
        if not raw_q_text:
            continue

        raw_id = row.get(header_map.get("id", "id"), "").strip()
        raw_lang = row.get(header_map.get("language", "langue"), "").strip().lower() or default_language or "fr"
        raw_themes = row.get(header_map.get("themes", "thematiques"), "").strip()
        raw_status = row.get(header_map.get("status", "statut"), "").strip().lower()
        raw_answer = row.get(header_map.get("answer", "reponse"), "").strip()
        raw_author = row.get(header_map.get("created_by", "auteur_question"), "").strip() or author
        raw_answered_by = row.get(header_map.get("answered_by", "auteur_reponse"), "").strip()

        # Parse themes
        if raw_themes:
            themes = [t.strip() for t in raw_themes.replace(";", ",").replace("/", ",").split(",") if t.strip()]
        else:
            themes = ["Général"]

        # Validate status
        valid_statuses = {"en_attente", "satisfaisante", "relance_necessaire", "resolu", "non_applicable"}
        if raw_status not in valid_statuses:
            if "sat" in raw_status or "ok" in raw_status or "bon" in raw_status:
                raw_status = "satisfaisante"
            elif "rel" in raw_status or "att" in raw_status or "warn" in raw_status:
                raw_status = "relance_necessaire"
            elif "res" in raw_status or "valid" in raw_status:
                raw_status = "resolu"
            elif "non" in raw_status or "n/a" in raw_status or "na" in raw_status:
                raw_status = "non_applicable"
            else:
                raw_status = "en_attente"

        # Check existing match
        target_q = None
        if raw_id.isdigit() and int(raw_id) in by_id:
            target_q = by_id[int(raw_id)]
        elif (raw_q_text.lower(), raw_lang) in by_text_lang:
            target_q = by_text_lang[(raw_q_text.lower(), raw_lang)]

        if target_q:
            # Update existing
            target_q.question_text = raw_q_text
            target_q.status = raw_status
            target_q.themes_json = json.dumps(themes, ensure_ascii=False)
            target_q.language = raw_lang
            if raw_answer:
                target_q.answer_text = raw_answer
            if raw_answered_by:
                target_q.answered_by = raw_answered_by
            if not target_q.listing_id:
                target_q.listing_id = listing_id
            updated_count += 1
        else:
            # Create new
            max_order += 1
            new_q = VisitQuestion(
                listing_id=listing_id,
                visit_id=visit_id,
                question_text=raw_q_text,
                status=raw_status,
                themes_json=json.dumps(themes, ensure_ascii=False),
                language=raw_lang,
                created_by=raw_author,
                answer_text=raw_answer or None,
                answered_by=raw_answered_by or (author if raw_answer else None),
                order_index=max_order
            )
            db.add(new_q)
            by_text_lang[(raw_q_text.lower(), raw_lang)] = new_q
            created_count += 1

            # Auto-record in platform global catalog
            record_in_global_catalog(
                db=db,
                question_text=raw_q_text,
                themes=themes,
                language=raw_lang,
                created_by=raw_author
            )

    db.commit()

    return {
        "status": "success",
        "success": True,
        "created_count": created_count,
        "updated_count": updated_count,
        "total_processed": created_count + updated_count
    }


def export_global_catalog_to_csv(catalog: List[GlobalQuestion]) -> str:
    """
    Exporte le catalogue global de questions types au format CSV (UTF-8-SIG, ';').
    Colonnes : id;langue;categorie;thematiques;question;conseil_reponse;nombre_utilisations
    """
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_MINIMAL)

    writer.writerow([
        "id",
        "langue",
        "categorie",
        "thematiques",
        "question",
        "conseil_reponse",
        "nombre_utilisations"
    ])

    for gq in catalog:
        themes = []
        if gq.themes_json:
            try:
                parsed = json.loads(gq.themes_json)
                if isinstance(parsed, list):
                    themes = parsed
            except Exception:
                pass
        
        writer.writerow([
            gq.id,
            gq.language or "fr",
            gq.category or "Inspection technique",
            ", ".join(themes),
            gq.question_text or "",
            gq.advice_notes or "",
            gq.usage_count or 0
        ])

    return output.getvalue()


def import_global_catalog_from_csv(db: Session, csv_content: str, default_language: str = "fr", author: str = "Import CSV") -> Dict[str, Any]:
    """
    Importe ou enrichit le catalogue global de questions depuis un CSV avec attribution de langue.
    """
    if csv_content.startswith('\ufeff'):
        csv_content = csv_content[1:]

    first_line = csv_content.strip().split('\n')[0] if csv_content.strip() else ""
    delimiter = ';' if ';' in first_line else ','

    reader = csv.DictReader(io.StringIO(csv_content), delimiter=delimiter)
    
    header_map = {}
    for f in (reader.fieldnames or []):
        clean = f.strip().lower().replace(" ", "_").replace("é", "e").replace("è", "e").replace("à", "a")
        if clean in ("langue", "lang", "language") or "lang" in clean:
            header_map["language"] = f
        elif clean in ("thematiques", "thematique", "themes", "theme", "tags", "tag") or "theme" in clean or "tag" in clean:
            header_map["themes"] = f
        elif clean in ("question", "titre", "libelle_question", "intitule") or "quest" in clean:
            header_map["question"] = f
        elif clean in ("categorie", "categories", "category") or "cat" in clean:
            header_map["category"] = f
        elif clean in ("conseil_reponse", "conseil", "avis", "advice", "notes") or "cons" in clean or "note" in clean or "avis" in clean:
            header_map["advice"] = f

    created_count = 0
    updated_count = 0

    for row in reader:
        q_text = row.get(header_map.get("question", "question"), "").strip()
        if not q_text:
            continue

        raw_lang = row.get(header_map.get("language", "langue"), "").strip().lower() or default_language or "fr"
        raw_themes = row.get(header_map.get("themes", "thematiques"), "").strip()
        themes = [t.strip() for t in raw_themes.replace(";", ",").replace("/", ",").split(",") if t.strip()] if raw_themes else ["Général"]
        category = row.get(header_map.get("category", "categorie"), "").strip() or "Inspection technique"
        advice = row.get(header_map.get("advice", "conseil_reponse"), "").strip() or None

        gq = db.query(GlobalQuestion).filter(
            GlobalQuestion.question_text.ilike(q_text),
            GlobalQuestion.language == raw_lang
        ).first()

        if gq:
            gq.themes_json = json.dumps(themes, ensure_ascii=False)
            gq.category = category
            if advice:
                gq.advice_notes = advice
            updated_count += 1
        else:
            new_gq = GlobalQuestion(
                question_text=q_text,
                themes_json=json.dumps(themes, ensure_ascii=False),
                category=category,
                advice_notes=advice,
                language=raw_lang,
                created_by=author,
                usage_count=1
            )
            db.add(new_gq)
            created_count += 1

    db.commit()

    return {
        "success": True,
        "created_count": created_count,
        "updated_count": updated_count,
        "total_processed": created_count + updated_count
    }


def get_faq_csv_template() -> str:
    """
    Retourne un modèle CSV type commenté pour l'import de questions/réponses bilingues.
    """
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_MINIMAL)

    writer.writerow([
        "langue",
        "thematiques",
        "question",
        "statut",
        "reponse",
        "auteur_question"
    ])
    writer.writerow([
        "fr",
        "Toiture & Charpente, Structure & Gros œuvre",
        "Quel est l'état général de la toiture et des combles ?",
        "satisfaisante",
        "Toiture refaite à neuf en 2021, factures fournies par le vendeur.",
        "Jean Dupont"
    ])
    writer.writerow([
        "fr",
        "Piscine, Extérieur, Jardin",
        "Quel est l'âge du liner de la piscine et l'état du système de filtration ?",
        "relance_necessaire",
        "Liner d'origine (12 ans), pompe changée l'an passé. Attente devis changement liner.",
        "Marie Martin"
    ])
    writer.writerow([
        "en",
        "Roof & Framework, Structure & Building Shell",
        "What is the overall condition of the roof and timber framework?",
        "satisfaisante",
        "Roof renewed in 2021, warranty invoices supplied by seller.",
        "John Doe"
    ])
    writer.writerow([
        "en",
        "Swimming Pool, Exterior, Garden",
        "What is the age of the pool liner and filtration pump?",
        "en_attente",
        "",
        "John Doe"
    ])

    return output.getvalue()
