"""
What the maps show. The sector is the whole map of a server, a quadrant one of its natural zones : game.models.Zone, drawn
by geography.galaxy, whose systems hold its number on System.region.

shortcut: the deposits aren't stored, the generator doesn't know them yet : they are drawn from the seeds, always the same for
a body. Store them at generation once their rules are decided, deposits_of_body is the only function to replace.
"""

import math
import random
import re

import numpy as np
from django.core.cache import cache
from django.db.models import Max
from django.db.models.functions import Substr
from django.utils.translation import get_language, gettext as _, gettext_lazy

from data.coordinates import SUBTYPE_NAMES, TYPE_NAMES
from data.ententes import memberships_of_commandants
from data.locations import seed_of
from data.names import localized_name
from database.schemas import on_server
from game.models import Colony, Commandant, Coordinate, Resource, System, Zone
from geography import galaxy

SECTOR_SIZE = 100  # The squares of the seeds : geography.map_generator
CELL = galaxy.CELL  # The cells of the shapes of the zones
AROUND = 5  # The map of a zone also shows, dimmed, the systems of this many cells around it
CACHE_SECONDS = 3600  # What only depends on the map is heavy to compute and only changes with a new generation

SYSTEM_TYPE_NAMES = {
    'realistic': gettext_lazy("Ordinaire"),
    'standard': gettext_lazy("Ordinaire"),
    'wilderness': gettext_lazy("Sauvage"),
    'native': gettext_lazy("Monde natal"),
    'habitable_gaia': gettext_lazy("Monde-jardin"),
    'habitable_good': gettext_lazy("Habitabilité bonne"),
    'habitable_medium': gettext_lazy("Habitabilité moyenne"),
    'habitable_poor': gettext_lazy("Habitabilité faible"),
    'danger': gettext_lazy("Dangereux"),
    'resources_rich': gettext_lazy("Riche en ressources"),
    'gas_rich': gettext_lazy("Riche en gaz"),
    'scientific': gettext_lazy("Scientifique"),
    'vestige': gettext_lazy("Vestige"),
}

# The chance for a body to hold each resource
DEPOSIT_CHANCES = {
    'telluric': {'common_metal': 0.7, 'aluminium': 0.4, 'water': 0.3, 'hydrocarbons': 0.15, 'titanium': 0.1, 'uranium': 0.04, 'rare_earth': 0.03},
    'jovian': {'hydrogen': 0.8, 'methane': 0.6},
    'planetoid': {'common_metal': 0.5, 'water': 0.1, 'titanium': 0.1, 'graphite': 0.05},
    'asteroid_belt': {'common_metal': 0.8, 'aluminium': 0.4, 'titanium': 0.2, 'graphite': 0.05, 'tungsten': 0.05, 'beryllium': 0.03, 'rare_earth': 0.03},
    'oort_cloud': {'water': 0.7, 'methane': 0.4},
}
RARE_RESOURCES = ('uranium', 'rare_earth', 'graphite', 'tungsten', 'beryllium')
# The system types which double the chances and the richness on some bodies
RICH_BODIES = {'resources_rich': ('telluric', 'planetoid', 'asteroid_belt'), 'gas_rich': ('jovian', 'oort_cloud')}


def deposits_of_body(coordinate_seed, body_type, system_type):
    # {resource: richness from 1 to 100}
    rng = random.Random(int(coordinate_seed))
    boost = 2 if body_type in RICH_BODIES.get(system_type, ()) else 1
    deposits = {}
    for resource, chance in DEPOSIT_CHANCES.get(body_type, {}).items():
        found, richness = rng.random(), rng.random()
        if found < chance * boost:
            deposits[resource] = min(100, boost * (1 + int(richness ** 2 * 99)))  # The great concentrations stay uncommon
    return deposits


########################################################################################################################
# THE SYSTEMS AND THE ZONES


def position(seed):
    # (y, x) of a system on the whole map, in units : the square of its sector, then its place inside
    return int(seed[4:7]) * SECTOR_SIZE + int(seed[10:13]), int(seed[7:10]) * SECTOR_SIZE + int(seed[13:16])


