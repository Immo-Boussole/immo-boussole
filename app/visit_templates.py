"""
Module de modèles de questions d'inspection et FAQ pour les visites et contre-visites.
Propose des packs de questions types multi-thématiques couvrant l'ensemble des aspects
d'un bien immobilier (Structure, Toiture, DPE/Chauffage, Copro, Extérieurs, etc.).
"""
from __future__ import annotations
import json
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models import Visit, VisitQuestion, GlobalQuestion


DEFAULT_INSPECTION_PACK: List[Dict[str, Any]] = [
    # ─── 1. Bâtiment, Structure & Gros Œuvre ──────────────────────────────
    {
        "question_text": "Quel est l'état général de la toiture, de la charpente et de la couverture ? Des infiltrations ou réparations récentes ont-elles eu lieu ?",
        "themes": ["Toiture & Charpente", "Structure & Gros œuvre", "Entretien à prévoir"],
        "category": "Structure & Gros œuvre",
        "advice_notes": "Vérifier la date de réfection de toiture et inspecter les combles."
    },
    {
        "question_text": "Y a-t-il des fissures traversantes, des traces d'humidité ou des remontées capillaires sur les murs porteurs et en sous-sol/cave ?",
        "themes": ["Structure & Gros œuvre", "Humidité & Assainissement", "Sous-sol & Cave"],
        "category": "Structure & Gros œuvre",
        "advice_notes": "Rechercher des traces de salpêtre ou moisissure en cave et soubassements."
    },
    {
        "question_text": "Quel est l'âge et l'état du ravalement de façade ? Des travaux d'isolation par l'extérieur (ITE) sont-ils prévus ou votés ?",
        "themes": ["Façade & Extérieur", "Structure & Gros œuvre", "Copropriété", "Travaux & Budget"],
        "category": "Structure & Gros œuvre",
        "advice_notes": "Consulter les 3 derniers procès-verbaux d'assemblée générale."
    },

    # ─── 2. Énergie, Chauffage, DPE & Isolation ──────────────────────────
    {
        "question_text": "Quel est le mode et le coût annuel réel de chauffage (chaudière, PAC, radiateurs) ? De quand date la dernière révision / installation ?",
        "themes": ["Chauffage & Énergie", "DPE & Isolation", "Charges & Budget", "Entretien à prévoir"],
        "category": "Énergie & Chauffage",
        "advice_notes": "Demander les factures réelles des 2 dernières années et l'attestation d'entretien annuel."
    },
    {
        "question_text": "Quelle est la nature du vitrage (simple, double, phonique/thermique) et l'état des menuiseries/volets ?",
        "themes": ["DPE & Isolation", "Menuiseries & Fenêtres", "Travaux & Budget"],
        "category": "Énergie & Chauffage",
        "advice_notes": "Inspecter l'étanchéité à l'air des ouvrants."
    },
    {
        "question_text": "Comment fonctionne la ventilation (VMC simple flux, double flux, naturelle) ? Est-elle opérationnelle dans les pièces humides ?",
        "themes": ["DPE & Isolation", "Humidité & Assainissement", "Plomberie & Sanitaires"],
        "category": "Énergie & Chauffage",
        "advice_notes": "Vérifier l'aspiration des bouches d'extraction avec une feuille de papier."
    },

    # ─── 3. Réseaux, Électricité & Plomberie ──────────────────────────────
    {
        "question_text": "Le tableau électrique est-il aux normes (différentiels 30mA, disjoncteurs, présence de terre dans toutes les pièces) ?",
        "themes": ["Électricité & Sécurité", "Diagnostics & Conformité"],
        "category": "Réseaux & Électricité",
        "advice_notes": "Consulter le diagnostic électrique (anomalies B3, B4 ou absence de terre)."
    },
    {
        "question_text": "Quel est l'état de la plomberie générale (matériaux plomb/cuivre/multicouche, pression, chauffe-eau récent) ?",
        "themes": ["Plomberie & Sanitaires", "Entretien à prévoir"],
        "category": "Réseaux & Plomberie",
        "advice_notes": "Vérifier la pression aux robinets et l'âge du cumulus."
    },
    {
        "question_text": "L'assainissement est-il collectif (tout-à-l'égout raccordé et conforme) ou individuel (fosse septique aux normes SPANC) ?",
        "themes": ["Humidité & Assainissement", "Diagnostics & Conformité", "Administratif & Urbanisme"],
        "category": "Réseaux & Assainissement",
        "advice_notes": "Demander le certificat de conformité d'assainissement de la commune ou du SPANC."
    },

    # ─── 4. Extérieur, Jardin, Piscine & Dépendances ──────────────────────
    {
        "question_text": "Quels sont les équipements extérieurs et l'entretien régulier à prévoir (arrosage, clôtures, portail automatique, dépendances) ?",
        "themes": ["Extérieur", "Jardin", "Entretien à prévoir"],
        "category": "Extérieur & Jardin",
        "advice_notes": "Vérifier la mitoyenneté des clôtures et haies."
    },
    {
        "question_text": "Quel est l'état de la piscine et de ses équipements (liner/coque, pompe, filtration, système de sécurité conforme) ?",
        "themes": ["Piscine", "Extérieur", "Jardin", "Entretien à prévoir", "Charges & Budget"],
        "category": "Extérieur & Jardin",
        "advice_notes": "Demander la date du liner et l'attestation de conformité du système de sécurité (alarme, bâche ou barrière)."
    },
    {
        "question_text": "Existe-t-il des servitudes de passage, de vue ou de réseaux traversant le terrain/jardin ?",
        "themes": ["Extérieur", "Jardin", "Administratif & Urbanisme", "Juridique & Servitudes"],
        "category": "Juridique & Servitudes",
        "advice_notes": "Consulter le titre de propriété antérieur et le plan cadastral."
    },

    # ─── 5. Copropriété, Charges & Assemblées Générales ──────────────────
    {
        "question_text": "Quel est le montant exact des charges courantes mensuelles et ce qu'elles comprennent (eau, chauffage, ascenseur, gardien) ?",
        "themes": ["Copropriété", "Charges & Budget"],
        "category": "Copropriété",
        "advice_notes": "Vérifier les 4 derniers appels de fonds."
    },
    {
        "question_text": "Y a-t-il des travaux récemment votés ou prévus lors des prochaines AG (ravalement, toiture, ascenseur, chaufferie) ?",
        "themes": ["Copropriété", "Travaux & Budget"],
        "category": "Copropriété",
        "advice_notes": "Analyser les PV des 3 dernières AG et le carnet d'entretien."
    },
    {
        "question_text": "Y a-t-il des impayés significatifs ou des procédures en cours au sein de la copropriété / syndic ?",
        "themes": ["Copropriété", "Juridique & Servitudes"],
        "category": "Copropriété",
        "advice_notes": "Consulter le pré-état daté fourni par le vendeur."
    },

    # ─── 6. Environnement, Voisinage & Vie Quotidienne ───────────────────
    {
        "question_text": "Quel est le niveau sonore aux heures de pointe, en soirée et le week-end (bruit de rue, mitoyenneté, chemin de fer, commerces) ?",
        "themes": ["Voisinage & Bruit", "Environnement & Quartier"],
        "category": "Environnement",
        "advice_notes": "Effectuer une contre-visite à une heure de pointe et en soirée."
    },
    {
        "question_text": "Quelle est l'exposition réelle du salon et des espaces de vie tout au long de la journée / luminosité ?",
        "themes": ["Luminosité & Orientation", "Environnement & Quartier"],
        "category": "Environnement",
        "advice_notes": "Vérifier la boussole et le simulateur solaire Immo-Boussole."
    },
    {
        "question_text": "Où se situent les commodités immédiates (transports, écoles, commerces, stationnement visiteurs) ?",
        "themes": ["Environnement & Quartier", "Vie pratique"],
        "category": "Environnement",
        "advice_notes": "Tester le trajet à pied jusqu'aux transports et commerces."
    },

    # ─── 7. Taxes, Prix & Négociation ────────────────────────────────────
    {
        "question_text": "Quel est le montant de la dernière taxe foncière ?",
        "themes": ["Charges & Budget", "Administratif & Urbanisme"],
        "category": "Financier & Négociation",
        "advice_notes": "Demander le dernier avis de taxe foncière officiel."
    },
    {
        "question_text": "Quelle est la raison de la vente et depuis combien de temps le bien est-il sur le marché ?",
        "themes": ["Négociation & Contexte", "Vente & Modalités"],
        "category": "Financier & Négociation",
        "advice_notes": "Déceler le niveau d'urgence ou la marge de négociation du vendeur."
    },
    {
        "question_text": "Quelle est la date souhaitée de libération des lieux par le vendeur ?",
        "themes": ["Négociation & Contexte", "Vente & Modalités"],
        "category": "Financier & Négociation",
        "advice_notes": "Indispensable pour caler le calendrier de signature notaire et le prêt bancaire."
    },
]


