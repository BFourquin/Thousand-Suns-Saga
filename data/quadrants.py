"""
What the map of a quadrant shows. A quadrant is a quarter of a sector : see data.modifiers.quadrant_of.

shortcut: the vortex and the deposits aren't stored, the generator doesn't know them yet : they are drawn from the seeds,
always the same for a place. Store them at generation once their rules are decided, deposits_of_body and vortex_of_quadrant
are the only functions to replace.
"""

import random
import re

from django.core.cache import cache
from django.utils.translation import gettext as _, gettext_lazy

from data.coordinates import SUBTYPE_NAMES, TYPE_NAMES
from data.ententes import memberships_of_commandants
from data.modifiers import quadrant_of
from data.names import localized_name
from database.schemas import on_server
from game.models import Colony, Commandant, Coordinate, Resource, Sector, System

SECTOR_SIZE = 100
QUADRANT_SIZE = 50
CACHE_SECONDS = 3600  # What only depends on the seeds is heavy to compute on a big sector, and only changes with a new generation

DIRECTIONS = {'north': (-1, 0), 'south': (1, 0), 'west': (0, -1), 'east': (0, 1)}
QUADRANT_NAMES = {'00': gettext_lazy("Nord-Ouest"), '01': gettext_lazy("Nord-Est"),
                  '10': gettext_lazy("Sud-Ouest"), '11': gettext_lazy("Sud-Est")}

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

VORTEX_NETWORKS = ('alpha', 'beta', 'gamma', 'delta')
VORTEX_SHARE = 0.1  # Of the systems of a quadrant


def quadrant_id(text):
    # The quadrant designated by its id or by the seed of a system or a coordinate. None if it is neither.
    if re.fullmatch(r'\d{16}(\d{2})?', text):
        text = quadrant_of(text)
    return text if re.fullmatch(r'\d{10}:[01]{2}', text) else None


def neighbour_quadrant(quadrant, dy, dx):
    # Across the border of a sector when needed. Seed of a sector : 4 digits of the server, 3 of its Y position, 3 of its X.
    sector, sub = quadrant.split(':')
    y = int(sector[4:7]) * 2 + int(sub[0]) + dy
    x = int(sector[7:10]) * 2 + int(sub[1]) + dx
    if y < 0 or x < 0:
        return None
    return f'{sector[:4]}{y // 2:03}{x // 2:03}:{y % 2}{x % 2}'


def _origin(quadrant):
    return int(quadrant[11]) * QUADRANT_SIZE, int(quadrant[12]) * QUADRANT_SIZE


def _in_quadrant(positions, quadrant):
    y0, x0 = _origin(quadrant)
    return sorted((y, x) for y, x in positions if y0 <= y < y0 + QUADRANT_SIZE and x0 <= x < x0 + QUADRANT_SIZE)


def _system_seed(quadrant, position):
    return f'{quadrant[:10]}{position[0]:03}{position[1]:03}'


########################################################################################################################
# DEPOSITS


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
# VORTEX


def _vortex_nodes(quadrant, positions):
    # {network: positions of its nodes}, depending only on the quadrant : its neighbours find the same ones
    rng = random.Random(quadrant)
    nodes = {network: [] for network in VORTEX_NETWORKS}
    for position in rng.sample(positions, round(len(positions) * VORTEX_SHARE)):
        nodes[rng.choice(VORTEX_NETWORKS)].append(position)
    return {network: sorted(positions) for network, positions in nodes.items() if positions}


def _shortest_links(positions):
    # Minimum spanning tree : each node reaches the others by the shortest vortex
    linked, links = positions[:1], []
    remaining = positions[1:]
    while remaining:
        length, a, b = min(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2, a, b) for a in linked for b in remaining)
        links.append((a, b))
        linked.append(b)
        remaining.remove(b)
    return links


def _closest_to_border(positions, dy, dx):
    return min(positions, key=lambda position: (-(position[0] * dy + position[1] * dx), position))


