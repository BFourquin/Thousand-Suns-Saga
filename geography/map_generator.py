"""
The map of a server : geography.galaxy draws it, this module reads its parameters in the Excel of the server and writes it
into the tables of the game.

The game keeps its seeds of 18 digits : server (4), sector Y and X (3 + 3), system Y and X in its sector (3 + 3), orbit (2).
A sector of the tables is a square of SECTOR_SIZE units of the galaxy ; the natural zone of each system is on System.zone.
"""

import random
from collections import Counter, defaultdict

from database.schemas import on_server
from game.models import Coordinate, Sector, StartingValues, System
from data import map_generator
from geography import galaxy, name_generator

SECTOR_SIZE = 100
ORDINARY_TYPES = ('realistic', 'standard', 'wilderness')  # Their star comes from their zone, the others' from MG_systems_types
DEFAULT_PLAYERS = {'saga': 100, 'skirmish': 10}  # Without a row max_players in the sheet MapGenerator


def excel_importer(excel_map_generator_path, sheet_map_generator_name):

    import pylightxl as xl

    with open(excel_map_generator_path, 'rb') as f:
        xldb = xl.readxl(f, ws=sheet_map_generator_name)

        mg_config = []

        for col in xldb.ws(ws=sheet_map_generator_name).cols:

            if col[0] and not col[0][0] == '#':

                # Manual end of file
                if col[0] == 'END_OF_FILE':
                    break

                # Header
                if col[0] in ('Map Generator Properties', 'General game settings', 'sector_type', 'system_type', 'solar_type'):
                    titles = col
                    continue

                conf = {}
                for i in range(len(titles)):

                    if titles[i] in (None, '', 'END_OF_FILE', 'Map Generator Properties', 'General game settings') or titles[i][0] == '#':
                        continue

                    if col[i] == '':
                        conf[titles[i]] = None
                    elif col[i] in ('True', 'true'):
                        conf[titles[i]] = True
                    elif col[i] in ('False', 'false'):
                        conf[titles[i]] = False
                    else:
                        conf[titles[i]] = col[i]

                mg_config.append(conf)

    return mg_config


def load_map_generator_parameters(server_name, excel_path):
    # Kept in the database : what the map of the server was made from
    for mg_type, sheet in (('global', 'MapGenerator'), ('systems_types', 'MG_systems_types'), ('systems_compositions', 'MG_systems')):
        map_generator.set_map_generator_parameters(server_name, excel_importer(excel_path, sheet), mg_type=mg_type)


def type_stars(excel_path):
    # {system type : {star class : weight}} for the special types, from the sheet MG_systems_types
    prefix = 'solar_type_probability_'
    return {row['system_type']: {name[len(prefix):]: value for name, value in row.items()
                                 if name.startswith(prefix) and value and name[len(prefix):] in galaxy.STARS}
            for row in excel_importer(excel_path, 'MG_systems_types') if row['system_type'] not in ORDINARY_TYPES}


def compositions(excel_path):
    # {star class : the probabilities of its bodies}, from the sheet MG_systems
    return {row['solar_type']: row for row in excel_importer(excel_path, 'MG_systems')}


def map_options(excel_path):
    # The players, the type of game and the rows of the sheet MapGenerator the generator reads : seed, max_players and,
    # left empty, the values of the type of game : area_per_player, homes_per_cradle, vestiges
    params = excel_importer(excel_path, 'MapGenerator')[0]
    gameplay = excel_importer(excel_path, 'Config')[0].get('gameplay_type') or 'saga'
    seed = int(params['seed'])
    if not 1000 <= seed <= 9999:
        raise ValueError(f'MapGenerator : the seed is the 4 digits of the server in every seed of the map, not {seed}')
    players = params.get('max_players')
    if not players:
        players = DEFAULT_PLAYERS.get(gameplay, 100)
        print(f'WARNING :: MapGenerator has no row max_players : a map for {players} players')
    options = {name: int(params[name]) if params.get(name) else value for name, value in galaxy.GAME_TYPES[gameplay].items()}
    options['vestiges'] = bool(params.get('vestiges'))
    return seed, int(players), options


