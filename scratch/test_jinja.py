
import enum
from jinja2 import Template

class ListingStatus(str, enum.Enum):
    NEW = "nouvelle"
    ACTIVE = "active"
    DISAPPEARED = "disparue"

template = Template('data-status="{{ status }}"')
print(template.render(status=ListingStatus.NEW))
