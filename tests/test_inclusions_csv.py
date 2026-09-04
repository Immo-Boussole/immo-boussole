"""
Unit and integration tests for Furniture & Services (VisitInclusion) CSV import, export, and template.
"""
import io
import time
from datetime import date, datetime
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app, get_db, user_required, login_required
from app.models import Visit, Listing, VisitInclusion, User
from app.database import Base, engine
from app import csv_service


def setup_test_listing_and_visit(db: Session):
    ts = int(time.time() * 1000)
    listing = Listing(
        title=f"Maison Test Inclusions CSV {ts}",
        url=f"https://example.com/test-inclusions-{ts}",
        price=350000,
        address="12 Rue du Mobilier, 75011 Paris",
        city="Paris",
        postal_code="75011",
        to_visit=True
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)

    visit = Visit(
        listing_id=listing.id,
        visit_type="contre_visite",
        scheduled_at=datetime(2026, 10, 15, 14, 30),
        status="programme",
        visitor="Acheteur Test"
    )
    db.add(visit)
    db.commit()
    db.refresh(visit)

    return listing, visit


def test_export_inclusions_to_csv():
    """Tests exporting a list of VisitInclusion to unified CSV."""
    inc_obj = VisitInclusion(
        id=101,
        listing_id=1,
        visit_id=1,
        item_type="objet",
        room="Salon",
        title="Canapé d'angle",
        variation_notes="Tissu gris",
        condition="Très bon état",
        estimated_value=850.0,
        negotiation_status="inclus_prix_negocie",
        notes="Facture 2023"
    )
    inc_srv = VisitInclusion(
        id=102,
        listing_id=1,
        visit_id=1,
        item_type="service",
        title="Contrat Alarme",
        provider_name="Verisure",
        equipment_included="Centrale + 2 badges",
        contract_start_date=date(2023, 1, 1),
        contract_end_date=date(2026, 12, 31),
        initial_cost=150.0,
        monthly_cost=35.0,
        annual_cost=420.0,
        transfer_status="reprise_contrat",
        negotiation_status="inclus_prix_negocie",
        notes="Sans frais de transfert"
    )

    csv_data = csv_service.export_inclusions_to_csv([inc_obj, inc_srv])
    assert csv_data.startswith('\ufeff')
    assert "Canapé d'angle" in csv_data
    assert "Contrat Alarme" in csv_data
    assert "Verisure" in csv_data
    assert "Très bon état" in csv_data
    assert "850.0" in csv_data
    assert ";" in csv_data


def test_generate_inclusions_csv_template():
    """Tests generation of the inclusions CSV template with samples."""
    template_data = csv_service.generate_inclusions_csv_template()
    assert template_data.startswith('\ufeff')
    assert "type" in template_data
    assert "objet" in template_data
    assert "service" in template_data
    assert "Verisure" in template_data


