import inspect
import json
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import AnonymousUser, User
from django.core.cache import cache
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import Client, RequestFactory, SimpleTestCase, TestCase
from django.urls import Resolver404, resolve
from django.utils import timezone

from backend import views_game
from backend.decorators import commandant_required
from backend.login import LOGIN_MAX_FAILURES_PER_ACCOUNT, throttled_authenticate
from backend.models import CommandantAccount, Server, UserExtended, to_id
from database.schemas import schema_of, server_schema
from game.models import Building, Colony, Commandant, Coordinate, District, DistrictType, Report, StartingValues
from backend.utils import commandant_owns_colony
from data import server_details
from data import cycles
from data.commandant import civilisation_name_taken, commandant_name_taken, create_commandant, delete_commandant, get_commandant
from data.coordinates import get_coordinate_image
from data.districts import create_district, delete_district
from data.errors import GameError
from data.user import get_user_by_name
from data.report import change_report_status, delete_report, get_report
from data.resources import add_resources, pay_resources

API_LOGGED_URLS = ['/api_create_commandant/', '/api_build_district/', '/api_delete_district/',
                   '/api_district_set_activation_percent/']


def player():
    return MagicMock(username='real_player', is_authenticated=True, is_superuser=False)


def call(url, method='post', data=None, user=None):
    request = getattr(RequestFactory(), method)(url, data or {})
    request.user = user or AnonymousUser()
    return resolve(url).func(request)


class ApiRoutesTests(SimpleTestCase):

    def assertJson(self, response, status, redirect=None):
        self.assertEqual(response.status_code, status)
        self.assertEqual(json.loads(response.content).get('redirect'), redirect)

    def test_profile_routes_are_removed(self):
        for url in ('/get_user/', '/get_commandant/'):
            with self.assertRaises(Resolver404):
                resolve(url)

    def test_get_is_refused(self):
        for url in API_LOGGED_URLS + ['/create_user/']:
            self.assertEqual(call(url, method='get', user=player()).status_code, 405, url)

    def test_post_without_csrf_token_is_refused(self):
        client = Client(enforce_csrf_checks=True)
        for url in API_LOGGED_URLS + ['/create_user/']:
            self.assertEqual(client.post(url).status_code, 403, url)

    def test_expired_session_answers_json(self):
        for url in API_LOGGED_URLS:
            self.assertJson(call(url), 401, '/player_login/')

    @patch('backend.views_api_user.create_user_and_user_extend')
    @patch('backend.views_api_user.user_mail_already_used', return_value=False)
    @patch('backend.views_api_user.user_name_exist', return_value=False)
    def test_create_user_success(self, _name, _mail, create):
        response = call('/create_user/', data={'username': 'new_player', 'email': 'a@example.com', 'password': 'Xq7!vLp2mZ'})
        self.assertJson(response, 200, '/player_login/')
        create.assert_called_once()


@patch('backend.views_api_commandant.commandant.civilisation_name_taken', return_value=False)
@patch('backend.views_api_commandant.commandant.commandant_name_taken', return_value=False)
@patch('backend.views_api_commandant.commandant.create_commandant')
@patch('backend.views_api_commandant.server_details.get_server_details')
class ApiCreateCommandantTests(SimpleTestCase):

    data = {'server': 'S', 'user': 'victim', 'commandant_name': 'Commandant', 'civilisation_name': 'Civilisation'}

    def test_owner_comes_from_the_session(self, get_server, create, _name, _civilisation):
        get_server.return_value = {'server_name': 'S', 'status': 'open'}
        response = call('/api_create_commandant/', data=self.data, user=player())
        self.assertEqual(response.status_code, 200)
        create.assert_called_once_with('S', 'real_player', 'Commandant', 'Civilisation')

    def test_unknown_server_is_refused(self, get_server, create, _name, _civilisation):
        get_server.return_value = None
        self.assertEqual(call('/api_create_commandant/', data=self.data, user=player()).status_code, 400)
        create.assert_not_called()

    def test_closed_server_is_refused(self, get_server, create, _name, _civilisation):
        get_server.return_value = {'server_name': 'S', 'status': 'close'}
        self.assertEqual(call('/api_create_commandant/', data=self.data, user=player()).status_code, 400)
        create.assert_not_called()


