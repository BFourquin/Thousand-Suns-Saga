import os
import random
from functools import lru_cache

from django.utils.translation import gettext_lazy as _

from game.models import Coordinate
from database.schemas import on_server
from django_tss.settings import BASE_DIR, STATIC_ROOT


TYPE_NAMES = {
    'star': _('Étoile'),
    'telluric': _('Planète tellurique'),
    'jovian': _('Géante gazeuse'),
    'planetoid': _('Planétoïde'),
    'asteroid_belt': _("Ceinture d'astéroïdes"),
    'oort_cloud': _("Nuage d'Oort"),
}

SUBTYPE_NAMES = {
    'native': _('Monde natal'),
    'habitable_poor': _('Habitabilité faible'),
    'habitable_medium': _('Habitabilité moyenne'),
    'O': _('Classe O'),
    'B': _('Classe B'),
    'A': _('Classe A'),
    'F': _('Classe F'),
    'G': _('Classe G'),
    'K': _('Classe K'),
    'M': _('Classe M'),
    'giant': _('Géante'),
    'supergiant': _('Supergéante'),
    'white_dwarf': _('Naine blanche'),
    'wolf_rayet': _('Wolf-Rayet'),
    'nebula': _('Nébuleuse'),
    'neutron': _('Étoile à neutrons'),
    'pulsar': _('Pulsar'),
    'magnetar': _('Magnétar'),
    'black_hole': _('Trou noir'),
    'supernova': _('Supernova'),
}


def add_display_info(coordinate):
    coordinate['image'] = get_coordinate_image(coordinate)
    coordinate['type_name'] = TYPE_NAMES.get(coordinate['type'], coordinate['type'])
    coordinate['subtype_name'] = SUBTYPE_NAMES.get(coordinate['subtype'], '')  # 'standard' deserves no mention
    return coordinate


@lru_cache(maxsize=None)
def images_in_folder(folder):
    path = os.path.join(BASE_DIR, STATIC_ROOT, 'images', 'coordinate', folder)
    if not os.path.isdir(path):
        return []
    return ['images/coordinate/' + folder + '/' + file for file in sorted(os.listdir(path)) if file.endswith('.png')]


def get_coordinate_image(coordinate):
    # shortcut: picked from the seed, always the same for a coordinate. Store it at generation once planets have biomes
    if coordinate['type'] != 'telluric':
        folders = [coordinate['type']]
    elif coordinate['subtype'] == 'standard':
        folders = ['telluric/cold', 'telluric/hot', 'telluric/ice', 'telluric/irradiated']
    else:
        folders = ['telluric/habitable', 'telluric/ocean']

    images = [image for folder in folders for image in images_in_folder(folder)]
    if not images:
        return 'images/placeholder/' + coordinate['type'] + '.png'
    return random.Random(int(coordinate['id'])).choice(images)


@on_server
def get_coordinates_of_system(server, system):
    # All the coordinates of a system in a single query, sorted from the star to the outer orbits
    rows = Coordinate.objects.filter(seed__in=system['system_coordinates'].keys()).order_by('sys_coordinate')
    return [coordinate.as_dict() for coordinate in rows]


@on_server
def get_coordinate(server, seed):
    coordinate = Coordinate.objects.filter(seed=str(seed)).first()
    return coordinate.as_dict() if coordinate else None