def seed_global_questions(db: Session) -> int:
    """
    Initialise le catalogue global transverse de la plateforme avec les questions d'inspection types.
    S'exécute automatiquement au démarrage si la table est vide.
    """
    existing_texts = {gq.question_text.strip().lower() for gq in db.query(GlobalQuestion).all()}
    added_count = 0

    for item in DEFAULT_INSPECTION_PACK:
        q_text = item["question_text"].strip()
        if q_text.lower() in existing_texts:
            continue

        gq = GlobalQuestion(
            question_text=q_text,
            themes_json=json.dumps(item["themes"], ensure_ascii=False),
            category=item.get("category", "Inspection technique"),
            advice_notes=item.get("advice_notes", None),
            created_by="Système",
            usage_count=1
        )
        db.add(gq)
        existing_texts.add(q_text.lower())
        added_count += 1

    if added_count > 0:
        db.commit()

    return added_count


def record_in_global_catalog(
    db: Session,
    question_text: str,
    themes: List[str],
    category: str = "Inspection technique",
    advice_notes: str = None,
    created_by: str = None
) -> Optional[GlobalQuestion]:
    """
    Enregistre ou met à jour une question dans le catalogue global de la plateforme.
    Incrémente le compteur d'utilisation si la question existe déjà.
    """
    clean_text = question_text.strip()
    if not clean_text:
        return None

    gq = db.query(GlobalQuestion).filter(
        GlobalQuestion.question_text.ilike(clean_text)
    ).first()

    if gq:
        gq.usage_count = (gq.usage_count or 0) + 1
        # Merge themes
        try:
            curr_themes = json.loads(gq.themes_json) if gq.themes_json else []
        except Exception:
            curr_themes = []
        
        merged = list(dict.fromkeys(curr_themes + themes))
        gq.themes_json = json.dumps(merged, ensure_ascii=False)
    else:
        gq = GlobalQuestion(
            question_text=clean_text,
            themes_json=json.dumps(themes or ["Général"], ensure_ascii=False),
            category=category or "Inspection technique",
            advice_notes=advice_notes,
            created_by=created_by,
            usage_count=1
        )
        db.add(gq)

    try:
        db.commit()
    except Exception:
        db.rollback()

    return gq