class ApiDistrictsTests(SimpleTestCase):

    colony_id = 11
    commandant_id = 22

    def active(self):
        return patch('backend.views_api_buildings.get_active_server_and_commandant_from_request',
                     return_value=('S', {'id': self.commandant_id, 'colonies': [self.colony_id]}))

    @patch('backend.views_api_buildings.get_active_server_and_commandant_from_request', return_value=(None, None))
    def test_no_active_commandant_answers_json(self, _active):
        for url in ('/api_build_district/', '/api_delete_district/'):
            response = call(url, data={'colony_id': str(self.colony_id)}, user=player())
            self.assertEqual(json.loads(response.content)['redirect'], '/user_account/')
            self.assertEqual(response.status_code, 400)

    def test_foreign_colony_answers_json(self):
        with self.active():
            response = call('/api_delete_district/', data={'colony_id': '999'}, user=player())
        self.assertEqual(json.loads(response.content)['redirect'], '/colonies/')
        self.assertEqual(response.status_code, 400)

    @patch('backend.views_api_buildings.delete_district')
    @patch('backend.views_api_buildings.get_district')
    def test_delete_success(self, get_district, delete):
        district_id = '33'
        get_district.return_value = {'category': 'industry', 'colony': self.colony_id}
        with self.active():
            response = call('/api_delete_district/', user=player(),
                            data={'colony_id': str(self.colony_id), 'district_id': district_id})
        self.assertEqual(response.status_code, 200)
        delete.assert_called_once_with('S', self.commandant_id, district_id)


class LoginThrottleTests(SimpleTestCase):

    def setUp(self):
        cache.clear()

    def attempt(self, password='wrong', username='player'):
        request = RequestFactory().post('/player_login/', {'username': username, 'password': password})
        return throttled_authenticate(request)

    @patch('backend.login.authenticate', return_value=None)
    def test_account_is_blocked_after_too_many_failures(self, authenticate):
        for _ in range(LOGIN_MAX_FAILURES_PER_ACCOUNT):
            self.assertEqual(self.attempt()[0], None)
        calls = authenticate.call_count
        self.attempt(password='right')
        self.assertEqual(authenticate.call_count, calls)

    @patch('backend.login.authenticate', return_value=None)
    def test_another_account_is_not_blocked(self, authenticate):
        for _ in range(LOGIN_MAX_FAILURES_PER_ACCOUNT):
            self.attempt()
        calls = authenticate.call_count
        self.attempt(username='someone_else')
        self.assertEqual(authenticate.call_count, calls + 1)

    def test_success_resets_the_failures_of_the_account(self):
        with patch('backend.login.authenticate', return_value=None):
            for _ in range(LOGIN_MAX_FAILURES_PER_ACCOUNT - 1):
                self.attempt()
        with patch('backend.login.authenticate', return_value='user'):
            self.assertEqual(self.attempt(password='right'), ('user', None))
        with patch('backend.login.authenticate', return_value=None) as authenticate:
            self.attempt()
            self.attempt()
        self.assertEqual(authenticate.call_count, 2)


