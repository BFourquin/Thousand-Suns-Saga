from collections import defaultdict

from django.db import transaction
from django.utils.translation import gettext as _, gettext_lazy

from database.schemas import on_server
from data.errors import GameError
from data.names import localized_name
from data.report import create_report
from data.resources import add_infos_to_resources_dict, pay_resources
from game.models import Commandant, Technology


# The values of the column tech_type of the Excel. A new value still gets its page, named as in the Excel.
CATEGORIES = {
    'social': {'name': gettext_lazy("Société"), 'icon': 'fa-people-group'},
    'biology': {'name': gettext_lazy("Biologie"), 'icon': 'fa-dna'},
    'industry': {'name': gettext_lazy("Industrie"), 'icon': 'fa-industry'},
    'energetic': {'name': gettext_lazy("Énergie"), 'icon': 'fa-bolt'},
    'electronic': {'name': gettext_lazy("Électronique"), 'icon': 'fa-microchip'},
    'nanorobotic': {'name': gettext_lazy("Nanorobotique"), 'icon': 'fa-robot'},
    'neumann': {'name': gettext_lazy("Von Neumann"), 'icon': 'fa-satellite'},
}

# The values of the column tech_level of the Excel
ERAS = (gettext_lazy("Époque coloniale"), "Low-Tech", "Middle-Tech", "High-Tech", "Ultra-Tech", gettext_lazy("Singularité"))

STATUS = {
    'researched': {'name': gettext_lazy("Recherchée"), 'icon': 'fa-check'},
    'researching': {'name': gettext_lazy("En cours"), 'icon': 'fa-hourglass-half'},
    'available': {'name': gettext_lazy("Disponible"), 'icon': 'fa-flask'},
    'locked': {'name': gettext_lazy("Verrouillée"), 'icon': 'fa-lock'},
}

# shortcut: the columns price and difficulty of the Excel are still empty, each technology costs this until they are filled
DEFAULT_PRICE_RESOURCE = 'merchandises_low_tech'
DEFAULT_PRICE_PER_ERA = 2


def _requisites(tech):
    return [name.strip() for name in (tech.get('requisite') or '').split(',') if name.strip()]


def _in_progress(researches):
    # researches : Commandant.technologies, {internal_name : cycles left}, 0 once researched
    return next((name for name, cycles_left in researches.items() if cycles_left), None)


def _status(tech, researches):
    cycles_left = researches.get(tech['internal_name'])
    if cycles_left == 0:
        return 'researched'
    if cycles_left:
        return 'researching'
    return 'available' if all(researches.get(name) == 0 for name in tech['requisites']) else 'locked'


@on_server
def technologies_of_commandant(server, researches, language):
    # All the technologies in the order of the Excel, where a requisite comes before what needs it
    technologies = {}

    for row in Technology.objects.order_by('id'):
        tech = row.as_dict()
        tech['requisites'] = _requisites(tech)

        # Without a level in the Excel, it stays in the era of what it requires
        level = tech.get('tech_level')
        if level is None:
            level = max((technologies[name]['level'] for name in tech['requisites'] if name in technologies), default=0)

        status = _status(tech, researches)
        tech |= {
            'name': localized_name(tech, language) or tech.get('name'),
            'level': level,
            'era': ERAS[level] if level < len(ERAS) else str(level),
            'category': CATEGORIES.get(tech.get('tech_type'), {'name': tech.get('tech_type'), 'icon': 'fa-flask'}),
            'price': tech.get('price') or {DEFAULT_PRICE_RESOURCE: DEFAULT_PRICE_PER_ERA * (level + 1)},
            'cycles': tech.get('difficulty') or level + 1,
            'status': status,
            'status_display': STATUS[status],
            'cycles_left': researches.get(tech['internal_name']),
        }
        technologies[tech['internal_name']] = tech

    return technologies


########################################################################################################################
# THE TREE OF ONE CATEGORY


