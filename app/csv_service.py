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
from datetime import datetime, date
from sqlalchemy.orm import Session
from app.models import VisitQuestion, GlobalQuestion, Visit, Listing, VisitInclusion
from app.visit_templates import record_in_global_catalog


def fix_mojibake(text: Optional[str]) -> Optional[str]:
    """
    Restaure les chaînes contenant des artefacts de mojibake causés par un décodage
    ou ré-encodage défectueux (ex: UTF-8 décodé à tort comme Latin-1 / CP1252 / Windows-1252).
    Exemples réparés :
    - 'sÃ©curitÃ©' -> 'sécurité'
    - 'Salle Ã  manger' -> 'Salle à manger'
    - 'RÃ©frigÃ©rateur' -> 'Réfrigérateur'
    - 'Ã\x80 nÃ©gocier' -> 'À négocier'
    - 'mÃ¢t' -> 'mât'
    """
    if not text or not isinstance(text, str):
        return text

    s = text
    # Si le texte contient des marqueurs caractéristiques de double encodage UTF-8
    mojibake_markers = ("Ã©", "Ã¨", "Ã\xa0", "Ã¢", "Ãª", "Ã®", "Ã¯", "Ã´", "Ã»", "Ã¹", "Ã§", "Ã ", "Ã\x80", "Ã\x89", "Ã\x88", "Ã\x8a", "Ã\x87", "â\x80\x99", "â\x80\x98", "â\x80\x9c", "â\x80\x9d", "â\x80\x93", "â\x80\x94", "â\x82¬")
    has_marker = any(m in s for m in mojibake_markers)

    if has_marker:
        for enc in ("cp1252", "latin-1", "iso-8859-1"):
            try:
                candidate = s.encode(enc).decode("utf-8")
                # Si le candidat ne produit pas de caractère de remplacement non résolu et réduit les marqueurs
                if candidate != s:
                    s = candidate
                    break
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue

    # Remplacements ciblés de résidus fréquents de conversion Windows-1252 / Excel
    replacements = {
        "Ã\x80": "À",
        "Ã©": "é",
        "Ã¨": "è",
        "Ã\xa0": "à",
        "Ã¢": "â",
        "Ãª": "ê",
        "Ã®": "î",
        "Ã¯": "ï",
        "Ã´": "ô",
        "Ã»": "û",
        "Ã¹": "ù",
        "Ã§": "ç",
        "Ã\x89": "É",
        "Ã\x88": "È",
        "Ã\x8a": "Ê",
        "Ã\x87": "Ç",
        "â\x80\x99": "'",
        "â\x80\x98": "'",
        "â\x80\x9c": '"',
        "â\x80\x9d": '"',
        "â\x80\x93": "-",
        "â\x80\x94": "-",
        "â\x82¬": "€",
        "\xa0": " ",
    }
    for bad, good in replacements.items():
        if bad in s:
            s = s.replace(bad, good)

    return s.strip() if isinstance(s, str) else s


def decode_csv_bytes(content_bytes: bytes) -> str:
    """
    Détecte l'encodage et décode de manière ultra-tolérante le flux d'octets d'un fichier CSV.
    Supporte UTF-8-SIG (BOM Excel), UTF-8 standard, CP1252 (Windows français standard),
    Latin-1 (ISO-8859-1), UTF-16-LE / UTF-16-BE.
    Applique ensuite une passe de réparation des mojibakes.
    """
    if not content_bytes:
        return ""

    decoded_text = None
    encodings_to_try = [
        "utf-8-sig",
        "utf-8",
        "cp1252",
        "latin-1",
        "iso-8859-15",
        "utf-16",
        "utf-16-le",
        "utf-16-be",
    ]

    for enc in encodings_to_try:
        try:
            decoded = content_bytes.decode(enc)
            # Vérification de cohérence minimale
            if "\x00" in decoded and "utf-16" not in enc:
                continue
            decoded_text = decoded
            break
        except (UnicodeDecodeError, LookupError):
            continue

    if decoded_text is None:
        decoded_text = content_bytes.decode("latin-1", errors="replace")

    # Nettoyage du BOM UTF-8 éventuel restant
    if decoded_text.startswith("\ufeff"):
        decoded_text = decoded_text[1:]

    # Réparation automatique globale du mojibake sur l'ensemble du flux textuel
    return fix_mojibake(decoded_text) or ""