class GameViewsTests(SimpleTestCase):

    def commandant_view(self, view, url, method='get', data=None):
        request = getattr(RequestFactory(), method)(url, data or {})
        request.user = player()
        return inspect.unwrap(view)(request, 'S', {'id': 1, 'colonies': []})

    @patch('backend.decorators.get_active_server_and_commandant_from_request', return_value=(None, None))
    def test_commandant_required_redirects(self, _active):
        request = RequestFactory().get('/')
        view = MagicMock()
        self.assertEqual(commandant_required(view)(request).status_code, 302)
        view.assert_not_called()

    def test_colony_ownership(self):
        commandant = {'colonies': [5]}
        self.assertTrue(commandant_owns_colony(commandant, '5'))
        self.assertFalse(commandant_owns_colony(commandant, '6'))
        self.assertFalse(commandant_owns_colony(commandant, 'invalid'))
        self.assertFalse(commandant_owns_colony(commandant, None))

    @patch('backend.views_game.cycles')
    def test_cycle_actions_need_a_post(self, cycles):
        url = '/cycle_monitoring/?commandant_cycle_status=commandant_cycle_finished'
        self.commandant_view(views_game.cycle_monitoring, url)
        cycles.mark_commandant_cycle_finished.assert_not_called()
        self.commandant_view(views_game.cycle_monitoring, '/cycle_monitoring/', 'post', {'commandant_cycle_status': 'commandant_cycle_finished'})
        cycles.mark_commandant_cycle_finished.assert_called_once()

    @patch('backend.views_game.update_nb_unread_reports')
    @patch('backend.views_game.get_commandant_reports', return_value=([], {}))
    @patch('backend.views_game.delete_report')
    def test_report_actions_need_a_post_and_keep_the_owner(self, delete, _reports, _update):
        report_id = '7'
        self.commandant_view(views_game.reports, f'/reports/?action=delete&reports[]={report_id}')
        delete.assert_not_called()
        self.commandant_view(views_game.reports, '/reports/', 'post', {'action': 'delete', 'reports[]': report_id})
        self.assertEqual(delete.call_args[0][1], report_id)
        self.assertEqual(len(delete.call_args[0]), 3)


@patch('backend.views_game.get_commandants')
@patch('backend.views_game.get_colonies_at_coordinates', return_value=[])
@patch('backend.views_game.coordinates.get_coordinates_of_system')
@patch('backend.views_game.systems')
class SystemMapTests(SimpleTestCase):

    star = {'id': '100', 'type': 'star', 'subtype': 'G', 'name': 'Delea'}
    planet = {'id': '101', 'type': 'telluric', 'subtype': 'native', 'name': 'Danus'}

    def view(self, url):
        request = RequestFactory().get(url)
        request.user = player()
        self.commandant = {'id': 1, 'colonies': [], 'native_system': 'home'}
        return inspect.unwrap(views_game.geography_system)(request, 'S', self.commandant)

    def test_unknown_system_falls_back_on_the_native_one(self, systems, get_coordinates, _colonies, _owners):
        get_coordinates.return_value = [dict(self.star)]
        systems.get_system_by_seed.side_effect = lambda server, seed: {'id': seed} if seed == 'home' else None
        context = self.view('/geography_system/?system_id=999').context_data
        self.assertTrue(context['system_not_found'])
        self.assertEqual(context['system']['id'], 'home')

    def test_position_is_zero_padded(self, systems, get_coordinates, _colonies, _owners):
        get_coordinates.return_value = [dict(self.star)]
        self.view('/geography_system/?sector_id=1001&pos_y=65&pos_x=047')
        systems.get_system_by_position.assert_called_once_with('S', '1001', '065', '047')

    def test_colonies_land_on_their_coordinate(self, systems, get_coordinates, colonies, owners):
        get_coordinates.return_value = [dict(self.star), dict(self.planet)]
        owner = 2
        colonies.return_value = [{'id': 3, 'name': 'Siravedra', 'coordinate': '101', 'owner': owner}]
        owners.return_value = [{'id': owner, 'commandant_name': 'Kyu', 'civilisation_name': 'Entente'}]
        star, planet = self.view('/geography_system/').context_data['system_coordinates']
        self.assertEqual(star['colonies'], [])
        self.assertEqual(planet['colonies'][0]['owner_name'], 'Kyu')
        self.assertFalse(planet['has_my_colony'])


class CoordinateImageTests(SimpleTestCase):

    @patch('data.coordinates.images_in_folder', side_effect=lambda folder: [folder + '/a.png', folder + '/b.png'])
    def test_image_is_stable_and_follows_habitability(self, _images):
        native = {'id': '101', 'type': 'telluric', 'subtype': 'native'}
        self.assertEqual(get_coordinate_image(native), get_coordinate_image(native))
        self.assertRegex(get_coordinate_image(native), '^telluric/(habitable|ocean)/')

    @patch('data.coordinates.images_in_folder', return_value=[])
    def test_no_image_falls_back_on_the_placeholder(self, _images):
        coordinate = {'id': '100', 'type': 'star', 'subtype': 'G'}
        self.assertEqual(get_coordinate_image(coordinate), 'images/placeholder/star.png')