def vortex_of_quadrant(quadrant, positions_of_sectors):
    # positions_of_sectors : {sector seed: positions of its systems}, for this sector and the ones around it.
    # A network continues in a neighbouring quadrant through the nodes the closest to their shared border, on both sides.
    def nodes_of(place):
        return _vortex_nodes(place, _in_quadrant(positions_of_sectors[place[:10]], place))

    nodes = nodes_of(quadrant)
    result = {'nodes': {}, 'links': [], 'exits': []}

    for network, positions in nodes.items():
        result['nodes'].update({_system_seed(quadrant, position): network for position in positions})
        result['links'] += [{'network': network, 'from': _system_seed(quadrant, a), 'to': _system_seed(quadrant, b)}
                            for a, b in _shortest_links(positions)]

    for direction, (dy, dx) in DIRECTIONS.items():
        neighbour = neighbour_quadrant(quadrant, dy, dx)
        if neighbour is None or neighbour[:10] not in positions_of_sectors:
            continue
        neighbour_nodes = nodes_of(neighbour)
        for network in nodes.keys() & neighbour_nodes.keys():
            result['exits'].append({'network': network, 'direction': direction, 'quadrant': neighbour,
                                    'from': _system_seed(quadrant, _closest_to_border(nodes[network], dy, dx)),
                                    'to': _system_seed(neighbour, _closest_to_border(neighbour_nodes[network], -dy, -dx))})
    return result


########################################################################################################################
# THE MAP


def _bodies_by_system(sector_id, quadrant):
    y0, x0 = _origin(quadrant)
    last = QUADRANT_SIZE - 1
    rows = Coordinate.objects.filter(sector_id=sector_id, sys_y__range=(y0, y0 + last), sys_x__range=(x0, x0 + last)) \
        .order_by('seed').values('seed', 'system_id', 'type', 'subtype', 'name', 'sys_y', 'sys_x', 'sys_coordinate')
    bodies = {}
    for row in rows:
        bodies.setdefault(row['system_id'], []).append(row)
    return bodies


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


def _labels():
    return {
        'colonies': _("Colonies"), 'no_colony': _("Aucune colonie"), 'bodies': _("Astres"), 'vortex': _("Vortex"), 'position': _("Position"),
        'open_system': _("Ouvrir le système"), 'open_quadrant': _("Vers le quadrant voisin"), 'rare': _("Rare"),
        'results': _("systèmes correspondent"), 'result': _("système correspond"), 'all_systems': _("systèmes"),
        'no_result': _("Aucun système ne correspond"), 'no_empire': _("Aucun empire ici"), 'no_entente': _("Aucune entente ici"),
        'network': _("Réseau"), 'alpha': _("Alpha"), 'beta': _("Bêta"), 'gamma': _("Gamma"), 'delta': _("Delta"), 'more': _("autres résultats"),
        'deposits': _("Gisements"), 'no_deposit': _("Aucun gisement"), 'no_vortex': _("Aucun vortex"),
        'rare_resources': _("Ressources rares"), 'quadrant': _("Quadrant"), 'open_quadrant_map': _("Ouvrir le quadrant"), 'load_error': _("Une erreur est survenue, veuillez réessayer"),
    }


