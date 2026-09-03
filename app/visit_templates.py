"""
Module de modèles de questions d'inspection et FAQ pour les visites et contre-visites.
Propose des packs de questions types multi-thématiques couvrant l'ensemble des aspects
d'un bien immobilier (Structure, Toiture, DPE/Chauffage, Copro, Extérieurs, etc.).
"""
import json
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from app.models import Visit, VisitQuestion


DEFAULT_INSPECTION_PACK: List[Dict[str, Any]] = [
    # ─── 1. Bâtiment, Structure & Gros Œuvre ──────────────────────────────
    {
        "question_text": "Quel est l'état général de la toiture, de la charpente et de la couverture ? Des infiltrations ou réparations récentes ont-elles eu lieu ?",
        "themes": ["Toiture & Charpente", "Structure & Gros œuvre", "Entretien à prévoir"],
    },
    {
        "question_text": "Y a-t-il des fissures traversantes, des traces d'humidité ou des remontées capillaires sur les murs porteurs et en sous-sol/cave ?",
        "themes": ["Structure & Gros œuvre", "Humidité & Assainissement", "Sous-sol & Cave"],
    },
    {
        "question_text": "Quel est l'âge et l'état du ravalement de façade ? Des travaux d'isolation par l'extérieur (ITE) sont-ils prévus ou votés ?",
        "themes": ["Façade & Extérieur", "Structure & Gros œuvre", "Copropriété", "Travaux & Budget"],
    },

    # ─── 2. Énergie, Chauffage, DPE & Isolation ──────────────────────────
    {
        "question_text": "Quel est le mode et le coût annuel réel de chauffage (chaudière, PAC, radiateurs) ? De quand date la dernière révision / installation ?",
        "themes": ["Chauffage & Énergie", "DPE & Isolation", "Charges & Budget", "Entretien à prévoir"],
    },
    {
        "question_text": "Quelle est la nature du vitrage (simple, double, phonique/thermique) et l'état des menuiseries/volets ?",
        "themes": ["DPE & Isolation", "Menuiseries & Fenêtres", "Travaux & Budget"],
    },
    {
        "question_text": "Comment fonctionne la ventilation (VMC simple flux, double flux, naturelle) ? Est-elle opérationnelle dans les pièces humides ?",
        "themes": ["DPE & Isolation", "Humidité & Assainissement", "Plomberie & Sanitaires"],
    },

    # ─── 3. Réseaux, Électricité & Plomberie ──────────────────────────────
    {
        "question_text": "Le tableau électrique est-il aux normes (différentiels 30mA, disjoncteurs, présence de terre dans toutes les pièces) ?",
        "themes": ["Électricité & Sécurité", "Diagnostics & Conformité"],
    },
    {
        "question_text": "Quel est l'état de la plomberie générale (matériaux plomb/cuivre/multicouche, pression, chauffe-eau récent) ?",
        "themes": ["Plomberie & Sanitaires", "Entretien à prévoir"],
    },
    {
        "question_text": "L'assainissement est-il collectif (tout-à-l'égout raccordé et conforme) ou individuel (fosse septique aux normes SPANC) ?",
        "themes": ["Humidité & Assainissement", "Diagnostics & Conformité", "Administratif & Urbanisme"],
    },

    # ─── 4. Extérieur, Jardin, Piscine & Dépendances ──────────────────────
    {
        "question_text": "Quels sont les équipements extérieurs et l'entretien régulier à prévoir (arrosage, clôtures, portail automatique, dépendances) ?",
        "themes": ["Extérieur", "Jardin", "Entretien à prévoir"],
    },
    {
        "question_text": "Quel est l'état de la piscine et de ses équipements (liner/coque, pompe, filtration, système de sécurité conforme) ?",
        "themes": ["Piscine", "Extérieur", "Jardin", "Entretien à prévoir", "Charges & Budget"],
    },
    {
        "question_text": "Existe-t-il des servitudes de passage, de vue ou de réseaux traversant le terrain/jardin ?",
        "themes": ["Extérieur", "Jardin", "Administratif & Urbanisme", "Juridique & Servitudes"],
    },

    # ─── 5. Copropriété, Charges & Assemblées Générales ──────────────────
    {
        "question_text": "Quel est le montant exact des charges courantes mensuelles et ce qu'elles comprennent (eau, chauffage, ascenseur, gardien) ?",
        "themes": ["Copropriété", "Charges & Budget"],
    },
    {
        "question_text": "Y a-t-il des travaux récemment votés ou prévus lors des prochaines AG (ravalement, toiture, ascenseur, chaufferie) ?",
        "themes": ["Copropriété", "Travaux & Budget"],
    },
    {
        "question_text": "Y a-t-il des impayés significatifs ou des procédures en cours au sein de la copropriété / syndic ?",
        "themes": ["Copropriété", "Juridique & Servitudes"],
    },

    # ─── 6. Environnement, Voisinage & Vie Quotidienne ───────────────────
    {
        "question_text": "Quel est le niveau sonore aux heures de pointe, en soirée et le week-end (bruit de rue, mitoyenneté, chemin de fer, commerces) ?",
        "themes": ["Voisinage & Bruit", "Environnement & Quartier"],
    },
    {
        "question_text": "Quelle est l'exposition réelle du salon et des espaces de vie tout au long de la journée / luminosité ?",
        "themes": ["Luminosité & Orientation", "Environnement & Quartier"],
    },
    {
        "question_text": "Où se situent les commodités immédiates (transports, écoles, commerces, stationnement visiteurs) ?",
        "themes": ["Environnement & Quartier", "Vie pratique"],
    },

    # ─── 7. Taxes, Prix & Négociation ────────────────────────────────────
    {
        "question_text": "Quel est le montant de la dernière taxe foncière ?",
        "themes": ["Charges & Budget", "Administratif & Urbanisme"],
    },
    {
        "question_text": "Quelle est la raison de la vente et depuis combien de temps le bien est-il sur le marché ?",
        "themes": ["Négociation & Contexte", "Vente & Modalités"],
    },
    {
        "question_text": "Quelle est la date souhaitée de libération des lieux par le vendeur ?",
        "themes": ["Négociation & Contexte", "Vente & Modalités"],
    },
]


def import_default_pack_for_visit(db: Session, visit: Visit, created_by: str = "Système") -> int:
    """
    Imports default inspection questions into a visit if not already present.
    Returns the number of created questions.
    """
    existing_texts = {q.question_text.strip().lower() for q in visit.questions}
    created_count = 0
    current_max_order = max([q.order_index for q in visit.questions], default=-1)

    for item in DEFAULT_INSPECTION_PACK:
        q_text = item["question_text"].strip()
        if q_text.lower() in existing_texts:
            continue

        current_max_order += 1
        vq = VisitQuestion(
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

    if created_count > 0:
        db.commit()

    return created_count
