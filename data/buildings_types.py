from collections import defaultdict

from django.utils.translation import gettext_lazy

from data.names import localized_name
from game.models import BuildingType, Technology
from database.schemas import on_server
from data.technology import within_tech_level


# shortcut: the column production_quantity of the Excel is still empty, each building gives this until it is filled
DEFAULT_PRODUCTION_QUANTITY = 1

# The values of the column category of the Excel. A new value still gets its tab, named as in the Excel.
CATEGORIES = {
    'vital_needs': {'name': gettext_lazy("Besoins vitaux"), 'icon': 'fa-wheat-awn'},
    'raw_materials': {'name': gettext_lazy("Extraction"), 'icon': 'fa-gem'},
    'industry': {'name': gettext_lazy("Industrie"), 'icon': 'fa-industry'},
    'electronics': {'name': gettext_lazy("Électronique"), 'icon': 'fa-microchip'},
    'robotic': {'name': gettext_lazy("Robotique"), 'icon': 'fa-robot'},
    'energy': {'name': gettext_lazy("Énergie"), 'icon': 'fa-bolt'},
    'science': {'name': gettext_lazy("Science"), 'icon': 'fa-flask'},
    'commerce': {'name': gettext_lazy("Commerce"), 'icon': 'fa-coins'},
    'culture': {'name': gettext_lazy("Culture et loisirs"), 'icon': 'fa-masks-theater'},
    'politics': {'name': gettext_lazy("Politique"), 'icon': 'fa-landmark'},
    'urban': {'name': gettext_lazy("Habitat"), 'icon': 'fa-city'},
    'space': {'name': gettext_lazy("Espace"), 'icon': 'fa-rocket'},
    'terraformation': {'name': gettext_lazy("Terraformation"), 'icon': 'fa-earth-americas'},
    'military_training': {'name': gettext_lazy("Entraînement militaire"), 'icon': 'fa-person-rifle'},
    'military_production': {'name': gettext_lazy("Production militaire"), 'icon': 'fa-bomb'},
    'military_defense': {'name': gettext_lazy("Défenses"), 'icon': 'fa-shield-halved'},
    'illicit': {'name': gettext_lazy("Illicite"), 'icon': 'fa-skull-crossbones'},
    'singularity': {'name': gettext_lazy("Singularité"), 'icon': 'fa-infinity'},
}

# The tree of the buildings opens on this level : what is obsolete there is hidden, what comes later is small
TREE_DEFAULT_LEVEL = 10
NO_PRODUCTION = 'none'


def production_of(building_type):
    # What the building gives per cycle, working at full capacity
    resource = building_type.get('production')
    return {resource: building_type.get('production_quantity') or DEFAULT_PRODUCTION_QUANTITY} if resource else {}


def is_buildable(building_type, district_category):
    # The Excel has one column of booleans per category of district
    return bool(building_type.get(district_category)) and within_tech_level(building_type)


@on_server
def get_building_type(server, internal_name, language=None):

    building = BuildingType.objects.filter(internal_name=internal_name).first()
    if not building:
        return None

    building = building.as_dict()
    if language:
        building['name'] = localized_name(building, language)
    return building


@on_server
def get_all_buildings_types(server, language=None):
    buildings = [building.as_dict() for building in BuildingType.objects.all().order_by('id')]

    if language:
        for i in range(len(buildings)):
            buildings[i]['name'] = localized_name(buildings[i], language)
    return buildings


@on_server
def get_all_buildable_buildings_types(server, commandant, language=None):
    buildings = get_all_buildings_types(server)

    # Remove unconstructibles buildings
    for building in buildings[:]:  # Duplicate buildings list to iterate correctly while removing entries
        if building['category'] == 'central_building':  # Central building are not buildable, only upgradable
            # TODO remove unbuildable buildings limited by tech too
            buildings.remove(building)

    # More info on resources cost and maintenance
    from data.resources import add_infos_to_resources_dict, get_resources_by_name
    resources = get_resources_by_name(server)
    for i in range(len(buildings)):
        buildings[i]['build_cost'] = add_infos_to_resources_dict(resources, buildings[i]['build_cost'], commandant, language)
        buildings[i]['maintenance'] = add_infos_to_resources_dict(resources, buildings[i]['maintenance'], commandant, language)
        production = {resource: quantity for resource, quantity in production_of(buildings[i]).items() if resource in resources}
        production = add_infos_to_resources_dict(resources, production, commandant, language)
        buildings[i]['resources_columns'] = (production, buildings[i]['build_cost'], buildings[i]['maintenance'])

        # Check if any resource is missing to build it
        buildings[i]['enough_stockpiles'] = True
        for resource_dict in buildings[i]['build_cost'].values():
            if not resource_dict['enough_stockpiles']:
                buildings[i]['enough_stockpiles'] = False
                break

    if language:
        for i in range(len(buildings)):
            buildings[i]['name'] = localized_name(buildings[i], language)

    return buildings


########################################################################################################################
# THE TREE OF THE UPGRADES


