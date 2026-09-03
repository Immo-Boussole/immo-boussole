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
        "advice_notes": "Vérifier la date de réfection de toiture et inspecter les combles.",
        "language": "fr"
    },
    {
        "question_text": "Y a-t-il des fissures traversantes, des traces d'humidité ou des remontées capillaires sur les murs porteurs et en sous-sol/cave ?",
        "themes": ["Structure & Gros œuvre", "Humidité & Assainissement", "Sous-sol & Cave"],
        "category": "Structure & Gros œuvre",
        "advice_notes": "Rechercher des traces de salpêtre ou moisissure en cave et soubassements.",
        "language": "fr"
    },
    {
        "question_text": "Quel est l'âge et l'état du ravalement de façade ? Des travaux d'isolation par l'extérieur (ITE) sont-ils prévus ou votés ?",
        "themes": ["Façade & Extérieur", "Structure & Gros œuvre", "Copropriété", "Travaux & Budget"],
        "category": "Structure & Gros œuvre",
        "advice_notes": "Consulter les 3 derniers procès-verbaux d'assemblée générale.",
        "language": "fr"
    },

    # ─── 2. Énergie, Chauffage, DPE & Isolation ──────────────────────────
    {
        "question_text": "Quel est le mode et le coût annuel réel de chauffage (chaudière, PAC, radiateurs) ? De quand date la dernière révision / installation ?",
        "themes": ["Chauffage & Énergie", "DPE & Isolation", "Charges & Budget", "Entretien à prévoir"],
        "category": "Énergie & Chauffage",
        "advice_notes": "Demander les factures réelles des 2 dernières années et l'attestation d'entretien annuel.",
        "language": "fr"
    },
    {
        "question_text": "Quelle est la nature du vitrage (simple, double, phonique/thermique) et l'état des menuiseries/volets ?",
        "themes": ["DPE & Isolation", "Menuiseries & Fenêtres", "Travaux & Budget"],
        "category": "Énergie & Chauffage",
        "advice_notes": "Inspecter l'étanchéité à l'air des ouvrants.",
        "language": "fr"
    },
    {
        "question_text": "Comment fonctionne la ventilation (VMC simple flux, double flux, naturelle) ? Est-elle opérationnelle dans les pièces humides ?",
        "themes": ["DPE & Isolation", "Humidité & Assainissement", "Plomberie & Sanitaires"],
        "category": "Énergie & Chauffage",
        "advice_notes": "Vérifier l'aspiration des bouches d'extraction avec une feuille de papier.",
        "language": "fr"
    },

    # ─── 3. Réseaux, Électricité & Plomberie ──────────────────────────────
    {
        "question_text": "Le tableau électrique est-il aux normes (différentiels 30mA, disjoncteurs, présence de terre dans toutes les pièces) ?",
        "themes": ["Électricité & Sécurité", "Diagnostics & Conformité"],
        "category": "Réseaux & Électricité",
        "advice_notes": "Consulter le diagnostic électrique (anomalies B3, B4 ou absence de terre).",
        "language": "fr"
    },
    {
        "question_text": "Quel est l'état de la plomberie générale (matériaux plomb/cuivre/multicouche, pression, chauffe-eau récent) ?",
        "themes": ["Plomberie & Sanitaires", "Entretien à prévoir"],
        "category": "Réseaux & Plomberie",
        "advice_notes": "Vérifier la pression aux robinets et l'âge du cumulus.",
        "language": "fr"
    },
    {
        "question_text": "L'assainissement est-il collectif (tout-à-l'égout raccordé et conforme) ou individuel (fosse septique aux normes SPANC) ?",
        "themes": ["Humidité & Assainissement", "Diagnostics & Conformité", "Administratif & Urbanisme"],
        "category": "Réseaux & Assainissement",
        "advice_notes": "Demander le certificat de conformité d'assainissement de la commune ou du SPANC.",
        "language": "fr"
    },

    # ─── 4. Extérieur, Jardin, Piscine & Dépendances ──────────────────────
    {
        "question_text": "Quels sont les équipements extérieurs et l'entretien régulier à prévoir (arrosage, clôtures, portail automatique, dépendances) ?",
        "themes": ["Extérieur", "Jardin", "Entretien à prévoir"],
        "category": "Extérieur & Jardin",
        "advice_notes": "Vérifier la mitoyenneté des clôtures et haies.",
        "language": "fr"
    },
    {
        "question_text": "Quel est l'état de la piscine et de ses équipements (liner/coque, pompe, filtration, système de sécurité conforme) ?",
        "themes": ["Piscine", "Extérieur", "Jardin", "Entretien à prévoir", "Charges & Budget"],
        "category": "Extérieur & Jardin",
        "advice_notes": "Demander la date du liner et l'attestation de conformité du système de sécurité (alarme, bâche ou barrière).",
        "language": "fr"
    },
    {
        "question_text": "Existe-t-il des servitudes de passage, de vue ou de réseaux traversant le terrain/jardin ?",
        "themes": ["Extérieur", "Jardin", "Administratif & Urbanisme", "Juridique & Servitudes"],
        "category": "Juridique & Servitudes",
        "advice_notes": "Consulter le titre de propriété antérieur et le plan cadastral.",
        "language": "fr"
    },

    # ─── 5. Copropriété, Charges & Assemblées Générales ──────────────────
    {
        "question_text": "Quel est le montant exact des charges courantes mensuelles et ce qu'elles comprennent (eau, chauffage, ascenseur, gardien) ?",
        "themes": ["Copropriété", "Charges & Budget"],
        "category": "Copropriété",
        "advice_notes": "Vérifier les 4 derniers appels de fonds.",
        "language": "fr"
    },
    {
        "question_text": "Y a-t-il des travaux récemment votés ou prévus lors des prochaines AG (ravalement, toiture, ascenseur, chaufferie) ?",
        "themes": ["Copropriété", "Travaux & Budget"],
        "category": "Copropriété",
        "advice_notes": "Analyser les PV des 3 dernières AG et le carnet d'entretien.",
        "language": "fr"
    },
    {
        "question_text": "Y a-t-il des impayés significatifs ou des procédures en cours au sein de la copropriété / syndic ?",
        "themes": ["Copropriété", "Juridique & Servitudes"],
        "category": "Copropriété",
        "advice_notes": "Consulter le pré-état daté fourni par le vendeur.",
        "language": "fr"
    },

    # ─── 6. Environnement, Voisinage & Vie Quotidienne ───────────────────
    {
        "question_text": "Quel est le niveau sonore aux heures de pointe, en soirée et le week-end (bruit de rue, mitoyenneté, chemin de fer, commerces) ?",
        "themes": ["Voisinage & Bruit", "Environnement & Quartier"],
        "category": "Environnement",
        "advice_notes": "Effectuer une contre-visite à une heure de pointe et en soirée.",
        "language": "fr"
    },
    {
        "question_text": "Quelle est l'exposition réelle du salon et des espaces de vie tout au long de la journée / luminosité ?",
        "themes": ["Luminosité & Orientation", "Environnement & Quartier"],
        "category": "Environnement",
        "advice_notes": "Vérifier la boussole et le simulateur solaire Immo-Boussole.",
        "language": "fr"
    },
    {
        "question_text": "Où se situent les commodités immédiates (transports, écoles, commerces, stationnement visiteurs) ?",
        "themes": ["Environnement & Quartier", "Vie pratique"],
        "category": "Environnement",
        "advice_notes": "Tester le trajet à pied jusqu'aux transports et commerces.",
        "language": "fr"
    },

    # ─── 7. Taxes, Prix & Négociation ────────────────────────────────────
    {
        "question_text": "Quel est le montant de la dernière taxe foncière ?",
        "themes": ["Charges & Budget", "Administratif & Urbanisme"],
        "category": "Financier & Négociation",
        "advice_notes": "Demander le dernier avis de taxe foncière officiel.",
        "language": "fr"
    },
    {
        "question_text": "Quelle est la raison de la vente et depuis combien de temps le bien est-il sur le marché ?",
        "themes": ["Négociation & Contexte", "Vente & Modalités"],
        "category": "Financier & Négociation",
        "advice_notes": "Déceler le niveau d'urgence ou la marge de négociation du vendeur.",
        "language": "fr"
    },
    {
        "question_text": "Quelle est la date souhaitée de libération des lieux par le vendeur ?",
        "themes": ["Négociation & Contexte", "Vente & Modalités"],
        "category": "Financier & Négociation",
        "advice_notes": "Indispensable pour caler le calendrier de signature notaire et le prêt bancaire.",
        "language": "fr"
    },
]