def import_default_pack_for_visit(db: Session, visit: Visit, created_by: str = "Système") -> int:
    """
    Imports default inspection questions into a visit/listing if not already present.
    Ensures questions are linked to the listing for cross-visit continuity.
    Returns the number of created questions.
    """
    existing_qs = db.query(VisitQuestion).filter(
        (VisitQuestion.listing_id == visit.listing_id) | (VisitQuestion.visit_id == visit.id)
    ).all()

    existing_texts = {q.question_text.strip().lower() for q in existing_qs}
    created_count = 0
    current_max_order = max([q.order_index for q in existing_qs], default=-1)

    for item in DEFAULT_INSPECTION_PACK:
        q_text = item["question_text"].strip()
        if q_text.lower() in existing_texts:
            continue

        current_max_order += 1
        vq = VisitQuestion(
            listing_id=visit.listing_id,
            visit_id=visit.id,
            question_text=q_text,
            status="en_attente",
            themes_json=json.dumps(item["themes"], ensure_ascii=False),
            created_by=created_by,
            order_index=current_max_order,
        )
        db.add(vq)
        existing_texts.add(q_text.lower())
        created_count += 1

        # Also register in platform global catalog
        record_in_global_catalog(
            db=db,
            question_text=q_text,
            themes=item["themes"],
            category=item.get("category", "Inspection technique"),
            advice_notes=item.get("advice_notes"),
            created_by=created_by
        )

    if created_count > 0:
        db.commit()

    return created_count
