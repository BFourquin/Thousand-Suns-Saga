"""
One-shot copy of the old MongoDB databases into PostgreSQL. Run from the project root, after `manage.py migrate` :

    python -m pip install pymongo   (no longer a dependency of the game)
    python database/import_from_mongo.py [mongodb://127.0.0.1:27017/]

MongoDB is only read. Everything happens in one transaction, refused if PostgreSQL already holds a server.
Sessions are not copied : players have to log in again, their passwords are kept.
"""

import os
import sys
from datetime import timezone as utc

import django

sys.path.insert(0, os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_tss.settings')
django.setup()

import pymongo
from django.contrib.auth.models import User
from django.db import transaction

from backend.models import Building, BuildingType, Colony, Commandant, Coordinate, Cycle, District, DistrictType, \
    MapGeneratorParameter, Report, Resource, ResourceCategory, ResourceSubcategory, Sector, Server, StartingValues, \
    Statistic, System, Technology, UserExtended

NAMED_CONFIGURATION = {'resources': Resource, 'resources_categories': ResourceCategory,
                       'resources_subcategories': ResourceSubcategory, 'technologies': Technology,
                       'districts_types': DistrictType, 'buildings_types': BuildingType}
MAP_GENERATOR = {'map_generator': 'global', 'mg_sectors': 'sectors', 'mg_systems_types': 'systems_types',
                 'mg_systems_compositions': 'systems_compositions'}
ABANDONED = ('modifiers', 'ship_components', 'ship_designs', 'fleets', 'factions', 'mg_suns', 'mg_planets', 'reports')


def aware(value):
    # shortcut: dates written by datetime.now() were local time, they end up shifted by the timezone (old alpha data)
    return value.replace(tzinfo=utc.utc) if value and not value.tzinfo else value


def document(doc):
    return {key: value for key, value in doc.items() if key != '_id'}


def report_gap(collection, doc, reason):
    print('  SKIPPED', collection, doc['_id'], ':', reason)


def import_users(main):
    users = {}
    for doc in main['auth_user'].find():
        users[doc['_id']] = User.objects.create(
            username=doc['username'], password=doc['password'], email=doc['email'], first_name=doc['first_name'],
            last_name=doc['last_name'], is_superuser=doc['is_superuser'], is_staff=doc['is_staff'],
            is_active=doc['is_active'], date_joined=aware(doc['date_joined']), last_login=aware(doc['last_login']))
    return users


def import_configuration(mongo, name):
    for collection, model in NAMED_CONFIGURATION.items():
        rows = [document(doc) for doc in mongo[collection].find()]
        for row in rows:
            # The old Excel files declare this name twice, and find_one only ever returned the central one
            if collection == 'districts_types' and row['internal_name'] == 'district_industrial' and row['category'] == 'central_district':
                print('  RENAMED central district_industrial to district_industrialized')
                row['internal_name'] = 'district_industrialized'
        model.objects.bulk_create([model(server_id=name, internal_name=row['internal_name'], data=row) for row in rows])

    for collection, mg_type in MAP_GENERATOR.items():
        MapGeneratorParameter.objects.bulk_create(
            [MapGeneratorParameter(server_id=name, mg_type=mg_type, data=document(doc)) for doc in mongo[collection].find()])

    Statistic.objects.bulk_create([Statistic(server_id=name, stats_category=doc['stats_category'], stats=doc['stats'])
                                   for doc in mongo['statistics'].find()])

    for doc in mongo['starting_values'].find():
        StartingValues.objects.create(server_id=name, start_type=doc['start_type'],
                                      available_native_planets=doc['available_native_planets'],
                                      starting_resources=doc['starting_resources'],
                                      starting_capital=doc['starting_capital'],
                                      starting_territories=doc['starting_territories'],
                                      starting_modifiers=doc['starting_modifiers'],
                                      starting_factions=doc['starting_factions'],
                                      starting_technologies=doc['starting_technologies'])


def import_geography(mongo, name):
    Sector.objects.bulk_create([
        Sector(server_id=name, seed=doc['_id'], pos_y=doc['pos_y'], pos_x=doc['pos_x'], sector_type=doc['sector_type'],
               nb_systems=doc['nb_systems'], nb_natives_start=doc['nb_natives_start'],
               systems_coordinates=doc.get('systems_coordinates', [])) for doc in mongo['sectors'].find()])

    System.objects.bulk_create([
        System(server_id=name, seed=doc['_id'], system_type=doc['system_type'],
               system_coordinates=doc['system_coordinates'], sector_id=doc['sector_id'], pos_y=doc['pos_y'],
               pos_x=doc['pos_x']) for doc in mongo['systems'].find()])

    Coordinate.objects.bulk_create([
        Coordinate(server_id=name, seed=doc['_id'], type=doc['type'], subtype=doc['subtype'], sector_id=doc['sector_id'],
                   system_id=doc['system_id'], sys_y=doc['sys_y'], sys_x=doc['sys_x'],
                   sys_coordinate=doc['sys_coordinate'], name=doc['name'], fleet_modifiers=doc['fleet_modifiers'],
                   colony_modifiers=doc['colony_modifiers'], colonies=[str(id) for id in doc['colonies']])
        for doc in mongo['coordinates'].find()], batch_size=1000)


def import_players(mongo, name, users):
    # Each child row needs the new id of its parent. Orphans of the old database are reported and left behind.

    commandants = {}
    for doc in mongo['commandants'].find():
        if doc['user_id'] not in users:
            report_gap('commandants', doc, 'unknown user')
            continue
        commandants[doc['_id']] = Commandant.objects.create(
            server_id=name, user=users[doc['user_id']], commandant_name=doc['commandant_name'],
            civilisation_name=doc['civilisation_name'], gender=doc['gender'], portrait=doc['portrait'],
            flag=doc['flag'], status=doc['status'], creation_date=aware(doc['creation_date']),
            native_entente=doc['native_entente'], native_sector=doc['native_sector'],
            native_system=doc['native_system'], native_planet=doc['native_planet'], capital=doc['capital'],
            resources=doc['resources'], technologies=doc['technologies'], player_modifiers=doc['player_modifiers'],
            owned_ship_designs=doc['owned_ship_designs'], orientations=doc['orientations'],
            nb_unread_reports=doc['nb_unread_reports'], time_last_activity=aware(doc.get('time_last_activity')),
            time_cycle_finished=aware(doc.get('time_cycle_finished')), tutorial_step=doc.get('tutorial_step'))

    colonies = {}
    for doc in mongo['colonies'].find():
        if doc['owner'] not in commandants or doc['controller'] not in commandants:
            report_gap('colonies', doc, 'unknown commandant')
            continue
        colonies[doc['_id']] = Colony.objects.create(
            name=doc['name'], owner=commandants[doc['owner']], controller=commandants[doc['controller']],
            coordinate=doc['coordinate'], colony_type=doc['colony_type'],
            districts_slots_occupied=doc['districts_slots_occupied'], districts_slots_total=doc['districts_slots_total'])

    districts = {}
    district_fields = ('district_type', 'category', 'buildings_slots_free', 'buildings_slots_total', 'population',
                       'population_details', 'transports_needs', 'transports_cars_needs', 'transports_public_needs',
                       'transports_planes_needs', 'transports_spaceshuttles_needs', 'power_needs', 'power_satisfaction',
                       'hp', 'hp_max', 'damages')
    for doc in mongo['districts'].find():
        if doc['colony_id'] not in colonies:
            report_gap('districts', doc, 'unknown colony')
            continue
        districts[doc['_id']] = District.objects.create(colony=colonies[doc['colony_id']],
                                                        **{field: doc[field] for field in district_fields})

    building_fields = ('name_fr', 'name_en', 'building_type', 'local_modifiers', 'player_modifiers', 'faction_modifiers',
                       'activation_percent', 'last_cycle_missing_resources', 'last_cycle_production',
                       'last_cycle_productivity_percent')
    for doc in mongo['buildings'].find():
        if doc['home_district'] not in districts:
            report_gap('buildings', doc, 'unknown district')
            continue
        Building.objects.create(home_district=districts[doc['home_district']], **{field: doc[field] for field in building_fields})

    for doc in mongo['report'].find():
        if doc['owner'] not in commandants:
            report_gap('report', doc, 'unknown commandant')
            continue
        Report.objects.create(owner=commandants[doc['owner']], status=doc['status'], category=doc['category'],
                              category_icon=doc['category_icon'], datetime=aware(doc['datetime']),
                              tss_calendar=aware(doc['tss_calendar']), illustration=doc['illustration'],
                              title=doc['title'], message=doc['message'], sender=doc['sender'],
                              sender_image=doc['sender_image'])

    for doc in mongo['cycles'].find():
        cycle = Cycle.objects.create(server_id=name, cycle_nb=doc['cycle_nb'], datetime_start=aware(doc['datetime_start']),
                                     datetime_end=aware(doc['datetime_end']), datetime_planned_end=aware(doc['datetime_planned_end']))
        for field in Cycle.COMMANDANTS_LISTS:
            getattr(cycle, field).add(*[commandants[id] for id in doc[field] if id in commandants])

    return commandants


def check_counts(mongo, name):
    # Every document is either copied or was reported above, and PostgreSQL holds exactly what was read
    expected_exact = [('sectors', Sector), ('systems', System), ('coordinates', Coordinate), ('cycles', Cycle),
                      ('statistics', Statistic), ('starting_values', StartingValues)]
    expected_exact += list(NAMED_CONFIGURATION.items())
    for collection, model in expected_exact:
        copied, read = model.objects.filter(server=name).count(), mongo[collection].count_documents({})
        print(' ', collection, copied, '/', read)
        assert copied == read, collection

    for collection, model, owner in (('commandants', Commandant, 'server'), ('colonies', Colony, 'owner__server'),
                                     ('districts', District, 'colony__owner__server'),
                                     ('buildings', Building, 'home_district__colony__owner__server'),
                                     ('report', Report, 'owner__server')):
        copied, read = model.objects.filter(**{owner: name}).count(), mongo[collection].count_documents({})
        print(' ', collection, copied, '/', read, '' if copied == read else '(see SKIPPED above)')
        assert copied <= read, collection

    for collection, mg_type in MAP_GENERATOR.items():
        assert MapGeneratorParameter.objects.filter(server=name, mg_type=mg_type).count() == mongo[collection].count_documents({}), collection

    for collection in ABANDONED:
        if mongo[collection].count_documents({}):
            print('  WARNING :', collection, 'is not empty and has no table : not copied')


@transaction.atomic
def import_everything(client):
    if Server.objects.exists():
        sys.exit('PostgreSQL already holds servers : nothing done. This script only fills an empty database.')

    main = client['TSS_main_server']
    users = import_users(main)
    all_commandants = {}
    known_servers = set()

    for doc in main['server_details'].find():
        name = doc['server_name']
        known_servers.add('TSS_' + name)
        print('Server', name)
        Server.objects.create(server_name=name, version=doc['version'], gameplay=doc['gameplay'], status=doc['status'],
                              admin_only_visibility=doc['admin_only_visibility'], creation_date=aware(doc['creation_date']),
                              opening_date=aware(doc['opening_date']), end_date=aware(doc['end_date']),
                              language=doc['language'], roleplay=doc['roleplay'],
                              allow_multiaccounts=doc['allow_multiaccounts'], timezone=doc['timezone'])
        mongo = client['TSS_' + name]
        import_configuration(mongo, name)
        import_geography(mongo, name)
        all_commandants.update(import_players(mongo, name, users))
        check_counts(mongo, name)

    # Needs the commandants of every server
    for doc in main['auth_user_extended'].find():
        if doc['_id'] not in users:
            report_gap('auth_user_extended', doc, 'unknown user')
            continue
        # Stored as text by the old commandant_login view, unlike the other references
        playing_on = {str(id): commandant for id, commandant in all_commandants.items()}.get(str(doc.get('playing_on_commandant')))
        if not playing_on and doc.get('playing_on_commandant'):
            report_gap('auth_user_extended', doc, 'playing_on_commandant is unknown, reset')
        UserExtended.objects.create(user=users[doc['_id']], status=doc['status'], banned_until=aware(doc['banned_until']),
                                    banned_reason=doc['banned_reason'], language=doc['language'],
                                    dark_mode=doc['dark_mode'], theme=doc.get('theme', 'classic'),
                                    playing_on_server_id=playing_on.server_id if playing_on else None,
                                    playing_on_commandant=playing_on)

    assert User.objects.count() == main['auth_user'].count_documents({})
    print('Users', User.objects.count())

    for db_name in client.list_database_names():
        if db_name.startswith('TSS_') and db_name != 'TSS_main_server' and db_name not in known_servers:
            print('WARNING :', db_name, 'is not declared in server_details : not copied')


if __name__ == '__main__':
    import_everything(pymongo.MongoClient(sys.argv[1] if len(sys.argv) > 1 else 'mongodb://127.0.0.1:27017/',
                                          serverSelectionTimeoutMS=5000))
    print('Done.')
