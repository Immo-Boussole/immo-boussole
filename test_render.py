from jinja2 import Environment, FileSystemLoader
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import sys
sys.path.append('.')
from app.models import Listing, Review

engine = create_engine('sqlite:///./immo_boussole.db')
Session = sessionmaker(bind=engine)
session = Session()
listing = session.query(Listing).filter_by(id=164).first()
if not listing:
    print('Listing not found')
    sys.exit(0)

env = Environment(loader=FileSystemLoader('templates'))
def fake_t(request, key, default=''):
    return default or key
env.globals['t'] = fake_t
env.globals['app_version'] = '1.0'
try:
    template = env.get_template('listing_detail.html')
    output = template.render(
        request={'session': {'role': 'user'}, 'url': {'path': '/listings/164'}},
        listing=listing,
        photos=[],
        reviews=[],
        reviews_by_reviewer={},
        duplicate_original=None,
        internal_duplicates=[],
        app_version='1.0',
        city_rule=None,
        station1_rule=None,
        station2_rule=None,
        station_rules={}
    )
    print('Render OK')
except Exception as e:
    import traceback
    traceback.print_exc()