@on_server
def quadrant_map(server, quadrant, commandant_id, language):
    # All that the page needs, ready for json_script. None if this quadrant doesn't exist.
    sector_id = quadrant[:10]
    neighbours = {direction: neighbour_quadrant(quadrant, dy, dx) for direction, (dy, dx) in DIRECTIONS.items()}
    sectors = {sector['seed']: sector for sector in Sector.objects.filter(
        seed__in={sector_id} | {neighbour[:10] for neighbour in neighbours.values() if neighbour})
        .values('seed', 'pos_y', 'pos_x', 'sector_type', 'systems_coordinates')}
    if sector_id not in sectors:
        return None

    bodies = _bodies_by_system(sector_id, quadrant)
    system_types = dict(System.objects.filter(seed__in=bodies).values_list('seed', 'system_type'))
    colonies = _colonies_by_system(Colony.objects.filter(coordinate__in=[body['seed'] for rows in bodies.values() for body in rows]), commandant_id)

    systems = []
    for system_id, rows in bodies.items():
        system_type = system_types.get(system_id, 'standard')
        star = rows[0]
        totals = {}
        details = []
        for row in rows:
            deposits = deposits_of_body(row['seed'], row['type'], system_type)
            for resource, richness in deposits.items():
                totals[resource] = totals.get(resource, 0) + richness
            details.append({'orbit': row['sys_coordinate'], 'name': row['name'], 'type': str(TYPE_NAMES.get(row['type'], row['type'])),
                            'subtype': str(SUBTYPE_NAMES.get(row['subtype'], '')), 'deposits': deposits})
        systems.append({
            'id': system_id, 'name': star['name'], 'y': star['sys_y'], 'x': star['sys_x'],
            'type': system_type, 'type_name': str(SYSTEM_TYPE_NAMES.get(system_type, system_type)),
            'star': star['subtype'], 'star_name': str(SUBTYPE_NAMES.get(star['subtype'], star['subtype'])),
            'bodies': details, 'deposits': totals, 'colonies': colonies.get(system_id, []),
        })

    empires, ententes = _politics(server, colonies, commandant_id)

    # Only the resources the generator knows on this server, its Excel file could have renamed them
    found = {resource for system in systems for resource in system['deposits']}
    resources = [{'id': row.internal_name, 'name': localized_name(row.data, language), 'rare': row.internal_name in RARE_RESOURCES}
                 for row in Resource.objects.filter(internal_name__in=found).order_by('id')]

    positions = {seed: [tuple(position) for position in sector['systems_coordinates']] for seed, sector in sectors.items()}
    y0, x0 = _origin(quadrant)
    return {
        'id': quadrant,
        'title': _("Quadrant %(quadrant)s du secteur %(sector)s") % {
            'quadrant': QUADRANT_NAMES[quadrant[11:]], 'sector': f"{sectors[sector_id]['pos_y']}-{sectors[sector_id]['pos_x']}"},
        'origin': {'y': y0, 'x': x0}, 'size': QUADRANT_SIZE,
        'neighbours': {direction: neighbour for direction, neighbour in neighbours.items() if neighbour and neighbour[:10] in sectors},
        'systems': systems, 'empires': empires, 'ententes': ententes,
        'resources': resources, 'vortex': vortex_of_quadrant(quadrant, positions), 'labels': _labels(),
    }


########################################################################################################################
# THE MAP OF A SECTOR : it has to stay light with tens of thousands of systems, so the systems are sent as columns,
# without their bodies, and the deposits of one resource only when a search asks for them


def sector_id_of(text):
    # The sector designated by its seed, the id of a quadrant or the seed of a system or a coordinate. None if it is neither.
    return text[:10] if re.fullmatch(r'\d{10}(:\d{2}|\d{6}(\d{2})?)?', text) else None


def _neighbour_sectors(sector_id):
    y, x = int(sector_id[4:7]), int(sector_id[7:10])
    return {direction: f'{sector_id[:4]}{y + dy:03}{x + dx:03}' for direction, (dy, dx) in DIRECTIONS.items() if y + dy >= 0 and x + dx >= 0}


def _stars_of_sector(sector_id):
    # Their order is the rank of the systems on the map : the vortex and the deposits refer to it
    return Coordinate.objects.filter(seed__startswith=sector_id, sys_coordinate=0).order_by('seed').values_list('system_id', 'sys_y', 'sys_x', 'subtype', 'name')