def export_questions_to_csv(questions: List[VisitQuestion]) -> str:
    """
    Exporte une liste de questions de visite/bien au format CSV (UTF-8-SIG, séparateur ';').
    Colonnes : id;langue;thematiques;question;statut;personnes_affectees;reponse;source_reponse;compte_reponse;date_reponse;auteur_question;date_creation
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
        "personnes_affectees",
        "reponse",
        "source_reponse",
        "compte_reponse",
        "date_reponse",
        "auteur_question",
        "date_creation"
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
        assigned_str = ", ".join(q.assigned_list) if hasattr(q, "assigned_list") else (q.assigned_to or "")
        created_str = q.created_at.strftime("%Y-%m-%d %H:%M:%S") if q.created_at else ""
        answered_date_str = (
            q.answered_at.strftime("%Y-%m-%d %H:%M:%S") if (hasattr(q, "answered_at") and q.answered_at)
            else (q.updated_at.strftime("%Y-%m-%d %H:%M:%S") if q.answer_text and q.updated_at else "")
        )

        writer.writerow([
            q.id,
            q.language or "fr",
            themes_str,
            q.question_text or "",
            q.status or "en_attente",
            assigned_str,
            q.answer_text or "",
            q.respondent_type or "",
            q.answered_by or "",
            answered_date_str,
            q.created_by or "",
            created_str
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
        elif clean in ("personnes_affectees", "personnes_assignees", "personnes_assignee", "personne_affectee", "assignes", "assigne", "affecte_a", "affectes", "assigned_to"):
            header_map["assigned_to"] = f
        elif clean in ("source_reponse", "source", "qui_a_repondu", "respondent_type", "repondeur", "source_rep"):
            header_map["respondent_type"] = f
        elif clean in ("compte_reponse", "auteur_reponse", "auteur_rep", "repondu_par", "answered_by") or "auteur_rep" in clean:
            header_map["answered_by"] = f
        elif clean in ("date_reponse", "date_rep", "answered_at"):
            header_map["answered_at"] = f
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
        raw_q_text = fix_mojibake(row.get(header_map.get("question", "question"), ""))
        if not raw_q_text:
            continue

        raw_id = row.get(header_map.get("id", "id"), "").strip()
        raw_lang = (row.get(header_map.get("language", "langue"), "") or default_language or "fr").strip().lower()
        raw_themes = fix_mojibake(row.get(header_map.get("themes", "thematiques"), ""))
        raw_status = (row.get(header_map.get("status", "statut"), "") or "").strip().lower()
        raw_assigned = fix_mojibake(row.get(header_map.get("assigned_to", "personnes_affectees"), ""))
        raw_answer = fix_mojibake(row.get(header_map.get("answer", "reponse"), ""))
        raw_resp_type = (row.get(header_map.get("respondent_type", "source_reponse"), "") or "").strip().lower()
        raw_author = fix_mojibake(row.get(header_map.get("created_by", "auteur_question"), "")) or author
        raw_answered_by = fix_mojibake(row.get(header_map.get("answered_by", "compte_reponse"), "")) or fix_mojibake(row.get("auteur_reponse", ""))
        raw_date_reponse = row.get(header_map.get("answered_at", "date_reponse"), "").strip()

        # Parse themes
        if raw_themes:
            themes = [t.strip() for t in raw_themes.replace(";", ",").replace("/", ",").split(",") if t.strip()]
        else:
            themes = ["Général"]

        # Parse assigned_to
        clean_assigned = None
        if raw_assigned:
            items = [x.strip() for x in raw_assigned.replace(";", ",").replace("/", ",").split(",") if x.strip()]
            clean_assigned = json.dumps(items, ensure_ascii=False) if items else None

        # Parse respondent_type
        clean_resp_type = None
        if raw_resp_type:
            if "agent" in raw_resp_type and "via" not in raw_resp_type:
                clean_resp_type = "agent"
            elif "via" in raw_resp_type or ("agent" in raw_resp_type and "proprio" in raw_resp_type):
                clean_resp_type = "proprietaire_via_agent"
            elif "direct" in raw_resp_type or "proprio" in raw_resp_type or "proprietaire" in raw_resp_type:
                clean_resp_type = "proprietaire_direct"
            elif raw_resp_type in ("agent", "proprietaire_via_agent", "proprietaire_direct"):
                clean_resp_type = raw_resp_type

        # Parse date_reponse
        parsed_answered_at = None
        if raw_date_reponse:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d"):
                try:
                    parsed_answered_at = datetime.strptime(raw_date_reponse, fmt)
                    break
                except ValueError:
                    pass

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
            if clean_assigned is not None:
                target_q.assigned_to = clean_assigned
            if raw_answer:
                target_q.answer_text = raw_answer
            if raw_answered_by:
                target_q.answered_by = raw_answered_by
            if clean_resp_type is not None:
                target_q.respondent_type = clean_resp_type
            if parsed_answered_at is not None:
                target_q.answered_at = parsed_answered_at
            elif raw_answer and not target_q.answered_at:
                target_q.answered_at = datetime.now()
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
                assigned_to=clean_assigned,
                answer_text=raw_answer or None,
                answered_by=raw_answered_by or (author if raw_answer else None),
                answered_at=parsed_answered_at or (datetime.now() if raw_answer else None),
                respondent_type=clean_resp_type,
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
        "personnes_affectees",
        "source_reponse",
        "compte_reponse",
        "auteur_question"
    ])
    writer.writerow([
        "fr",
        "Toiture & Charpente, Structure & Gros œuvre",
        "Quel est l'état général de la toiture et des combles ?",
        "satisfaisante",
        "Toiture refaite à neuf en 2021, factures fournies par le vendeur.",
        "Marie Martin, Jean Dupont",
        "proprietaire_via_agent",
        "Marie Martin",
        "Jean Dupont"
    ])
    writer.writerow([
        "fr",
        "Piscine, Extérieur, Jardin",
        "Quel est l'âge du liner de la piscine et l'état du système de filtration ?",
        "relance_necessaire",
        "Liner d'origine (12 ans), pompe changée l'an passé. Attente devis changement liner.",
        "Jean Dupont",
        "agent",
        "Jean Dupont",
        "Marie Martin"
    ])
    writer.writerow([
        "en",
        "Roof & Framework, Structure & Building Shell",
        "What is the overall condition of the roof and timber framework?",
        "satisfaisante",
        "Roof renewed in 2021, warranty invoices supplied by seller.",
        "John Doe",
        "proprietaire_direct",
        "John Doe",
        "Jane Doe"
    ])
    writer.writerow([
        "en",
        "Swimming Pool, Exterior, Garden",
        "What is the age of the pool liner and filtration pump?",
        "en_attente",
        "",
        "Jane Doe",
        "",
        "",
        "John Doe"
    ])

    return output.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# MOBILIER & SERVICES (INCLUSIONS) : EXPORT, IMPORT ET TEMPLATE CSV
# ─────────────────────────────────────────────────────────────────────────────

INCLUSIONS_CSV_HEADERS = [
    "id",
    "type",
    "piece",
    "titre",
    "variantes_declinaisons",
    "etat",
    "valeur_estimee_notaire",
    "fournisseur",
    "materiel_inclus",
    "date_debut_contrat",
    "date_fin_contrat",
    "cout_initial",
    "cout_mensuel",
    "cout_annuel",
    "statut_transfert",
    "statut_negociation",
    "notes",
    "photo_url"
]


def export_inclusions_to_csv(inclusions: List[VisitInclusion]) -> str:
    """
    Exporte une liste de mobilier, objets et contrats de service au format CSV unifié (UTF-8-SIG, séparateur ';').
    """
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_MINIMAL)
    writer.writerow(INCLUSIONS_CSV_HEADERS)

    for inc in inclusions:
        start_date = inc.contract_start_date.isoformat() if inc.contract_start_date else ""
        end_date = inc.contract_end_date.isoformat() if inc.contract_end_date else ""

        writer.writerow([
            inc.id or "",
            inc.item_type or "objet",
            inc.room or "",
            inc.title or "",
            inc.variation_notes or "",
            inc.condition or "",
            inc.estimated_value if inc.estimated_value is not None else "",
            inc.provider_name or "",
            inc.equipment_included or "",
            start_date,
            end_date,
            inc.initial_cost if inc.initial_cost is not None else "",
            inc.monthly_cost if inc.monthly_cost is not None else "",
            inc.annual_cost if inc.annual_cost is not None else "",
            inc.transfer_status or "",
            inc.negotiation_status or "inclus_prix_negocie",
            inc.notes or "",
            inc.photo_url or ""
        ])

    return output.getvalue()


def generate_inclusions_csv_template() -> str:
    """
    Génère un fichier modèle CSV (UTF-8-SIG, séparateur ';') pré-rempli avec des exemples concrets
    d'objets mobiliers et de contrats de service.
    """
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_MINIMAL)
    writer.writerow(INCLUSIONS_CSV_HEADERS)

    # Exemples Mobilier & Objets
    writer.writerow([
        "",  # id vide pour création
        "objet",
        "Salon",
        "Canapé d'angle convertible 4 places",
        "Tissu gris anthracite avec coffre de rangement intégré",
        "Très bon état",
        "850.0",
        "",  # fournisseur
        "",  # materiel_inclus
        "",  # date_debut_contrat
        "",  # date_fin_contrat
        "",  # cout_initial
        "",  # cout_mensuel
        "",  # cout_annuel
        "",  # statut_transfert
        "inclus_prix_negocie",
        "Facture d'achat 2023 fournie",
        ""   # photo_url
    ])
    writer.writerow([
        "",
        "objet",
        "Cuisine",
        "Îlot central avec 4 tabourets hauts",
        "Plateau chêne massif et piétement métal noir",
        "Bon état",
        "450.0",
        "", "", "", "", "", "", "", "",
        "inclus_prix_negocie",
        "Parfaitement ajusté aux dimensions de la pièce",
        ""
    ])

    # Exemples Services & Contrats
    writer.writerow([
        "",
        "service",
        "",  # piece
        "Abonnement Télésurveillance & Alarme",
        "",  # variantes
        "",  # etat
        "",  # valeur notaire
        "Verisure",
        "Centrale alarme GSM + 3 détecteurs volumétriques + 2 badges + 1 sirène",
        "2022-06-01",
        "2027-05-31",
        "299.0",
        "39.90",
        "478.80",
        "reprise_contrat",
        "inclus_prix_negocie",
        "Transfert de contrat possible sans frais d'installation",
        ""
    ])
    writer.writerow([
        "",
        "service",
        "",
        "Contrat Entretien Pompe à Chaleur (PAC)",
        "",
        "",
        "",
        "Engie Home Services",
        "Visite annuelle d'entretien + dépannage 7j/7 sous 48h inclus",
        "2024-01-01",
        "2025-12-31",
        "",
        "18.50",
        "222.0",
        "reprise_contrat",
        "en_discussion",
        "Dernier certificat d'entretien annuel disponible",
        ""
    ])

    return output.getvalue()


def _parse_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip().replace("€", "").replace(" ", "").replace(",", ".")
    try:
        return float(s) if s else None
    except ValueError:
        return None


def _parse_date(val: Any) -> Optional[date]:
    if not val:
        return None
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def import_inclusions_from_csv(
    db: Session,
    listing_id: int,
    visit_id: int,
    csv_content: str,
    replace_all: bool = False,
    created_by: str = "Import CSV"
) -> Dict[str, Any]:
    """
    Importe mobilier, objets et contrats de service depuis un contenu CSV unifié.
    - Détection automatique du séparateur (';' ou ',')
    - Tolérance aux en-têtes français et anglais
    - Si replace_all=True : vide les inclusions existantes de cette visite avant import
    - Si 'id' correspond à un élément existant du bien/visite : mise à jour
    - Sinon : création d'un nouvel élément VisitInclusion
    """
    if not csv_content or not csv_content.strip():
        return {
            "status": "error",
            "message": "Le fichier CSV est vide.",
            "total_processed": 0,
            "created": 0,
            "updated": 0,
            "errors": ["Le fichier CSV est vide."]
        }

    # Nettoyage du BOM UTF-8 éventuel
    if csv_content.startswith('\ufeff'):
        csv_content = csv_content[1:]

    first_line = csv_content.strip().split('\n')[0]
    delimiter = ';' if ';' in first_line else ','

    reader = csv.DictReader(io.StringIO(csv_content), delimiter=delimiter)
    fieldnames = reader.fieldnames or []

    # Correspondance tolérante des noms de colonnes
    header_map = {}
    for f in fieldnames:
        clean = f.strip().lower().replace(" ", "_").replace("é", "e").replace("è", "e").replace("à", "a").replace("'", "_")
        if clean in ("id", "identifiant"):
            header_map[f] = "id"
        elif clean in ("type", "type_element", "item_type", "categorie"):
            header_map[f] = "type"
        elif clean in ("piece", "room", "chambre", "espace", "lieu"):
            header_map[f] = "piece"
        elif clean in ("titre", "title", "designation", "nom", "meuble", "contrat"):
            header_map[f] = "titre"
        elif "variante" in clean or "declinaison" in clean or "precision" in clean or "variation" in clean:
            header_map[f] = "variantes_declinaisons"
        elif clean in ("etat", "condition", "etat_bien"):
            header_map[f] = "etat"
        elif "valeur" in clean or "notaire" in clean or "estimation" in clean:
            header_map[f] = "valeur_estimee_notaire"
        elif clean in ("fournisseur", "prestataire", "provider", "societe", "entreprise"):
            header_map[f] = "fournisseur"
        elif "materiel" in clean or "equipement" in clean or "equipment" in clean:
            header_map[f] = "materiel_inclus"
        elif "debut" in clean or "start" in clean:
            header_map[f] = "date_debut_contrat"
        elif "fin" in clean or "end" in clean or "echeance" in clean:
            header_map[f] = "date_fin_contrat"
        elif "initial" in clean or "achat" in clean or "pose" in clean:
            header_map[f] = "cout_initial"
        elif "mensuel" in clean or "month" in clean:
            header_map[f] = "cout_mensuel"
        elif "annuel" in clean or "year" in clean:
            header_map[f] = "cout_annuel"
        elif "transfert" in clean or "reprise" in clean:
            header_map[f] = "statut_transfert"
        elif "negociation" in clean or "inclus" in clean:
            header_map[f] = "statut_negociation"
        elif clean in ("notes", "remarque", "remarques", "commentaire", "commentaires"):
            header_map[f] = "notes"
        elif clean in ("photo", "photo_url", "image", "url_photo"):
            header_map[f] = "photo_url"

    if replace_all:
        db.query(VisitInclusion).filter(
            VisitInclusion.listing_id == listing_id,
            VisitInclusion.visit_id == visit_id
        ).delete()
        db.flush()

    # Indexation des éléments existants pour mise à jour éventuelle par ID
    existing_items = db.query(VisitInclusion).filter(
        VisitInclusion.listing_id == listing_id
    ).all()
    existing_by_id = {item.id: item for item in existing_items}

    created_count = 0
    updated_count = 0
    errors = []
    total_processed = 0

    for row_idx, raw_row in enumerate(reader, start=2):
        row = {header_map.get(k, k): (v.strip() if isinstance(v, str) else v) for k, v in raw_row.items() if k}

        # Ignorer lignes entièrement vides
        if not any(bool(v) for v in row.values()):
            continue

        total_processed += 1
        title = fix_mojibake(row.get("titre") or "")
        if not title:
            errors.append(f"Ligne {row_idx}: le titre ou la désignation est obligatoire.")
            continue

        raw_type = fix_mojibake(row.get("type") or "objet").strip().lower()
        item_type = "service" if ("serv" in raw_type or "contrat" in raw_type) else "objet"

        raw_id = row.get("id")
        parsed_id = None
        if raw_id:
            try:
                parsed_id = int(str(raw_id).strip())
            except ValueError:
                parsed_id = None

        target_item = existing_by_id.get(parsed_id) if (parsed_id and not replace_all) else None

        room = fix_mojibake(row.get("piece")) or None
        variation_notes = fix_mojibake(row.get("variantes_declinaisons")) or None
        condition = fix_mojibake(row.get("etat")) or ("À définir" if item_type == "objet" else None)
        estimated_value = _parse_float(row.get("valeur_estimee_notaire"))
        provider_name = fix_mojibake(row.get("fournisseur")) or None
        equipment_included = fix_mojibake(row.get("materiel_inclus")) or None
        contract_start_date = _parse_date(row.get("date_debut_contrat"))
        contract_end_date = _parse_date(row.get("date_fin_contrat"))
        initial_cost = _parse_float(row.get("cout_initial"))
        monthly_cost = _parse_float(row.get("cout_mensuel"))
        annual_cost = _parse_float(row.get("cout_annuel"))
        transfer_status = fix_mojibake(row.get("statut_transfert")) or None

        raw_neg = fix_mojibake(row.get("statut_negociation") or "")
        clean_neg = (raw_neg or "").lower().strip()
        if "negoc" in clean_neg or "disc" in clean_neg or "cours" in clean_neg:
            negotiation_status = "en_discussion"
        elif "excl" in clean_neg or "refus" in clean_neg:
            negotiation_status = "exclu_vendeur"
        elif "opt" in clean_neg or "payan" in clean_neg or "suppl" in clean_neg:
            negotiation_status = "option_payante"
        elif "inclus" in clean_neg or "prix" in clean_neg or "accord" in clean_neg or not clean_neg:
            negotiation_status = "inclus_prix_negocie"
        else:
            negotiation_status = raw_neg or "inclus_prix_negocie"

        notes = fix_mojibake(row.get("notes")) or None
        photo_url = row.get("photo_url") or None

        if target_item:
            target_item.item_type = item_type
            target_item.title = title
            if room is not None:
                target_item.room = room
            if variation_notes is not None:
                target_item.variation_notes = variation_notes
            if condition is not None:
                target_item.condition = condition
            if estimated_value is not None:
                target_item.estimated_value = estimated_value
            if provider_name is not None:
                target_item.provider_name = provider_name
            if equipment_included is not None:
                target_item.equipment_included = equipment_included
            if contract_start_date is not None:
                target_item.contract_start_date = contract_start_date
            if contract_end_date is not None:
                target_item.contract_end_date = contract_end_date
            if initial_cost is not None:
                target_item.initial_cost = initial_cost
            if monthly_cost is not None:
                target_item.monthly_cost = monthly_cost
            if annual_cost is not None:
                target_item.annual_cost = annual_cost
            if transfer_status is not None:
                target_item.transfer_status = transfer_status
            if negotiation_status is not None:
                target_item.negotiation_status = negotiation_status
            if notes is not None:
                target_item.notes = notes
            if photo_url is not None:
                target_item.photo_url = photo_url
            updated_count += 1
        else:
            new_inc = VisitInclusion(
                listing_id=listing_id,
                visit_id=visit_id,
                item_type=item_type,
                title=title,
                room=room,
                variation_notes=variation_notes,
                condition=condition,
                estimated_value=estimated_value,
                provider_name=provider_name,
                equipment_included=equipment_included,
                contract_start_date=contract_start_date,
                contract_end_date=contract_end_date,
                initial_cost=initial_cost,
                monthly_cost=monthly_cost,
                annual_cost=annual_cost,
                transfer_status=transfer_status,
                negotiation_status=negotiation_status,
                notes=notes,
                photo_url=photo_url,
                created_by=created_by
            )
            db.add(new_inc)
            created_count += 1

    db.commit()

    return {
        "status": "success",
        "total_processed": total_processed,
        "created": created_count,
        "updated": updated_count,
        "errors": errors
    }