DEFAULT_INSPECTION_PACK_EN: List[Dict[str, Any]] = [
    # ─── 1. Building, Structure & Shell ──────────────────────────────────
    {
        "question_text": "What is the overall condition of the roof, timber framework, and covering? Have there been any recent leaks or repairs?",
        "themes": ["Roof & Framework", "Structure & Building Shell", "Maintenance & Repairs"],
        "category": "Structure & Shell",
        "advice_notes": "Check the last roof renovation date and inspect the attic.",
        "language": "en"
    },
    {
        "question_text": "Are there any through-cracks, signs of dampness, or rising damp on load-bearing walls and in the basement/cellar?",
        "themes": ["Structure & Building Shell", "Dampness & Drainage", "Basement & Cellar"],
        "category": "Structure & Shell",
        "advice_notes": "Look for saltpetre, flaking plaster, or mould in the cellar and foundation walls.",
        "language": "en"
    },
    {
        "question_text": "What is the age and condition of the exterior facade? Are any external wall insulation (EWI) works planned or approved?",
        "themes": ["Facade & Exterior", "Structure & Building Shell", "HOA / Copro", "Renovation & Budget"],
        "category": "Structure & Shell",
        "advice_notes": "Review the minutes of the last 3 general meetings.",
        "language": "en"
    },

    # ─── 2. Energy, Heating, EPC & Insulation ────────────────────────────
    {
        "question_text": "What is the heating system type and actual annual energy cost (boiler, heat pump, radiators)? When was it last serviced or installed?",
        "themes": ["Heating & Energy", "EPC & Insulation", "Utility Bills & Budget", "Maintenance & Repairs"],
        "category": "Energy & Heating",
        "advice_notes": "Request actual utility bills for the past 2 years and annual maintenance certificate.",
        "language": "en"
    },
    {
        "question_text": "What type of glazing is installed (single, double, acoustic/thermal) and what is the condition of window frames/shutters?",
        "themes": ["EPC & Insulation", "Windows & Joinery", "Renovation & Budget"],
        "category": "Energy & Heating",
        "advice_notes": "Check air tightness around window sashes and doors.",
        "language": "en"
    },
    {
        "question_text": "How does the ventilation work (mechanical extract, double flux, natural)? Is it fully working in wet rooms (kitchen, bathrooms)?",
        "themes": ["EPC & Insulation", "Dampness & Drainage", "Plumbing & Bathrooms"],
        "category": "Energy & Heating",
        "advice_notes": "Test air extraction grills with a piece of paper.",
        "language": "en"
    },

    # ─── 3. Electrical, Utilities & Plumbing ──────────────────────────────
    {
        "question_text": "Is the electrical distribution board compliant with modern standards (30mA RCDs, circuit breakers, earthing in all rooms)?",
        "themes": ["Electrical & Safety", "Diagnostics & Compliance"],
        "category": "Utilities & Electrical",
        "advice_notes": "Review the electrical inspection report for safety anomalies.",
        "language": "en"
    },
    {
        "question_text": "What is the general condition of plumbing (copper, multilayer or lead pipes, water pressure, recent boiler/cylinder)?",
        "themes": ["Plumbing & Bathrooms", "Maintenance & Repairs"],
        "category": "Utilities & Plumbing",
        "advice_notes": "Check water pressure at taps and water heater manufacturing date.",
        "language": "en"
    },
    {
        "question_text": "Is drainage connected to mains sewer (compliant connection) or a private septic tank system (compliant with local regulations)?",
        "themes": ["Dampness & Drainage", "Diagnostics & Compliance", "Legal & Permits"],
        "category": "Utilities & Drainage",
        "advice_notes": "Request the sanitation/drainage compliance certificate.",
        "language": "en"
    },

    # ─── 4. Exterior, Garden, Pool & Outbuildings ────────────────────────
    {
        "question_text": "What exterior equipment is included and what regular maintenance is required (irrigation, fences, motorized gate, outbuildings)?",
        "themes": ["Exterior", "Garden", "Maintenance & Repairs"],
        "category": "Exterior & Garden",
        "advice_notes": "Verify boundary ownership of fences and hedges.",
        "language": "en"
    },
    {
        "question_text": "What is the condition of the swimming pool and its plant equipment (liner/shell, pump, filtration, compliant safety barrier/alarm)?",
        "themes": ["Swimming Pool", "Exterior", "Garden", "Maintenance & Repairs", "Utility Bills & Budget"],
        "category": "Exterior & Garden",
        "advice_notes": "Ask for liner replacement date and pool safety compliance certificate.",
        "language": "en"
    },
    {
        "question_text": "Are there any rights of way, easements, or utility lines crossing the plot/garden?",
        "themes": ["Exterior", "Garden", "Legal & Permits", "Easements & Rights"],
        "category": "Legal & Easements",
        "advice_notes": "Examine title deeds and cadastral survey plans.",
        "language": "en"
    },

    # ─── 5. Co-ownership / HOA, Service Charges & AGM ────────────────────
    {
        "question_text": "What are the exact monthly service charges and what do they cover (water, communal heating, elevator, caretaker)?",
        "themes": ["HOA / Copro", "Utility Bills & Budget"],
        "category": "Co-ownership & HOA",
        "advice_notes": "Review the last 4 quarterly service charge statements.",
        "language": "en"
    },
    {
        "question_text": "Have major capital works been voted or planned for upcoming AGMs (facade rendering, roof, lift, heating plant)?",
        "themes": ["HOA / Copro", "Renovation & Budget"],
        "category": "Co-ownership & HOA",
        "advice_notes": "Analyze minutes of the last 3 general meetings and building maintenance logbook.",
        "language": "en"
    },
    {
        "question_text": "Are there any substantial unpaid service charges or ongoing litigation within the co-ownership / building management?",
        "themes": ["HOA / Copro", "Legal & Easements"],
        "category": "Co-ownership & HOA",
        "advice_notes": "Check the pre-contractual questionnaire provided by the seller.",
        "language": "en"
    },

    # ─── 6. Environment, Neighborhood & Daily Living ─────────────────────
    {
        "question_text": "What is the noise level during rush hours, evenings, and weekends (street noise, party walls, railway, commercial shops)?",
        "themes": ["Noise & Neighbors", "Neighborhood & Surroundings"],
        "category": "Environment & Location",
        "advice_notes": "Conduct a second visit during peak traffic and evening hours.",
        "language": "en"
    },
    {
        "question_text": "What is the actual sun exposure of the living room and primary areas throughout the day / natural light?",
        "themes": ["Sunlight & Orientation", "Neighborhood & Surroundings"],
        "category": "Environment & Location",
        "advice_notes": "Check orientation with compass and solar tracker tool in Immo-Boussole.",
        "language": "en"
    },
    {
        "question_text": "Where are nearby amenities located (public transit, schools, grocery stores, visitor parking)?",
        "themes": ["Neighborhood & Surroundings", "Daily Life & Transit"],
        "category": "Environment & Location",
        "advice_notes": "Walk the route from the property to local transit and shops.",
        "language": "en"
    },

    # ─── 7. Taxes, Price & Negotiation ───────────────────────────────────
    {
        "question_text": "What is the exact annual property tax amount (Taxe Foncière / local rates)?",
        "themes": ["Utility Bills & Budget", "Legal & Permits"],
        "category": "Financial & Negotiation",
        "advice_notes": "Ask for the latest official property tax bill.",
        "language": "en"
    },
    {
        "question_text": "What is the reason for selling and how long has the property been on the market?",
        "themes": ["Negotiation & Context", "Sale Conditions"],
        "category": "Financial & Negotiation",
        "advice_notes": "Gauge the seller's urgency level and negotiation flexibility.",
        "language": "en"
    },
    {
        "question_text": "What is the seller's preferred timeline for vacating the property / completion date?",
        "themes": ["Negotiation & Context", "Sale Conditions"],
        "category": "Financial & Negotiation",
        "advice_notes": "Crucial to synchronize mortgage approval and final completion notary schedule.",
        "language": "en"
    },
]


