from collections import defaultdict

from django.utils.translation import gettext as _, gettext_lazy

from data.names import localized_name
from game.models import BuildingType, Technology
from database.schemas import on_server
from data.technology import CIVILISATION_TECH_LEVEL, within_tech_level


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
def buildings_catalogue(server, commandant, language):
    # Every building type with what the trees of the colony page show of it, read once for the page
    from data.resources import add_infos_to_resources_dict, get_resources_by_name

    resources = get_resources_by_name(server)
    technologies = {tech.internal_name: localized_name(tech.as_dict(), language) for tech in Technology.objects.all()}
    catalogue = [building.as_dict() for building in BuildingType.objects.order_by('id')]
    last = max((building.get('tech_available') or 0 for building in catalogue), default=0)

    def text(infos):
        return ', '.join(' '.join(filter(None, (str(info['quantity']), info['unit_notation'], info['name']))) for info in infos.values())

    for order, building in enumerate(catalogue):
        unlocked_by = building.get('unlocked_by_technology')
        production = {resource: quantity for resource, quantity in production_of(building).items() if resource in resources}
        building |= {
            'order': order,
            'name': localized_name(building, language),
            'icon': building.get('icon') or CATEGORIES.get(building.get('category'), {}).get('icon', 'fa-building'),
            'level': building.get('tech_available') or 0,
            'obsolete': building.get('tech_hidden') or last + 1,  # The first level where it can't be built anymore
            'technology': technologies.get(unlocked_by, unlocked_by),
            'costs': add_infos_to_resources_dict(resources, dict(building.get('build_cost') or {}), commandant, language),
            'upkeep': add_infos_to_resources_dict(resources, dict(building.get('maintenance') or {}), commandant, language),
            'produces': add_infos_to_resources_dict(resources, production, commandant, language),
        }
        building['levels'] = str(building['level']) if building['obsolete'] > last else f"{building['level']} – {building['obsolete'] - 1}"
        building['status'] = 'obsolete' if building['obsolete'] <= CIVILISATION_TECH_LEVEL \
            else 'locked' if building['level'] > CIVILISATION_TECH_LEVEL else 'available'
        building['enough_stockpiles'] = all(cost['enough_stockpiles'] for cost in building['costs'].values())
        building['tooltip'] = '\n'.join(filter(None, (
            building['name'],
            _("Niveau %s") % building['levels'],
            building['produces'] and _("Produit : %s") % text(building['produces']),
            building['costs'] and _("Coût : %s") % text(building['costs']),
            building['upkeep'] and _("Entretien : %s") % text(building['upkeep']),
            building['technology'] and _("Débloqué par : %s") % building['technology'],
            {'obsolete': _("Obsolète"), 'locked': _("Niveau technologique insuffisant")}.get(building['status']),
            building['status'] == 'available' and not building['enough_stockpiles'] and _("Stock insuffisant"),
        )))
    return catalogue


########################################################################################################################
# THE TREES OF THE UPGRADES


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


def _place_lanes(group):
    # A building in the lane of its first upgrade, the other upgrades in the next lanes, as the branches of a tree.
    # Returns the number of lanes.
    names = {building['internal_name']: building for building in group}
    children, roots = defaultdict(list), []
    for building in group:
        # Only from a lower level : an upgrade_from going round in circles can't hang the layout
        parent = next((names[name] for name in building['parents']
                       if name in names and names[name]['level'] < building['level']), None)
        (children[parent['internal_name']] if parent else roots).append(building)

    lanes = 0

    def place(building):
        nonlocal lanes
        placed = [place(child) for child in children[building['internal_name']]]
        if placed:
            building['lane'] = placed[0]
        else:
            building['lane'], lanes = lanes, lanes + 1
        return building['lane']

    for root in roots:
        place(root)
    return lanes


def _reach(name, neighbours):
    reached, todo = set(), [name]
    while todo:
        for other in neighbours[todo.pop()]:
            if other not in reached:
                reached.add(other)
                todo.append(other)
    return reached


def _groups(catalogue, district_category):
    # The buildings a category of district takes : {category : {production : its buildings, linked}}
    groups = {}
    for building in catalogue:
        if building.get(district_category):
            groups.setdefault(building.get('category') or '', {}).setdefault(building.get('production') or NO_PRODUCTION, []).append(dict(building))
    for productions in groups.values():
        for group in productions.values():
            _link_upgrades(group)
    return groups


def _tree(group, current=None, targets=()):
    # Upright, as in Total War : the levels from the bottom up, the variants side by side. Selectable : what can be built,
    # or with a current building, what it can become.
    group = [dict(building) for building in group if building['status'] != 'obsolete' or building['internal_name'] == current]
    lanes = _place_lanes(group)
    levels = sorted({building['level'] for building in group}, reverse=True)
    for building in group:
        building |= {
            'grid_row': levels.index(building['level']) + 1,
            'grid_column': building['lane'] + 1,
            'current': building['internal_name'] == current,
            # A central building is never built, only upgraded
            'selectable': building['status'] == 'available' and building['enough_stockpiles'] and (
                building['internal_name'] in targets if current else building.get('category') != 'central_building'),
        }
    return {'buildings': group, 'columns': lanes}


def construction_trees(catalogue, district_category):
    # For a construction in a district : the categories, then their productions, then the tree of each production
    trees = []
    for category, productions in _groups(catalogue, district_category).items():
        shown = []
        for production, group in productions.items():
            tree = _tree(group)
            if tree['buildings']:
                name = next(iter(group[0]['produces'].values()), {}).get('name') or (_("Sans production") if production == NO_PRODUCTION else production)
                shown.append({'key': production, 'name': name, 'tree': tree})
        if shown:
            trees.append({'key': category, 'productions': shown} | CATEGORIES.get(category, {'name': category or _("Autres"), 'icon': 'fa-building'}))
    return trees


def upgrade_tree(catalogue, building_type, district_category):
    # The lineage of a building, where it stands framed. None when its district doesn't take it anymore.
    group = next((group for productions in _groups(catalogue, district_category).values() for group in productions.values()
                  if any(building['internal_name'] == building_type for building in group)), None)
    if not group:
        return None
    up, down = defaultdict(list), defaultdict(list)
    for building in group:
        for parent in building['parents']:
            up[building['internal_name']].append(parent)
            down[parent].append(building['internal_name'])
    descendants = _reach(building_type, down)
    lineage = {building_type} | _reach(building_type, up) | descendants
    return _tree([building for building in group if building['internal_name'] in lineage], building_type, descendants)