def _link_upgrades(group):
    # group : the buildings of one production, in the order of the Excel
    # shortcut: the Excel has no column for the upgrades, a building comes from the one it replaces : the latest of its
    # production still buildable when it appears, the nearest row of the Excel on a tie. A column upgrade_from in the
    # sheet Buildings_new (internal names separated by commas) overrides this guess, building by building.
    for building in group:
        explicit = [name.strip() for name in (building.get('upgrade_from') or '').split(',') if name.strip()]
        before = [other for other in group if other['level'] < building['level'] <= other['obsolete']]
        best = max(before, key=lambda other: (other['level'], -abs(other['order'] - building['order'])), default=None)
        building['parents'] = explicit or ([best['internal_name']] if best else [])


def _place_rows(group):
    # A building on the row of its first upgrade, the other upgrades below it, as the branches of a tree.
    # Returns the number of rows.
    names = {building['internal_name']: building for building in group}
    children, roots = defaultdict(list), []
    for building in group:
        # Only from a lower level : an upgrade_from going round in circles can't hang the layout
        parent = next((names[name] for name in building['parents']
                       if name in names and names[name]['level'] < building['level']), None)
        (children[parent['internal_name']] if parent else roots).append(building)

    rows = 0

    def place(building):
        nonlocal rows
        placed = [place(child) for child in children[building['internal_name']]]
        if placed:
            building['row'] = placed[0]
        else:
            building['row'], rows = rows, rows + 1
        return building['row']

    for root in roots:
        place(root)
    return rows


def _reach(name, neighbours):
    reached, todo = set(), [name]
    while todo:
        for other in neighbours[todo.pop()]:
            if other not in reached:
                reached.add(other)
                todo.append(other)
    return reached


@on_server
def buildings_tree(server, language, level, category=None, production=None, selected=None):
    # One category, one band per production (the sub-categories), the tech levels in columns. selected : a building
    # of the category, shown with its lineage only.
    from data.resources import get_resources_by_name

    buildings = [building.as_dict() for building in BuildingType.objects.order_by('id')]
    last = max((building.get('tech_available') or 0 for building in buildings), default=0)

    categories = {}
    for building in buildings:
        key = building.get('category') or ''
        categories.setdefault(key, CATEGORIES.get(key, {'name': key or gettext_lazy("Autres"), 'icon': 'fa-building'}))
    if category not in categories:
        category = next(iter(categories), None)

    technologies = {tech.internal_name: localized_name(tech.as_dict(), language) for tech in Technology.objects.all()}
    groups = {}  # production : its buildings, in the order of the Excel
    for order, building in enumerate(buildings):
        if (building.get('category') or '') != category:
            continue
        unlocked_by = building.get('unlocked_by_technology')
        building |= {
            'order': order,
            'group': building.get('production') or NO_PRODUCTION,
            'name': localized_name(building, language),
            'level': building.get('tech_available') or 0,
            'obsolete': building.get('tech_hidden') or last + 1,  # The first level where it can't be built anymore
            'technology': technologies.get(unlocked_by, unlocked_by),
        }
        building['levels'] = str(building['level']) if building['obsolete'] > last else f"{building['level']} – {building['obsolete'] - 1}"
        groups.setdefault(building['group'], []).append(building)

    resources = get_resources_by_name(server)
    productions = {key: localized_name(resources[key], language) if key in resources
                   else gettext_lazy("Sans production") if key == NO_PRODUCTION else key for key in groups}

    focus = next((building for group in groups.values() for building in group if building['internal_name'] == selected), None)
    if focus:
        production = focus['group']
    if production not in groups:
        production = None

    bands, next_row = [], 2  # Row 1 : the levels
    for key, group in groups.items():
        if production and key != production:
            continue
        _link_upgrades(group)
        if focus:
            up, down = defaultdict(list), defaultdict(list)
            for building in group:
                for parent in building['parents']:
                    up[building['internal_name']].append(parent)
                    down[parent].append(building['internal_name'])
            lineage = {selected} | _reach(selected, up) | _reach(selected, down)
            group = [building for building in group if building['internal_name'] in lineage]

        rows = _place_rows(group)
        for building in group:
            building['status'] = 'future' if building['level'] > level else 'past' if building['obsolete'] <= level else 'current'
            building['grid_row'] = next_row + building['row']
        statuses = {building['status'] for building in group}
        bands.append({'key': key, 'name': productions[key], 'buildings': group, 'grid_row': next_row, 'rows': rows,
                      'status': next(status for status in ('current', 'future', 'past') if status in statuses)})
        next_row += rows

    # Only the levels with a building, each as visible as its most visible building
    levels = sorted({building['level'] for band in bands for building in band['buildings']})
    for band in bands:
        for building in band['buildings']:
            building['grid_column'] = levels.index(building['level']) + 2  # Column 1 : the names of the bands
    levels = [{'level': column, 'grid_column': i + 2,
               'status': 'future' if column > level else 'current' if any(
                   building['level'] == column and building['status'] == 'current' for band in bands for building in band['buildings']) else 'past'}
              for i, column in enumerate(levels)]

    return {'categories': categories, 'selected_category': category, 'category_name': categories.get(category, {}).get('name'),
            'productions': productions, 'selected_production': production, 'production_name': productions.get(production),
            'focus': focus, 'bands': bands, 'levels': levels, 'level': level, 'all_levels': range(1, last + 1)}
