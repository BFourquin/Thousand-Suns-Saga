

from database.db_connect import databases


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


def get_all_technologies(server_name):
    client = databases['TSS_' + server_name]
    db = client['technologies']

    return db.find({})
