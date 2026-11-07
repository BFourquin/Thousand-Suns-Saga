

from game.models import Technology
from database.schemas import on_server


# shortcut: every civilisation stays at the level of its start (the one of district_territory), until the levels 1-15 of
# the buildings are linked to the eras 0-5 of the technologies (data/research.py)
CIVILISATION_TECH_LEVEL = 9


def within_tech_level(type_data):
    # For a row of the Excel with the columns tech_available and tech_hidden
    return (type_data.get('tech_available') or 0) <= CIVILISATION_TECH_LEVEL < (type_data.get('tech_hidden') or float('inf'))


def tech(internal_name, name, tech_type, description, tech_level, modifiers, price, difficulty):
    return {'internal_name': None,
            'name': None,
            'tech_type': None,
            'description': None,
            'tech_level': None,
            'difficulty': None,
            'modifiers': None,
            'prices': None,
            'running_event': None,
            'running_event_probability': None,
            'end_event': None,
            'end_event_probability': None,
            }


@on_server
def get_all_technologies(server_name):
    return [technology.as_dict() for technology in Technology.objects.all().order_by('id')]
