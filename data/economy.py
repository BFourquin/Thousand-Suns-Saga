from collections import Counter

from game.models import Building, BuildingType, Commandant, District, DistrictType, Resource
from database.schemas import on_server
from data.buildings_types import production_of
from data.modifiers import active_modifiers, commandant_target, district_targets, modified_production
from data.report import create_report
from data.technology import CIVILISATION_TECH_LEVEL


# The native column of the Excel reads : 'needs for 1Mo pop per tech level'
POPULATION_UNIT = 1_000_000
NOT_A_NEED_CATEGORIES = ('resources_cat_illicits',)  # A demand that a civilisation is free to leave unanswered


def _pay(stock, needs, consumed, missing):
    # Takes what is available and returns the fraction of the needs which was covered
    covered = 1
    for resource, quantity in needs.items():
        taken = min(stock.get(resource, 0), quantity)
        if taken:
            stock[resource] -= taken
            consumed[resource] += taken
        if taken < quantity:
            missing[resource] += quantity - taken
            covered = min(covered, taken / quantity)
    return covered


def _feed_population(stock, population, resources, consumed, missing):
    level_column = f'pop_consumption_{CIVILISATION_TECH_LEVEL}'
    foods = []

    for resource in resources:
        rate = resource.data.get(level_column) or 0
        if not rate or resource.data.get('category') in NOT_A_NEED_CATEGORIES:
            continue
        if resource.data.get('sub_category') == 'food':
            foods.append((resource.internal_name, rate))
        else:
            _pay(stock, {resource.internal_name: population * rate}, consumed, missing)

    # The foods replace each other, in the order of the Excel. What can't be eaten is displayed on the first one.
    if foods:
        hunger = population * max(rate for _, rate in foods)
        for resource, _ in foods:
            taken = min(stock.get(resource, 0), hunger)
            if taken:
                stock[resource] -= taken
                consumed[resource] += taken
                hunger -= taken
        if hunger:
            missing[foods[0][0]] += hunger


def economy_tables():
    # What all the commandants share : read once at the end of a cycle, not once per commandant
    return {'resources': list(Resource.objects.order_by('id')),
            'district_types': {row.internal_name: row.data for row in DistrictType.objects.all()},
            'building_types': {row.internal_name: row.data for row in BuildingType.objects.all()}}


@on_server
def cycle_balance(server, commandant_id, resources, tables=None):
    # What a passing of cycle does to these resources. Reads only : it also gives the forecast of the resources page.
    #
    # All the maintenances come first, the oldest districts being served first when the stock runs out. Then all the
    # productions : what is produced can only be spent by the population during the same cycle.

    stock = dict(resources)
    produced, consumed, missing = Counter(), Counter(), Counter()
    buildings = []

    districts = District.objects.filter(colony__controller=commandant_id).order_by('id').select_related('colony').prefetch_related('buildings')
    tables = tables or economy_tables()
    known_resources = {resource.internal_name for resource in tables['resources']}
    district_types, building_types = tables['district_types'], tables['building_types']
    targets_of_districts = {district.id: commandant_target(commandant_id) | district_targets(district) for district in districts}
    modifiers = active_modifiers(server, {target for targets in targets_of_districts.values() for target in targets})

    for district in districts:
        # A district without maintenance slows down everything it holds
        district_type = district_types.get(district.district_type, {})
        district_covered = _pay(stock, district_type.get('maintenance') or {}, consumed, missing)

        for building in sorted(district.buildings.all(), key=lambda row: row.id):
            building_type = building_types.get(building.building_type, {})
            activation = building.activation_percent / 100
            building_missing = Counter()
            maintenance = {resource: quantity * activation for resource, quantity in (building_type.get('maintenance') or {}).items()}
            covered = _pay(stock, maintenance, consumed, building_missing)
            missing.update(building_missing)
            buildings.append({
                'building': building,
                'building_type': building_type,
                'targets': targets_of_districts[district.id],
                'productivity': activation * covered * district_covered,
                'missing': dict(building_missing),
            })

    for row in buildings:
        row['production'] = 0
        for resource, quantity in production_of(row['building_type']).items():
            production = modified_production(modifiers, row['targets'], resource, quantity) * row['productivity']
            if production and resource in known_resources:  # Some rows of the Excel still name it in plain text
                row['production'] = production
                produced[resource] += production
                stock[resource] = stock.get(resource, 0) + production

    population = sum(district.population or 0 for district in districts) / POPULATION_UNIT
    _feed_population(stock, population, tables['resources'], consumed, missing)

    return {'stock': stock, 'produced': produced, 'consumed': consumed, 'missing': missing, 'buildings': buildings}


@on_server
def apply_cycle_economy(server):
    # Inside the transaction of the end of the cycle : a failure on one commandant cancels it for everyone

    tables = economy_tables()

    for commandant in Commandant.objects.select_for_update().filter(status='active').order_by('id'):
        balance = cycle_balance(server, commandant.id, commandant.resources, tables)

        commandant.resources = {resource: round(quantity, 6) for resource, quantity in balance['stock'].items()}
        commandant.save(update_fields=['resources'])

        updated_buildings = []
        for row in balance['buildings']:
            building = row['building']
            building.last_cycle_production = row['production']
            building.last_cycle_productivity_percent = row['productivity'] * 100
            building.last_cycle_missing_resources = row['missing']
            updated_buildings.append(building)
        Building.objects.bulk_update(updated_buildings, ['last_cycle_production', 'last_cycle_productivity_percent',
                                                         'last_cycle_missing_resources'])

        if balance['produced'] or balance['consumed'] or balance['missing']:
            create_report(server, commandant.id, 'cycle_economy', {key: dict(balance[key]) for key in ('produced', 'consumed', 'missing')})