def generate_map(server, excel_path):
    # Draws the map of the server and writes it. Returns the galaxy, for its report.
    seed, players, options = map_options(excel_path)
    if galaxy.SECRET == galaxy.DEV_SECRET:
        print('WARNING :: secrets/map.ini is missing : anyone can draw this map again from its seed. Fine for a test server only.')
    drawn = galaxy.generate(str(seed), players, type_stars=type_stars(excel_path), **options)
    save_galaxy(server, drawn, seed, compositions(excel_path))
    return drawn


def bodies_of(r, star, system_type, composition):
    # The bodies of a system around its star, (type, subtype), in the order of their orbits
    probabilities = composition.get(star) or composition.get('none') or {}

    def count(body):
        numbers = {int(name.rsplit('_', 1)[1]): value for name, value in probabilities.items()
                   if name.startswith(f'prob_{body}_') and value}
        return r.choices(list(numbers), list(numbers.values()))[0] if numbers else 0

    def chance(name):
        return r.random() < (probabilities.get(name) or 0)

    bodies = [('star', star)]
    if system_type == 'native' or system_type.startswith('habitable'):
        bodies.append(('telluric', system_type))
    bodies += [('telluric', 'standard')] * count('telluric')
    if chance('prob_asteroid_belt'):
        bodies.append(('asteroid_belt', 'standard'))
    bodies += [('planetoid', 'standard')] * count('planetoid')
    bodies += [('jovian', 'standard')] * count('jovian')
    if chance('prob_oort_cloud'):
        bodies.append(('oort_cloud', 'standard'))
    return bodies


@on_server
def save_galaxy(server, drawn, server_seed, composition, batch=5000):
    # Every system in its sector of SECTOR_SIZE units, and every body of every system. The homes are the native planets.
    r = galaxy.rng(drawn.key, 'bodies')
    random.seed(r.random())  # The names of name_generator, the same on the same map
    zone_of = drawn.zone_kinds()[drawn.system_zones()]
    sectors, natives, systems, bodies, seen = defaultdict(list), [], [], [], set()
    for i in range(drawn.n):
        y, x = int(drawn.ys[i]), int(drawn.xs[i])
        sy, sx = y % SECTOR_SIZE, x % SECTOR_SIZE
        sector_seed = f'{server_seed:04}{y // SECTOR_SIZE:03}{x // SECTOR_SIZE:03}'
        system_seed = f'{sector_seed}{sy:03}{sx:03}'
        if system_seed in seen:  # A relay of the repair put on a system already there
            continue
        seen.add(system_seed)
        system_type = galaxy.TYPES[drawn.stype[i]]
        system_bodies = {}
        for orbit, (body_type, subtype) in enumerate(bodies_of(r, galaxy.CLASSES[drawn.cls[i]], system_type, composition)):
            seed = f'{system_seed}{orbit:02}'
            bodies.append(Coordinate(seed=seed, type=body_type, subtype=subtype, sector_id=sector_seed, system_id=system_seed,
                                     sys_y=sy, sys_x=sx, sys_coordinate=orbit, name=name_generator.random_combination()))
            system_bodies[seed] = subtype if body_type == 'star' else f'{body_type} {subtype}'
            if subtype == 'native':
                natives.append(int(seed))
        systems.append(System(seed=system_seed, system_type=system_type, system_coordinates=system_bodies, sector_id=sector_seed,
                              pos_y=f'{sy:03}', pos_x=f'{sx:03}', zone=zone_of[i]))
        sectors[sector_seed].append((sy, sx, system_type, zone_of[i]))

    Sector.objects.bulk_create([
        Sector(seed=seed, pos_y=int(seed[4:7]), pos_x=int(seed[7:10]), nb_systems=len(inside),
               sector_type=Counter(zone for *_, zone in inside).most_common(1)[0][0],  # The zone that holds most of its systems
               nb_natives_start=sum(system_type == 'native' for _, _, system_type, _ in inside),
               systems_coordinates=[[sy, sx] for sy, sx, *_ in inside])
        for seed, inside in sectors.items()], batch_size=batch)
    System.objects.bulk_create(systems, batch_size=batch)
    Coordinate.objects.bulk_create(bodies, batch_size=batch)
    starting = StartingValues.objects.first()
    if starting:
        starting.available_native_planets = natives
        starting.save(update_fields=['available_native_planets'])


@on_server
def remove_past_generation(server):
    for model in (Sector, System, Coordinate):
        model.objects.all().delete()

    # These planets don't exist anymore
    StartingValues.objects.update(available_native_planets=[])