def _place_nodes(nodes):
    # Rows : the longest chain of requisites inside the era. Columns : each node below the middle of those which need it,
    # its first requisite of the page being the one it hangs from, or else in the next free spot of its row.
    # Returns the number of columns.

    def row_of(node):
        same_era = [nodes[name] for name in node['parents'] if nodes[name]['level'] == node['level']]
        return 1 + max(map(row_of, same_era)) if same_era else 0

    children, roots = defaultdict(list), []
    for name, node in nodes.items():
        node['row'] = row_of(node)
        local_parents = [parent for parent in node['parents'] if not nodes[parent]['foreign']]
        parent = next(iter(local_parents or node['parents']), None)
        (children[parent] if parent else roots).append(name)

    next_free = defaultdict(int)

    def place(name):
        node = nodes[name]
        columns = [place(child) for child in children[name]]
        spot = (node['level'], node['row'])
        wanted = round(min(columns) + max(columns)) / 2 if columns else 0  # In half columns : the grid has 2 tracks per column
        column = max(wanted, next_free[spot])
        next_free[spot] = column + 1
        node['grid_column'] = int(column * 2) + 1
        return column

    for root in roots:
        place(root)
    return max(next_free.values(), default=0)


@on_server
def research_tree(server, commandant, language, selected=None):
    researches = commandant['technologies']
    technologies = technologies_of_commandant(server, researches, language)

    categories = {}
    for tech in technologies.values():
        categories.setdefault(tech.get('tech_type'), tech['category'])
    if selected not in categories:
        selected = next(iter(categories), None)

    # A requisite from another category stands on the page as a small icon, before the first technology needing it
    nodes = {}
    for name, tech in technologies.items():
        tech['foreign'] = tech.get('tech_type') != selected
        tech['parents'] = []
        if not tech['foreign']:
            for requisite in tech['requisites']:
                if requisite in technologies and technologies[requisite].get('tech_type') != selected:
                    nodes.setdefault(requisite, technologies[requisite])
            nodes[name] = tech

    for name, tech in nodes.items():
        if not tech['foreign']:
            # A technology requiring itself can't be researched, but must not hang the layout
            tech['parents'] = [requisite for requisite in tech['requisites'] if requisite in nodes and requisite != name]
        tech['requisites_details'] = [technologies[requisite] for requisite in tech['requisites'] if requisite in technologies]
        tech['costs'] = add_infos_to_resources_dict(server, dict(tech['price']), commandant, language)
        tech['enough_stockpiles'] = all(cost['enough_stockpiles'] for cost in tech['costs'].values())

    columns = int(_place_nodes(nodes) * 2)

    levels = {node['level'] for node in nodes.values()}
    frontier = max((node['level'] for node in nodes.values() if node['status'] != 'locked'), default=min(levels, default=0))

    eras = []
    for level in sorted(levels, reverse=True):  # Latest on top : the tree reads from the bottom
        era_nodes = [node for node in nodes.values() if node['level'] == level]
        nb_researched = sum(node['status'] == 'researched' for node in era_nodes)
        rows = max(node['row'] for node in era_nodes) + 1
        for node in era_nodes:
            node['grid_row'] = rows - node['row']
        eras.append({
            'name': era_nodes[0]['era'],
            'nodes': era_nodes,
            'nb_researched': nb_researched,
            'kind': 'future' if level > frontier else 'past' if level < frontier and nb_researched == len(era_nodes) else 'open',
        })

    current = _in_progress(researches)
    return {'categories': categories, 'selected_category': selected, 'eras': eras, 'techs': nodes.values(), 'columns': columns,
            'current_research': technologies.get(current)}


########################################################################################################################
# RESEARCHING


@on_server
@transaction.atomic
def start_research(server, commandant_id, internal_name, language):
    commandant = Commandant.objects.select_for_update().get(id=commandant_id)
    tech = technologies_of_commandant(server, commandant.technologies, language).get(internal_name)

    if not tech:
        raise GameError(_("Technologie inconnue"))
    if _in_progress(commandant.technologies):
        raise GameError(_("Une recherche est déjà en cours"))
    if tech['status'] != 'available':
        raise GameError(_("Cette technologie n'est pas disponible"))
    if not pay_resources(server, commandant_id, tech['price']):
        raise GameError(_("Ressources insuffisantes"))

    commandant.technologies[internal_name] = tech['cycles']
    commandant.save(update_fields=['technologies'])
    return tech


@on_server
def apply_cycle_research(server):
    # Inside the transaction of the end of the cycle : a failure on one commandant cancels it for everyone

    for commandant in Commandant.objects.select_for_update().filter(status='active').order_by('id'):
        internal_name = _in_progress(commandant.technologies)
        if internal_name:
            commandant.technologies[internal_name] -= 1
            commandant.save(update_fields=['technologies'])
            if not commandant.technologies[internal_name]:
                create_report(server, commandant.id, 'research_finished', {'technology': internal_name})