def _systems(sector_ids=None):
    # The systems of these sectors (all of them without), in the order of their seeds :
    # [(seed, y, x, star class, name, system type, region)]
    stars, details = Coordinate.objects.filter(sys_coordinate=0), System.objects.all()
    if sector_ids is not None:
        stars, details = stars.filter(sector_id__in=sector_ids), details.filter(sector_id__in=sector_ids)
    details = {seed: (system_type, region) for seed, system_type, region in details.values_list('seed', 'system_type', 'region')}
    return [(seed, *position(seed), star, name, *details.get(seed, ('standard', None)))
            for seed, star, name in stars.order_by('system_id').values_list('system_id', 'subtype', 'name')]


def _columns(rows):
    # The systems as columns : the map of the whole sector holds a hundred thousand of them
    star_keys, type_keys = sorted({row[3] for row in rows}), sorted({row[5] for row in rows})
    star_ranks, type_ranks = {key: rank for rank, key in enumerate(star_keys)}, {key: rank for rank, key in enumerate(type_keys)}
    return {
        'stars': [{'key': key, 'name': str(SUBTYPE_NAMES.get(key, key))} for key in star_keys],
        'types': [{'key': key, 'name': str(SYSTEM_TYPE_NAMES.get(key, key))} for key in type_keys],
        'y': [row[1] for row in rows], 'x': [row[2] for row in rows], 'name': [row[4] for row in rows],
        'star': [star_ranks[row[3]] for row in rows], 'type': [type_ranks[row[5]] for row in rows],
        'zone': [row[6] for row in rows],
    }


def _zone(zone, shape=True):
    kind = galaxy.ZONES.get(zone.kind, {'label': zone.kind, 'colour': (128, 128, 128)})
    found = {'id': zone.region, 'name': zone.name, 'kind': zone.kind, 'kind_name': kind['label'],
             'color': '#%02x%02x%02x' % tuple(kind['colour']), 'y': zone.y, 'x': zone.x, 'systems': zone.nb_systems}
    return found | ({'shape': zone.shape} if shape else {})


def map_version():
    # Changes with each generation of the map : what the browsers and the cache keep of the old one isn't used anymore
    return Zone.objects.aggregate(last=Max('id'))['last']


@on_server
def region_of(server, text, server_seed):
    # The zone designated by its number, or by any place inside it : a system or a body, by its seed or its readable place
    text = str(text or '').strip()
    if re.fullmatch(r'\d{1,6}', text):
        return int(text) if Zone.objects.filter(region=int(text)).exists() else None
    seed = seed_of(text, server_seed)
    if seed and len(seed) >= 16:
        return System.objects.filter(seed=seed[:16]).values_list('region', flat=True).first()
    return None


@on_server
def place(server, kind, place_id):
    # A place of the maps for the lists of a commandant, its name from the map itself. None if it doesn't exist.
    place_id = str(place_id or '').strip()
    if kind == 'zone' and re.fullmatch(r'\d{1,6}', place_id):
        name = Zone.objects.filter(region=int(place_id)).values_list('name', flat=True).first()
    elif kind == 'system' and re.fullmatch(r'\d{16}', place_id):
        name = Coordinate.objects.filter(seed=place_id + '00').values_list('name', flat=True).first()
    else:
        return None
    return {'kind': kind, 'id': place_id, 'name': name} if name else None


########################################################################################################################
# WHO IS WHERE


def _colonies_by_system(rows, commandant_id):
    colonies = {}
    for colony in rows.order_by('id').values('id', 'name', 'owner_id', 'coordinate'):
        is_mine = colony['owner_id'] == commandant_id
        colonies.setdefault(colony['coordinate'][:16], []).append({
            'name': colony['name'], 'owner': colony['owner_id'], 'is_mine': is_mine,
            'id': colony['id'] if is_mine else None,  # The page of a colony is for its owner
        })
    return colonies


