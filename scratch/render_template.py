from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader
import json

try:
    env = Environment(loader=FileSystemLoader('c:/tools/GitHub/Immo-Boussole/immo-boussole/templates'))
    # Dummy mock for request to handle t(request, ...) function
    class MockRequest:
        def __init__(self):
            self.session = {'lang': 'fr'}
    
    def mock_t(req, key, default=None):
        return default or key

    env.globals['t'] = mock_t

    template = env.get_template('listing_detail.html')

    dummy_georisques = {
      "risquesNaturels": {
        "inondation": {
          "present": True,
          "libelle": "Inondation",
          "libelleStatutCommune": "Risque Existant",
          "libelleStatutAdresse": None,
          "specifique": None
        }
      },
      "risquesTechnologiques": {}
    }

    class MockAppVersion:
        def __str__(self): return "1.0"

    context = {
        "request": MockRequest(),
        "listing": type('Listing', (), {'title': 'Test', 'description_text': 'test', 'photos_local': '[]', 'id': 1})(),
        "georisques": dummy_georisques,
        "app_version": MockAppVersion()
    }
    output = template.render(context)
    print("Template rendered successfully.")
except Exception as e:
    import traceback
    traceback.print_exc()