def test_inclusions_csv_api_endpoints_and_import():
    """Tests the full API workflow: template, export, and import with upsert and replace_all."""
    client = TestClient(app)
    db = next(get_db())

    app.dependency_overrides[user_required] = lambda: {"username": "tester", "role": "user"}
    app.dependency_overrides[login_required] = lambda: {"username": "tester", "role": "user"}

    listing, visit = setup_test_listing_and_visit(db)
    visit_id = visit.id
    listing_id = listing.id

    try:
        # 1. Download template
        tpl_resp = client.get("/api/visites/inclusions/csv-template")
        assert tpl_resp.status_code == 200
        assert "text/csv" in tpl_resp.headers.get("content-type", "")
        assert "template_mobilier_services.csv" in tpl_resp.headers.get("content-disposition", "")

        # 2. Import new inclusions via CSV
        csv_payload = (
            "\ufeffid;type;piece;titre;variantes_declinaisons;etat;valeur_estimee_notaire;fournisseur;materiel_inclus;date_debut_contrat;date_fin_contrat;cout_initial;cout_mensuel;cout_annuel;statut_transfert;statut_negociation;notes;photo_url\n"
            ";objet;Chambre;Lit double 160x200;Coffre intégré;Bon état;500.0;;;;;;;;inclus_prix_negocie;Matelas non inclus;\n"
            ";service;;Télésurveillance;;;;Somfy;Centrale + caméra;2024-01-01;2027-01-01;;29.90;358.80;reprise_contrat;en_discussion;Abonnement résiliable;\n"
        )

        files = {
            "file": ("test_import.csv", io.BytesIO(csv_payload.encode("utf-8")), "text/csv")
        }
        data = {"replace_all": "false"}

        import_resp = client.post(f"/api/visites/{visit_id}/inclusions/import-csv", files=files, data=data)
        assert import_resp.status_code == 200
        res_data = import_resp.json()
        assert res_data["status"] == "success"
        assert res_data["created"] == 2
        assert res_data["updated"] == 0

        # Verify DB records
        items = db.query(VisitInclusion).filter(VisitInclusion.listing_id == listing_id).all()
        assert len(items) == 2
        lit = next((i for i in items if i.title == "Lit double 160x200"), None)
        assert lit is not None
        assert lit.room == "Chambre"
        assert lit.estimated_value == 500.0
        assert lit.condition == "Bon état"

        srv = next((i for i in items if i.title == "Télésurveillance"), None)
        assert srv is not None
        assert srv.provider_name == "Somfy"
        assert srv.monthly_cost == 29.90

        # 3. Export CSV
        export_resp = client.get(f"/api/visites/{visit_id}/inclusions/export-csv")
        assert export_resp.status_code == 200
        exported_content = export_resp.content.decode("utf-8-sig")
        assert "Lit double 160x200" in exported_content
        assert "Télésurveillance" in exported_content

        # 4. Update existing item by ID + Add new item
        update_csv = (
            f"id;type;piece;titre;variantes_declinaisons;etat;valeur_estimee_notaire;fournisseur;materiel_inclus;date_debut_contrat;date_fin_contrat;cout_initial;cout_mensuel;cout_annuel;statut_transfert;statut_negociation;notes;photo_url\n"
            f"{lit.id};objet;Chambre Parentale;Lit double 160x200;Coffre intégré;Très bon état;600.0;;;;;;;;inclus_prix_negocie;Matelas inclus;\n"
            f";objet;Cuisine;Réfrigérateur américain;;Neuf;900.0;;;;;;;;inclus_prix_negocie;Garantie 5 ans;\n"
        )
        files_update = {
            "file": ("test_update.csv", io.BytesIO(update_csv.encode("utf-8")), "text/csv")
        }
        update_resp = client.post(f"/api/visites/{visit_id}/inclusions/import-csv", files=files_update, data={"replace_all": "false"})
        assert update_resp.status_code == 200
        up_data = update_resp.json()
        assert up_data["created"] == 1
        assert up_data["updated"] == 1

        db.refresh(lit)
        assert lit.room == "Chambre Parentale"
        assert lit.estimated_value == 600.0
        assert lit.condition == "Très bon état"

        # 5. Test replace_all
        replace_csv = (
            "id;type;piece;titre;variantes_declinaisons;etat;valeur_estimee_notaire;fournisseur;materiel_inclus;date_debut_contrat;date_fin_contrat;cout_initial;cout_mensuel;cout_annuel;statut_transfert;statut_negociation;notes;photo_url\n"
            ";objet;Terrasse;Salon de jardin 6 places;Table + 6 fauteuils;Bon état;300.0;;;;;;;;inclus_prix_negocie;Housse fournie;\n"
        )
        files_rep = {
            "file": ("test_replace.csv", io.BytesIO(replace_csv.encode("utf-8")), "text/csv")
        }
        rep_resp = client.post(f"/api/visites/{visit_id}/inclusions/import-csv", files=files_rep, data={"replace_all": "true"})
        assert rep_resp.status_code == 200
        rep_data = rep_resp.json()
        assert rep_data["created"] == 1

        db.expire_all()
        items_after_rep = db.query(VisitInclusion).filter(VisitInclusion.listing_id == listing_id).all()
        assert len(items_after_rep) == 1
        assert items_after_rep[0].title == "Salon de jardin 6 places"

    finally:
        # Cleanup test data
        app.dependency_overrides.clear()
        db.query(VisitInclusion).filter(VisitInclusion.listing_id == listing_id).delete()
        db.query(Visit).filter(Visit.id == visit_id).delete()
        db.query(Listing).filter(Listing.id == listing_id).delete()
        db.commit()


if __name__ == "__main__":
    test_export_inclusions_to_csv()
    test_generate_inclusions_csv_template()
    test_inclusions_csv_api_endpoints_and_import()
    print("All inclusions CSV tests passed successfully!")