def _empires(owner_ids, commandant_id, memberships):
    # Only what the other players are allowed to know of a commandant
    return [{'id': row['id'], 'commandant': row['commandant_name'], 'civilisation': row['civilisation_name'],
             'is_mine': row['id'] == commandant_id, 'ententes': [entente['id'] for entente in memberships.get(row['id'], [])]}
            for row in Commandant.objects.filter(id__in=owner_ids).order_by('civilisation_name')
                                         .values('id', 'commandant_name', 'civilisation_name')]


def _politics(server, colonies, commandant_id):
    # The empires and the ententes present on a map
    owner_ids = {colony['owner'] for rows in colonies.values() for colony in rows}
    memberships = memberships_of_commandants(server, owner_ids)
    ententes = {entente['id']: entente for rows in memberships.values() for entente in rows}
    return _empires(owner_ids, commandant_id, memberships), sorted(ententes.values(), key=lambda entente: entente['name'].lower())


def _resources(language):
    # The resources the deposits are made of, the most common first ; only those the Excel of this server knows
    abundance = {}
    for chances in DEPOSIT_CHANCES.values():
        for resource, chance in chances.items():
            abundance[resource] = abundance.get(resource, 0) + chance
    return [{'id': row.internal_name, 'name': localized_name(row.data, language), 'rare': row.internal_name in RARE_RESOURCES}
            for row in sorted(Resource.objects.filter(internal_name__in=abundance), key=lambda row: -abundance[row.internal_name])]


def _labels():
    return {
        'colonies': _("Colonies"), 'no_colony': _("Aucune colonie"), 'bodies': _("Astres"), 'position': _("Position"),
        'open_system': _("Ouvrir le système"), 'open_zone': _("Ouvrir le quadrant"), 'rare': _("Rare"), 'zone': _("Quadrant"),
        'results': _("systèmes correspondent"), 'result': _("système correspond"), 'all_systems': _("systèmes"),
        'no_result': _("Aucun système ne correspond"), 'no_empire': _("Aucun empire ici"), 'no_entente': _("Aucune entente ici"),
        'more': _("autres résultats"), 'deposits': _("Gisements"), 'no_deposit': _("Aucun gisement"), 'vortex': _("Liens de vortex"),
        'rare_resources': _("Ressources rares"), 'load_error': _("Une erreur est survenue, veuillez réessayer"),
        'loading': _("Chargement de la carte…"), 'towards': _("Vers"), 'outside': _("Hors du quadrant"), 'native': _("Votre quadrant d'origine"),
    }


########################################################################################################################
# THE MAP OF THE SECTOR : the whole map. What only depends on the map is asked apart, kept in cache and compressed.


@on_server
def sector_map(server, commandant_id, native_region, server_seed, language):
    # What the page needs besides the map itself, ready for json_script. None if this server has no zones.
    version = map_version()
    if version is None:
        return None
    colonies = _colonies_by_system(Colony.objects.all(), commandant_id)
    empires, ententes = _politics(server, colonies, commandant_id)
    return {
        'title': _("Carte du secteur"), 'mode': 'sector', 'version': version, 'native_zone': native_region, 'server_seed': server_seed,
        'colonies': colonies, 'empires': empires, 'ententes': ententes, 'resources': _resources(language), 'labels': _labels(),
    }


def _sector_systems():
    zones = list(Zone.objects.order_by('region'))
    height = (max(row for zone in zones for row, _, _ in zone.shape) + 1) * CELL
    width = max(start + length for zone in zones for _, start, length in zone.shape) * CELL
    return {'height': height, 'width': width, 'cell': CELL, 'zones': [_zone(zone) for zone in zones], 'systems': _columns(_systems())}


@on_server
def sector_systems(server):
    # shortcut: kept in the memory of each process, an hour at most after a new generation. Store it at generation if it gets slow.
    return cache.get_or_set(f'sector_systems:{server}:{map_version()}:{get_language()}', _sector_systems, CACHE_SECONDS)


########################################################################################################################
# THE MAP OF A QUADRANT : one zone, the systems around it dimmed, its vortex and the way to the zones around it


