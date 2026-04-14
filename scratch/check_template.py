from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader

try:
    env = Environment(loader=FileSystemLoader('c:/tools/GitHub/Immo-Boussole/immo-boussole/templates'))
    template = env.get_template('listing_detail.html')
    print("Template parsed successfully. No Jinja2 syntax errors found.")
except Exception as e:
    print(f"Error parsing template: {e}")
