import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import is_valid_listing_url, is_search_page_title


class TestSearchPageValidation(unittest.TestCase):

    def test_valid_listing_urls(self):
        """Test that single listing page URLs are correctly validated."""
        valid_urls = [
            # Orpi
            "https://www.orpi.com/annonce-vente-maison-t4-gradignan-33170-orpi-0129-3079/",
            "https://www.orpi.com/annonce-location-appartement-t2-bordeaux-33000-orpi-0128-4052/",
            # Leboncoin
            "https://www.leboncoin.fr/ad/ventes_immobilieres/2347289347",
            "https://www.leboncoin.fr/ventes_immobilieres/2347289347.htm",
            # SeLoger
            "https://www.seloger.com/annonces/achat/maison/gradignan-33/213566141.htm",
            "https://www.seloger.com/annonce/achat/auvergne-rhone-alpes/isere-38/saint-clair-du-rhone-38370/26H129BK5GHE?serp_view=list&search=classifiedBusiness%3DProfessional%26distributionTypes%3DBuy%2CBuy_Auction%26estateTypes%3DHouse%26locations%3DAD08FR15167%26projectTypes%3DProjected%2CResale#ln=classified_search_results&m=classified_search_results_classified_classified_detail_L",
            # Le Figaro
            "https://immobilier.lefigaro.fr/annonces/annonce-166299101.html",
            # LogicImmo
            "https://www.logic-immo.com/detail-vente-appartement-lyon-3-69003-logic-123456.html",
            # Bien'Ici
            "https://www.bienici.com/annonce/vente/lyon/appartement/23456",
            # IAD France
            "https://www.iadfrance.fr/annonce/vente/appartement/lyon-69003/12345",
            # Notaires
            "https://immobilier.notaires.fr/annonce/vente/maison/gradignan-33/123456",
            # Vinci
            "https://www.vinci-immobilier.com/achat-immobilier-neuf/appartement-neuf/bordeaux/le-clos-des-terres/12345",
            # Immobilier France
            "https://www.immobilier-france.fr/annonce/vente-maison-12345",
            "https://www.immobilier-france.fr/detail/vente-maison-12345",
        ]
        
        for url in valid_urls:
            is_valid, err_msg = is_valid_listing_url(url)
            self.assertTrue(is_valid, f"Expected valid URL to be accepted: {url}. Error: {err_msg}")

    def test_invalid_search_or_landing_urls(self):
        """Test that search, results, or landing pages are correctly rejected."""
        invalid_urls = [
            # Orpi
            "https://www.orpi.com/recherche/achat/maison/paris/",
            "https://www.orpi.com/recherche/location/appartement/",
            # Leboncoin
            "https://www.leboncoin.fr/recherche?category=9&locations=d_33",
            # SeLoger
            "https://www.seloger.com/resultats/achat/maison/gradignan-33/",
            "https://www.seloger.com/carte/achat/maison/gradignan-33/",
            # Le Figaro
            "https://immobilier.lefigaro.fr/annonces/immobilier-achat-maison-gradignan.html",
            # LogicImmo
            "https://www.logic-immo.com/recherche-immobilier/vente/maisons/lyon/",
            # Bien'Ici
            "https://www.bienici.com/recherche/achat/paris/maison",
            # IAD France
            "https://www.iadfrance.fr/recherche/vente/maison/lyon",
            # Notaires
            "https://immobilier.notaires.fr/recherche/vente/maison",
            # Vinci
            "https://www.vinci-immobilier.com/carte-des-programmes",
            # Immobilier France
            "https://www.immobilier-france.fr/recherche/vente/maison",
        ]
        
        for url in invalid_urls:
            is_valid, err_msg = is_valid_listing_url(url)
            self.assertFalse(is_valid, f"Expected search URL to be rejected: {url}")
            self.assertIsNotNone(err_msg)

    def test_search_page_titles(self):
        """Test page title validation that detects search results/landing pages."""
        # Titles that should be rejected as search pages
        search_titles = [
            "Maisons à Vendre à Gradignan (33170) 🏡 : Maisons en Vente",
            "Appartements à Vendre à Bordeaux 🏡 : Appartements en Vente",
            "123 Maisons à vendre à Gradignan - SeLoger",
            "Résultats de votre recherche immobilière",
            "Annonces immobilières de particuliers et d'agences",
            "Dernières annonces de vente à Paris",
            "Toutes les annonces immobilières de location",
            "Terrains à vendre à Lyon",
            "Locaux à louer à Marseille",
        ]
        for title in search_titles:
            self.assertTrue(is_search_page_title(title), f"Expected search page title to be detected: {title}")

        # Titles that should be accepted as single listings (nominal case)
        listing_titles = [
            "Maison à vendre à Bordeaux",
            "Appartement 3 pièces à louer à Lyon (69003)",
            "Terrain de 500m² à vendre à Gradignan",
            "Local commercial à louer de 150m²",
            "Annonce Le Figaro",
            "Maison 4 pièces à vendre Gradignan (33170) - 350000 €",
        ]
        for title in listing_titles:
            self.assertFalse(is_search_page_title(title), f"Expected single listing title to be accepted: {title}")


if __name__ == "__main__":
    unittest.main()