def _grid(zones, row0, col0, rows, cols):
    # The region of each cell of this window of the map, -1 where none of these zones is
    owner = np.full((rows, cols), -1, np.int64)
    for zone in zones:
        for row, start, length in zone.shape:
            if row0 <= row < row0 + rows:
                first, last = max(start - col0, 0), min(start + length - col0, cols)
                if first < last:
                    owner[row - row0, first:last] = zone.region
    return owner


def _window(zone):
    # The cells of the zone and AROUND more on every side : (first row, first column, rows, columns)
    rows = [row for row, _, _ in zone.shape]
    cols = [start for _, start, _ in zone.shape] + [start + length for _, start, length in zone.shape]
    row0, col0 = max(min(rows) - AROUND, 0), max(min(cols) - AROUND, 0)
    return row0, col0, max(rows) + AROUND + 1 - row0, max(cols) + AROUND - col0


def _shown(zone, server_seed):
    # The systems of the zone, then those around it : (rows of _systems, the mask of the cells shown, its window)
    row0, col0, rows, cols = _window(zone)
    mask = _grid([zone], row0, col0, rows, cols) == zone.region
    for _ in range(AROUND):
        mask = galaxy.dilate(mask)
    sectors = {(int((row0 + row) * CELL // SECTOR_SIZE), int((col0 + col) * CELL // SECTOR_SIZE)) for row, col in zip(*np.nonzero(mask))}
    sector_ids = [f'{server_seed}{y:03}{x:03}' for y, x in sorted(sectors)]
    shown = [row for row in _systems(sector_ids)
             if row[6] == zone.region or mask[min(max(row[1] // CELL - row0, 0), rows - 1), min(max(row[2] // CELL - col0, 0), cols - 1)]]
    return shown, sector_ids


def _vortex(rows):
    # Flat pairs of ranks : the rule of the generator, the bigger of two stars has to reach the other one
    if not rows:
        return []
    classes = {name: index for index, name in enumerate(galaxy.CLASSES)}
    edges = galaxy.links(np.array([row[1] for row in rows], np.int64), np.array([row[2] for row in rows], np.int64),
                         np.array([classes.get(row[3], 0) for row in rows], np.int64))
    return edges.ravel().tolist()


def _touching(cells, others):
    # The cells which have one of the others above, below or on a side
    touching = np.zeros_like(cells)
    touching[1:] |= cells[1:] & others[:-1]
    touching[:-1] |= cells[:-1] & others[1:]
    touching[:, 1:] |= cells[:, 1:] & others[:, :-1]
    touching[:, :-1] |= cells[:, :-1] & others[:, 1:]
    return touching


def _exits(zone, neighbours):
    # An arrow toward each zone around : on the border they share, pointing from this zone toward the other one
    row0, col0, rows, cols = _window(zone)
    owner = _grid([zone, *neighbours], row0, col0, rows, cols)
    inside = owner == zone.region
    exits = []
    for neighbour in sorted(neighbours, key=lambda neighbour: neighbour.name):
        outside = owner == neighbour.region
        border, beyond = _touching(inside, outside), _touching(outside, inside)
        if not border.any():  # Only touching outside the window : it can't happen, the window holds the whole zone
            continue
        cells = np.argwhere(border)
        middle = cells.mean(0)
        anchor = cells[np.argmin(((cells - middle) ** 2).sum(1))]  # On the border itself, the closest to its middle
        dy, dx = np.argwhere(beyond).mean(0) - middle
        if math.hypot(dy, dx) < 0.5:  # A border around the zone : away from its centre
            dy, dx = anchor[0] + row0 + 0.5 - zone.y / CELL, anchor[1] + col0 + 0.5 - zone.x / CELL
        length = math.hypot(dy, dx) or 1
        exits.append({'zone': neighbour.region, 'name': neighbour.name, 'kind_name': _zone(neighbour, shape=False)['kind_name'],
                      'y': int((anchor[0] + row0 + 0.5) * CELL), 'x': int((anchor[1] + col0 + 0.5) * CELL),
                      'dy': round(dy / length, 3), 'dx': round(dx / length, 3)})
    return exits


@on_server
def zone_map(server, region, commandant_id, language, server_seed):
    # All that the page needs, ready for json_script. None if this zone doesn't exist.
    zone = Zone.objects.filter(region=region).first()
    if zone is None:
        return None
    neighbours = list(Zone.objects.filter(region__in=zone.neighbours))
    rows, sector_ids = _shown(zone, server_seed)
    ranks = {row[0]: rank for rank, row in enumerate(rows)}
    colonies = _colonies_by_system(Colony.objects.annotate(sector=Substr('coordinate', 1, 10)).filter(sector__in=sector_ids), commandant_id)
    colonies = {seed: rows_ for seed, rows_ in colonies.items() if seed in ranks}
    empires, ententes = _politics(server, colonies, commandant_id)
    row0, col0, height, width = _window(zone)
    return {
        'id': zone.region, 'title': _("Quadrant %(zone)s") % {'zone': zone.name}, 'mode': 'zone', 'zone': _zone(zone, shape=False),
        'server_seed': server_seed,
        'bounds': {'y': row0 * CELL, 'x': col0 * CELL, 'height': height * CELL, 'width': width * CELL}, 'cell': CELL,
        'zones': [_zone(zone) for zone in [zone, *neighbours]], 'exits': _exits(zone, neighbours),
        'systems': _columns(rows), 'vortex': _vortex(rows),
        'colonies': {ranks[seed]: rows_ for seed, rows_ in colonies.items()},
        'empires': empires, 'ententes': ententes, 'resources': _resources(language), 'labels': _labels(),
    }


def _zone_deposits(region, server_seed):
    # {resource: {'indexes': [rank of a system], 'values': [what this system holds]}}, '__rare' for all the rare ones together.
    # Only the systems of the zone : the ones around it belong to the maps of their own zones.
    zone = Zone.objects.get(region=region)
    rows, sector_ids = _shown(zone, server_seed)
    ranks = {row[0]: rank for rank, row in enumerate(rows) if row[6] == region}
    system_types = {row[0]: row[5] for row in rows}
    totals = {}
    bodies = Coordinate.objects.filter(sector_id__in=sector_ids).exclude(type='star').values_list('seed', 'system_id', 'type')
    for seed, system_id, body_type in bodies.iterator():
        if system_id not in ranks:
            continue
        for resource, richness in deposits_of_body(seed, body_type, system_types[system_id]).items():
            for key in (resource, '__rare') if resource in RARE_RESOURCES else (resource,):
                of_key = totals.setdefault(key, {})
                of_key[ranks[system_id]] = of_key.get(ranks[system_id], 0) + richness
    return {resource: {'indexes': list(values), 'values': list(values.values())} for resource, values in totals.items()}


@on_server
def zone_deposits(server, region, resource, server_seed):
    if not Zone.objects.filter(region=region).exists():
        return {'indexes': [], 'values': []}
    # shortcut: kept in the memory of each process, an hour at most after a new generation. Replace it when the deposits are stored.
    deposits = cache.get_or_set(f'zone_deposits:{server}:{map_version()}:{region}', lambda: _zone_deposits(region, server_seed), CACHE_SECONDS)
    return deposits.get(resource, {'indexes': [], 'values': []})


@on_server
def system_bodies(server, system_seed):
    # The bodies of a system and their deposits, for the details of a system on the map
    system_type = System.objects.filter(seed=system_seed).values_list('system_type', flat=True).first()
    if system_type is None:
        return []
    bodies = Coordinate.objects.filter(sector_id=system_seed[:10], system_id=system_seed).order_by('sys_coordinate') \
        .values_list('seed', 'sys_coordinate', 'name', 'type', 'subtype')
    return [{'orbit': orbit, 'name': name, 'type': str(TYPE_NAMES.get(body_type, body_type)), 'subtype': str(SUBTYPE_NAMES.get(subtype, '')),
             'deposits': deposits_of_body(seed, body_type, system_type)} for seed, orbit, name, body_type, subtype in bodies]
