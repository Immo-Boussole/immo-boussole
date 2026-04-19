from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader

import os
import sys

try:
    templates_dir = os.path.join(os.path.dirname(__file__), '..', 'templates')
    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template('listing_detail.html')
    print("Template parsed successfully. No Jinja2 syntax errors found.")
except Exception as e:
    print(f"Error parsing template: {e}")
    sys.exit(1)