def seed_global_questions(db: Session) -> int:
    """
    Initialise le catalogue global transverse de la plateforme avec les questions d'inspection types en français et en anglais.
    S'exécute automatiquement au démarrage si la table est vide ou pour compléter les langues manquantes.
    """
    existing_items = {(gq.question_text.strip().lower(), (gq.language or "fr").lower()) for gq in db.query(GlobalQuestion).all()}
    added_count = 0

    all_packs = DEFAULT_INSPECTION_PACK + DEFAULT_INSPECTION_PACK_EN

    for item in all_packs:
        q_text = item["question_text"].strip()
        q_lang = (item.get("language") or "fr").lower()
        if (q_text.lower(), q_lang) in existing_items:
            continue

        gq = GlobalQuestion(
            question_text=q_text,
            themes_json=json.dumps(item["themes"], ensure_ascii=False),
            category=item.get("category", "Inspection technique"),
            advice_notes=item.get("advice_notes", None),
            language=q_lang,
            created_by="Système",
            usage_count=1
        )
        db.add(gq)
        existing_items.add((q_text.lower(), q_lang))
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
    language: str = "fr",
    created_by: str = None
) -> Optional[GlobalQuestion]:
    """
    Enregistre ou met à jour une question dans le catalogue global de la plateforme avec sa langue.
    Incrémente le compteur d'utilisation si la question existe déjà dans cette langue.
    """
    clean_text = question_text.strip()
    if not clean_text:
        return None

    clean_lang = (language or "fr").strip().lower()

    gq = db.query(GlobalQuestion).filter(
        GlobalQuestion.question_text.ilike(clean_text),
        GlobalQuestion.language == clean_lang
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
            language=clean_lang,
            created_by=created_by,
            usage_count=1
        )
        db.add(gq)

    try:
        db.commit()
    except Exception:
        db.rollback()

    return gq


def import_default_pack_for_visit(db: Session, visit: Visit, language: str = "fr", created_by: str = "Système") -> int:
    """
    Imports default inspection questions into a visit/listing in the specified language (fr or en).
    Ensures questions are linked to the listing for cross-visit continuity.
    Returns the number of created questions.
    """
    existing_qs = db.query(VisitQuestion).filter(
        (VisitQuestion.listing_id == visit.listing_id) | (VisitQuestion.visit_id == visit.id)
    ).all()

    existing_texts = {q.question_text.strip().lower() for q in existing_qs}
    created_count = 0
    current_max_order = max([q.order_index for q in existing_qs], default=-1)

    clean_lang = (language or "fr").strip().lower()
    pack = DEFAULT_INSPECTION_PACK_EN if clean_lang.startswith("en") else DEFAULT_INSPECTION_PACK

    for item in pack:
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
            language=clean_lang,
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
            language=clean_lang,
            created_by=created_by
        )

    if created_count > 0:
        db.commit()

    return created_count