class ServersMenuTests(SimpleTestCase):

    @patch('data.server_details.get_servers_names', return_value=['Alpha'])
    def test_servers_menu_is_cached_until_refreshed(self, names):
        cache.clear()
        server_details.get_servers_menu()
        calls = names.call_count
        server_details.get_servers_menu()
        self.assertEqual(names.call_count, calls)
        server_details.refresh_servers_menu()
        server_details.get_servers_menu()
        self.assertGreater(names.call_count, calls)


def make_server(name):
    return server_details.create_server(name, 1, status='open', admin_only_visibility=False)


class GameRulesTests(TestCase):
    # On the real database : these rules rely on its schemas, constraints and row locks

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('player', 'p@example.com', 'x')
        make_server('S')
        make_server('Other')
        cls.commandant = cls.make_commandant('S', 'Paullus', 'Empire', resources={'steel': 100})
        with server_schema('S'):
            cls.colony = Colony.objects.create(name='Home', owner=cls.commandant, controller=cls.commandant,
                                               coordinate='100100000005505001', colony_type='start')
            for name, category, slots in (('central', 'central_district', 1), ('mine', 'mining', 0)):
                DistrictType.objects.create(internal_name=name, data={
                    'internal_name': name, 'category': category, 'districts_slots': slots, 'buildings_slots': 5,
                    'build_population': 10, 'hp': 100, 'build_cost': {'steel': 40}})

    @classmethod
    def make_commandant(cls, server, name, civilisation, resources=None):
        with server_schema(server):
            commandant = Commandant.objects.create(user=cls.user, commandant_name=name, civilisation_name=civilisation,
                                                   creation_date=timezone.now(), resources=resources or {})
        CommandantAccount.objects.create(server_id=server, commandant_id=commandant.id, user=cls.user, commandant_name=name)
        return commandant

    def stock(self):
        with server_schema('S'):
            return Commandant.objects.get(id=self.commandant.id).resources['steel']

    def test_ids_from_requests(self):
        self.assertEqual(to_id('12'), 12)
        for invalid in ('abc', '-1', '1 OR 1=1', '', None):
            self.assertIsNone(to_id(invalid))
        self.assertIsNone(get_report('S', 'abc', self.commandant.id))
        self.assertIsNone(get_report('S', '9' * 40, self.commandant.id))

    def test_servers_are_separated(self):
        self.assertIsNotNone(get_commandant('S', self.commandant.id))
        self.assertIsNone(get_commandant('Other', self.commandant.id))
        self.assertEqual(get_commandant('S', self.commandant.id)['server'], 'S')

    def test_game_tables_are_out_of_reach_outside_a_server(self):
        with self.assertRaises(DatabaseError), transaction.atomic():
            Commandant.objects.count()

    def test_schema_is_given_back_after_an_error(self):
        with self.assertRaises(ValueError):
            with server_schema('S'):
                raise ValueError
        with connection.cursor() as cursor:
            cursor.execute('SHOW search_path')
            self.assertEqual(cursor.fetchone()[0], '"TSS_main_server"')

    def test_server_name_can_not_escape_its_schema(self):
        with self.assertRaises(DatabaseError), transaction.atomic():
            get_commandant('S"; DROP TABLE auth_user; --', 1)
        self.assertTrue(User.objects.exists())

    def test_commandant_name_is_unique_on_every_server_whatever_the_case(self):
        self.assertTrue(commandant_name_taken('PAULLUS'))
        self.assertFalse(commandant_name_taken('Someone'))
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_commandant('Other', 'PAULLUS', 'Other civilisation')

    def test_civilisation_name_is_unique_by_server(self):
        self.assertTrue(civilisation_name_taken('S', 'EMPIRE'))
        self.assertFalse(civilisation_name_taken('Other', 'EMPIRE'))
        self.make_commandant('Other', 'Second', 'Empire')
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_commandant('S', 'Third', 'EMPIRE')

    def test_accounts_of_a_player(self):
        other = self.make_commandant('Other', 'Second', 'Empire')
        self.assertEqual(get_user_by_name('player')['accounts'], [('S', self.commandant.id), ('Other', other.id)])
        self.assertEqual(server_details.get_server_details('Other')['active_commandants'], [other.id])
        self.assertEqual(server_details.get_server_details('Other')['active_users'], [self.user.id])
        server_details.set_dead_commandant('Other', other.id)
        self.assertEqual(get_user_by_name('player')['dead_accounts'], [('Other', other.id)])
        self.assertEqual(server_details.get_server_details('Other')['dead_commandants'], [other.id])

    def test_deleting_a_commandant_removes_its_account(self):
        UserExtended.objects.update_or_create(user=self.user, defaults={'playing_on_server_id': 'S', 'playing_on_commandant': self.commandant.id})
        delete_commandant('S', self.commandant.id)
        self.assertFalse(commandant_name_taken('Paullus'))
        self.assertIsNone(get_user_by_name('player')['playing_on_commandant'])

    def test_payment(self):
        self.assertTrue(pay_resources('S', self.commandant.id, {'steel': 60, 'food': 0}))
        self.assertEqual(self.stock(), 40)
        self.assertFalse(pay_resources('S', self.commandant.id, {'steel': 41}))
        self.assertFalse(pay_resources('S', self.commandant.id, {'gold': 1}))
        self.assertEqual(self.stock(), 40)
        self.assertTrue(pay_resources('S', self.commandant.id, {}))
        self.assertFalse(pay_resources('Other', self.commandant.id, {'steel': 1}))
        add_resources('S', self.commandant.id, {'steel': 5, 'gold': 2})
        self.assertEqual(get_commandant('S', self.commandant.id)['resources'], {'steel': 45, 'gold': 2})

    def test_report_of_another_commandant_is_out_of_reach(self):
        other = self.make_commandant('S', 'Second', 'Other')
        with server_schema('S'):
            report = Report.objects.create(owner=self.commandant, category='other', category_icon='x', datetime=timezone.now(),
                                           tss_calendar=timezone.now(), title='t', message='m')
        self.assertIsNone(get_report('S', report.id, other.id))
        change_report_status('S', report.id, other.id, 'read')
        delete_report('S', report.id, other.id)
        self.assertEqual(get_report('S', report.id, self.commandant.id)['status'], 'unread')
        change_report_status('S', report.id, self.commandant.id, 'read')
        self.assertEqual(get_report('S', str(report.id), self.commandant.id)['status'], 'read')

    def test_district_slots(self):
        self.assertTrue(create_district('S', self.colony.id, 'central'))
        self.assertTrue(create_district('S', self.colony.id, 'mine'))
        self.assertFalse(create_district('S', self.colony.id, 'mine'))
        with server_schema('S'):
            colony = Colony.objects.get(id=self.colony.id)
            self.assertEqual(colony.districts.count(), 2)
            self.assertEqual((colony.districts_slots_total, colony.districts_slots_occupied), (1, 1))

    def test_deleting_a_district_refunds_once_and_removes_its_buildings(self):
        create_district('S', self.colony.id, 'central')
        create_district('S', self.colony.id, 'mine')
        with server_schema('S'):
            district = District.objects.get(category='mining')
            Building.objects.create(building_type='b', home_district=district)
        self.assertTrue(delete_district('S', self.commandant.id, district.id))
        self.assertFalse(delete_district('S', self.commandant.id, district.id))
        self.assertEqual(self.stock(), 130)  # 75 % of 40
        with server_schema('S'):
            self.assertFalse(Building.objects.exists())
            self.assertEqual(Colony.objects.get(id=self.colony.id).districts_slots_occupied, 0)

    def test_deleting_a_server_removes_its_schema_and_nothing_else(self):
        UserExtended.objects.update_or_create(user=self.user, defaults={'playing_on_server_id': 'S', 'playing_on_commandant': self.commandant.id})
        server_details.delete_server_details('S')
        with connection.cursor() as cursor:
            cursor.execute('SELECT schema_name FROM information_schema.schemata')
            schemas = [row[0] for row in cursor.fetchall()]
        self.assertNotIn(schema_of('S'), schemas)
        self.assertIn(schema_of('Other'), schemas)
        self.assertFalse(CommandantAccount.objects.exists())
        self.assertTrue(User.objects.filter(username='player').exists())
        user = get_user_by_name('player')
        self.assertEqual((user['playing_on_server'], user['playing_on_commandant']), (None, None))

    def test_cycles(self):
        cycles.create_cycle_entry('S')
        commandant_id = self.commandant.id
        self.assertEqual(cycles.get_current_cycle('S')['commandants_cycle_playing'], [commandant_id])
        cycles.mark_commandant_cycle_finished('S', commandant_id)
        cycle = cycles.get_current_cycle('S')
        self.assertEqual((cycle['commandants_cycle_playing'], cycle['commandants_cycle_finished']), ([], [commandant_id]))
        self.assertIsNotNone(get_commandant('S', commandant_id)['time_cycle_finished'])
        cycles.mark_commandant_cycle_absent('S', str(commandant_id))
        cycles.end_cycle('S')
        cycle = cycles.get_current_cycle('S')
        self.assertEqual(cycle['cycle_nb'], 2)
        self.assertEqual(cycle['commandants_cycle_absent'], [commandant_id])
        self.assertEqual(cycle['commandants_cycle_playing'], [])
        self.assertIsNone(get_commandant('S', commandant_id)['time_cycle_finished'])


class CreateCommandantTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('player', 'p@example.com', 'x')
        make_server('S')
        make_server('Other')
        cls.planets = [100100000005505001, 100100000007905001]
        for server in ('S', 'Other'):
            with server_schema(server):
                StartingValues.objects.create(start_type='default_land_colony', available_native_planets=cls.planets,
                                              starting_resources={'steel': 10})
                DistrictType.objects.create(internal_name='district_territory', data={
                    'category': 'central_district', 'districts_slots': 3, 'buildings_slots': 5, 'build_population': 10, 'hp': 100})
                for planet in cls.planets:
                    Coordinate.objects.create(seed=str(planet), type='telluric', sector_id='1', system_id='1',
                                              sys_y=1, sys_x=1, sys_coordinate=1, name='Planet')

    def planets_left(self, server='S'):
        with server_schema(server):
            return StartingValues.objects.get().available_native_planets

    def test_creation_links_everything_and_takes_the_planet(self):
        create_commandant('S', 'player', 'Paullus', 'Empire')
        with server_schema('S'):
            commandant = Commandant.objects.get().as_dict()
            self.assertEqual(Colony.objects.get().as_dict()['districts_slots_total'], 3)
        self.assertEqual(commandant['resources'], {'steel': 10})
        self.assertEqual(commandant['nb_unread_reports'], 1)
        left = self.planets_left()
        self.assertEqual(len(left), 1)
        self.assertNotIn(int(commandant['native_planet']), left)
        self.assertEqual(server_details.get_server_details('S')['active_commandants'], [commandant['id']])
        self.assertEqual(get_user_by_name('player')['accounts'], [('S', commandant['id'])])
        self.assertEqual(len(self.planets_left('Other')), 2)

    def test_name_taken_on_another_server_is_a_game_error_and_changes_nothing(self):
        create_commandant('S', 'player', 'Paullus', 'Empire')
        with self.assertRaises(GameError):
            create_commandant('Other', 'player', 'PAULLUS', 'Other')
        with server_schema('Other'):
            self.assertFalse(Commandant.objects.exists())
        self.assertEqual(len(self.planets_left('Other')), 2)

    def test_failure_midway_leaves_nothing_in_either_schema(self):
        with patch('data.report.generate_report', side_effect=ValueError):
            with self.assertRaises(ValueError):
                create_commandant('S', 'player', 'Paullus', 'Empire')
        self.assertFalse(CommandantAccount.objects.exists())
        with server_schema('S'):
            self.assertFalse(Commandant.objects.exists())
            self.assertFalse(Colony.objects.exists())
        self.assertEqual(len(self.planets_left()), 2)
