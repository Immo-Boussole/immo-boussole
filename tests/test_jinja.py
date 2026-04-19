
import enum
from jinja2 import Template

class ListingStatus(str, enum.Enum):
    NEW = "nouvelle"
    ACTIVE = "active"
    DISAPPEARED = "disparue"

template = Template('data-status="{{ status.value }}"')
output = template.render(status=ListingStatus.NEW)
print(output)
assert output == 'data-status="nouvelle"'
print("Jinja test passed.")