def _vortex_of_sector(sector_id, neighbours, ranks):
    positions = {sector.seed: [tuple(position) for position in sector.systems_coordinates]
                 for sector in Sector.objects.filter(seed__in=[sector_id, *neighbours.values()]).only('seed', 'systems_coordinates')}
    result = {'nodes': {}, 'links': {}, 'exits': []}
    crossed = set()
    per_axis = range(SECTOR_SIZE // QUADRANT_SIZE)
    for quadrant in (f'{sector_id}:{y}{x}' for y in per_axis for x in per_axis):
        vortex = vortex_of_quadrant(quadrant, positions)
        for seed, network in vortex['nodes'].items():
            result['nodes'].setdefault(network, []).append(ranks[seed])
        for link in vortex['links']:
            result['links'].setdefault(link['network'], []).extend((ranks[link['from']], ranks[link['to']]))
        for exit_ in vortex['exits']:
            if exit_['to'] not in ranks:
                result['exits'].append({'network': exit_['network'], 'direction': exit_['direction'], 'from': ranks[exit_['from']]})
            elif (exit_['to'], exit_['from'], exit_['network']) not in crossed:  # Each side of a border finds the same one
                crossed.add((exit_['from'], exit_['to'], exit_['network']))
                result['links'].setdefault(exit_['network'], []).extend((ranks[exit_['from']], ranks[exit_['to']]))
    return result


@on_server
def sector_map(server, sector_id, commandant_id, language):
    # All that the page needs, ready for json_script. None if this sector doesn't exist.
    sector = Sector.objects.filter(seed=sector_id).values('pos_y', 'pos_x').first()
    if sector is None:
        return None

    stars = list(_stars_of_sector(sector_id))
    ranks = {star[0]: rank for rank, star in enumerate(stars)}
    system_types = dict(System.objects.filter(sector_id=sector_id).values_list('seed', 'system_type'))
    types = [system_types.get(star[0], 'standard') for star in stars]
    star_keys = sorted({star[3] for star in stars})
    type_keys = sorted(set(types))
    star_ranks = {key: rank for rank, key in enumerate(star_keys)}
    type_ranks = {key: rank for rank, key in enumerate(type_keys)}

    colonies = _colonies_by_system(Colony.objects.filter(coordinate__startswith=sector_id), commandant_id)
    empires, ententes = _politics(server, colonies, commandant_id)

    abundance = {}
    for chances in DEPOSIT_CHANCES.values():
        for resource, chance in chances.items():
            abundance[resource] = abundance.get(resource, 0) + chance
    resources = [{'id': row.internal_name, 'name': localized_name(row.data, language), 'rare': row.internal_name in RARE_RESOURCES}
                 for row in sorted(Resource.objects.filter(internal_name__in=abundance), key=lambda row: -abundance[row.internal_name])]

    candidates = _neighbour_sectors(sector_id)
    existing = set(Sector.objects.filter(seed__in=candidates.values()).values_list('seed', flat=True))
    neighbours = {direction: seed for direction, seed in candidates.items() if seed in existing}

    return {
        'id': sector_id,
        'title': _("Secteur %(sector)s") % {'sector': f"{sector['pos_y']}-{sector['pos_x']}"},
        'size': SECTOR_SIZE, 'quadrant_size': QUADRANT_SIZE, 'neighbours': neighbours,
        'stars': [{'key': key, 'name': str(SUBTYPE_NAMES.get(key, key))} for key in star_keys],
        'types': [{'key': key, 'name': str(SYSTEM_TYPE_NAMES.get(key, key))} for key in type_keys],
        'systems': {'y': [star[1] for star in stars], 'x': [star[2] for star in stars], 'star': [star_ranks[star[3]] for star in stars],
                    'type': [type_ranks[system_type] for system_type in types], 'name': [star[4] for star in stars]},
        'colonies': {ranks[system_id]: rows for system_id, rows in colonies.items() if system_id in ranks},
        'empires': empires, 'ententes': ententes, 'resources': resources, 'labels': _labels(),
        'vortex': cache.get_or_set(f'sector_vortex:{server}:{sector_id}', lambda: _vortex_of_sector(sector_id, neighbours, ranks), CACHE_SECONDS),
    }


def _deposits_of_sector(sector_id):
    # {resource: {'indexes': [rank of a system], 'values': [what this system holds]}}, '__rare' for all the rare ones together
    ranks = {star[0]: rank for rank, star in enumerate(_stars_of_sector(sector_id))}
    system_types = dict(System.objects.filter(sector_id=sector_id).values_list('seed', 'system_type'))
    totals = {}
    bodies = Coordinate.objects.filter(seed__startswith=sector_id).exclude(type='star').values_list('seed', 'system_id', 'type')
    for seed, system_id, body_type in bodies.iterator():
        for resource, richness in deposits_of_body(seed, body_type, system_types.get(system_id, 'standard')).items():
            for key in (resource, '__rare') if resource in RARE_RESOURCES else (resource,):
                of_key = totals.setdefault(key, {})
                of_key[ranks[system_id]] = of_key.get(ranks[system_id], 0) + richness
    return {resource: {'indexes': list(values), 'values': list(values.values())} for resource, values in totals.items()}


@on_server
def sector_deposits(server, sector_id, resource):
    if not Sector.objects.filter(seed=sector_id).exists():
        return {'indexes': [], 'values': []}
    # shortcut: kept in the memory of each process, an hour at most after a new generation. Replace it when the deposits are stored.
    deposits = cache.get_or_set(f'sector_deposits:{server}:{sector_id}', lambda: _deposits_of_sector(sector_id), CACHE_SECONDS)
    return deposits.get(resource, {'indexes': [], 'values': []})
