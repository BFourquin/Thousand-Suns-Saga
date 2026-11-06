

from game.models import Technology
from database.schemas import on_server


# shortcut: every civilisation stays at the level of its start (the one of district_territory), until researching exists
CIVILISATION_TECH_LEVEL = 9


tech_types = ['general theory',
              'social', 'biology', 'electronic', 'energy'
              'spaceship', 'weaponry', 'military doctrine',
              'planetology', 'industry', '']


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
