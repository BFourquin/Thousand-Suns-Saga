import inspect
import json
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import AnonymousUser, User
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import Client, RequestFactory, SimpleTestCase, TestCase
from django.urls import Resolver404, resolve
from django.utils import timezone

from backend import views_game
from backend.decorators import commandant_required
from backend.login import LOGIN_MAX_FAILURES_PER_ACCOUNT, throttled_authenticate
from backend.models import Building, Colony, Commandant, Coordinate, District, DistrictType, Report, Server, StartingValues, to_id
from backend.utils import commandant_owns_colony
from data import server_details
from data import cycles
from data.commandant import civilisation_name_taken, commandant_name_taken, create_commandant
from data.coordinates import get_coordinate_image
from data.districts import create_district, delete_district
from data.errors import GameError
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


class GameRulesTests(TestCase):
    # On the real database : these rules rely on its constraints and row locks

    def setUp(self):
        self.user = User.objects.create_user('player', 'p@example.com', 'x')
        self.server = self.make_server('S')
        self.commandant = self.make_commandant(self.server, 'Paullus', 'Empire', resources={'steel': 100})
        self.colony = Colony.objects.create(name='Home', owner=self.commandant, controller=self.commandant,
                                            coordinate='100100000005505001', colony_type='start')
        for name, category, slots in (('central', 'central_district', 1), ('mine', 'mining', 0)):
            DistrictType.objects.create(server=self.server, internal_name=name, data={
                'internal_name': name, 'category': category, 'districts_slots': slots, 'buildings_slots': 5,
                'build_population': 10, 'hp': 100, 'build_cost': {'steel': 40}})

    def make_server(self, name):
        return Server.objects.create(server_name=name, version=1, gameplay='saga', status='open', language='fr', roleplay='HRP',
                                     creation_date=timezone.now(), opening_date=timezone.now(), timezone='Europe/Paris')

    def make_commandant(self, server, name, civilisation, resources=None):
        return Commandant.objects.create(server=server, user=self.user, commandant_name=name, civilisation_name=civilisation,
                                         creation_date=timezone.now(), resources=resources or {})

    def stock(self):
        return Commandant.objects.get(id=self.commandant.id).resources['steel']

    def test_ids_from_requests(self):
        self.assertEqual(to_id('12'), 12)
        for invalid in ('abc', '-1', '1 OR 1=1', '', None):
            self.assertIsNone(to_id(invalid))
        self.assertIsNone(get_report('S', 'abc', self.commandant.id))
        self.assertIsNone(get_report('S', '9' * 40, self.commandant.id))

    def test_commandant_name_is_unique_on_every_server_whatever_the_case(self):
        other = self.make_server('Other')
        self.assertTrue(commandant_name_taken('PAULLUS'))
        self.assertFalse(commandant_name_taken('Someone'))
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_commandant(other, 'PAULLUS', 'Other civilisation')

    def test_civilisation_name_is_unique_by_server(self):
        other = self.make_server('Other')
        self.assertTrue(civilisation_name_taken('S', 'EMPIRE'))
        self.assertFalse(civilisation_name_taken('Other', 'EMPIRE'))
        self.make_commandant(other, 'Second', 'Empire')
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_commandant(self.server, 'Third', 'EMPIRE')

    def test_payment(self):
        self.assertTrue(pay_resources('S', self.commandant.id, {'steel': 60, 'food': 0}))
        self.assertEqual(self.stock(), 40)
        self.assertFalse(pay_resources('S', self.commandant.id, {'steel': 41}))
        self.assertFalse(pay_resources('S', self.commandant.id, {'gold': 1}))
        self.assertEqual(self.stock(), 40)
        self.assertTrue(pay_resources('S', self.commandant.id, {}))
        self.assertFalse(pay_resources('Other', self.commandant.id, {'steel': 1}))
        add_resources('S', self.commandant.id, {'steel': 5, 'gold': 2})
        self.assertEqual(Commandant.objects.get(id=self.commandant.id).resources, {'steel': 45, 'gold': 2})

    def test_report_of_another_commandant_is_out_of_reach(self):
        other = self.make_commandant(self.server, 'Second', 'Other')
        report = Report.objects.create(owner=self.commandant, category='other', category_icon='x', datetime=timezone.now(),
                                       tss_calendar=timezone.now(), title='t', message='m')
        self.assertIsNone(get_report('S', report.id, other.id))
        change_report_status('S', report.id, other.id, 'read')
        delete_report('S', report.id, other.id)
        self.assertEqual(Report.objects.get(id=report.id).status, 'unread')
        change_report_status('S', report.id, self.commandant.id, 'read')
        self.assertEqual(get_report('S', str(report.id), self.commandant.id)['status'], 'read')

    def test_district_slots(self):
        self.assertTrue(create_district('S', self.colony.id, 'central'))
        self.assertEqual(Colony.objects.get(id=self.colony.id).districts_slots_total, 1)
        self.assertTrue(create_district('S', self.colony.id, 'mine'))
        self.assertFalse(create_district('S', self.colony.id, 'mine'))
        self.assertEqual(self.colony.districts.count(), 2)
        self.assertEqual(Colony.objects.get(id=self.colony.id).districts_slots_occupied, 1)

    def test_deleting_a_district_refunds_once_and_removes_its_buildings(self):
        create_district('S', self.colony.id, 'central')
        create_district('S', self.colony.id, 'mine')
        district = self.colony.districts.get(category='mining')
        Building.objects.create(building_type='b', home_district=district)
        self.assertTrue(delete_district('S', self.commandant.id, district.id))
        self.assertFalse(delete_district('S', self.commandant.id, district.id))
        self.assertEqual(self.stock(), 130)  # 75 % of 40
        self.assertFalse(Building.objects.exists())
        self.assertEqual(Colony.objects.get(id=self.colony.id).districts_slots_occupied, 0)

    def test_deleting_a_server_removes_all_its_content(self):
        create_district('S', self.colony.id, 'central')
        Server.objects.filter(pk='S').delete()
        for model in (Commandant, Colony, District, DistrictType):
            self.assertFalse(model.objects.exists(), model)

    def test_cycles(self):
        cycles.create_cycle_entry('S')
        commandant_id = self.commandant.id
        self.assertEqual(cycles.get_current_cycle('S')['commandants_cycle_playing'], [commandant_id])
        cycles.mark_commandant_cycle_finished('S', commandant_id)
        cycle = cycles.get_current_cycle('S')
        self.assertEqual((cycle['commandants_cycle_playing'], cycle['commandants_cycle_finished']), ([], [commandant_id]))
        self.assertIsNotNone(Commandant.objects.get(id=commandant_id).time_cycle_finished)
        cycles.mark_commandant_cycle_absent('S', str(commandant_id))
        cycles.end_cycle('S')
        cycle = cycles.get_current_cycle('S')
        self.assertEqual(cycle['cycle_nb'], 2)
        self.assertEqual(cycle['commandants_cycle_absent'], [commandant_id])
        self.assertEqual(cycle['commandants_cycle_playing'], [])
        self.assertIsNone(Commandant.objects.get(id=commandant_id).time_cycle_finished)


class CreateCommandantTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('player', 'p@example.com', 'x')
        Server.objects.create(server_name='S', version=1, gameplay='saga', status='open', language='fr', roleplay='HRP',
                              creation_date=timezone.now(), opening_date=timezone.now(), timezone='Europe/Paris')
        self.planets = [100100000005505001, 100100000007905001]
        StartingValues.objects.create(server_id='S', start_type='default_land_colony', available_native_planets=self.planets,
                                      starting_resources={'steel': 10})
        DistrictType.objects.create(server_id='S', internal_name='district_territory', data={
            'category': 'central_district', 'districts_slots': 3, 'buildings_slots': 5, 'build_population': 10, 'hp': 100})
        for planet in self.planets:
            Coordinate.objects.create(server_id='S', seed=str(planet), type='telluric', sector_id='1', system_id='1',
                                      sys_y=1, sys_x=1, sys_coordinate=1, name='Planet')

    def test_creation_links_everything_and_takes_the_planet(self):
        create_commandant('S', 'player', 'Paullus', 'Empire')
        commandant = Commandant.objects.get().as_dict()
        self.assertEqual(commandant['resources'], {'steel': 10})
        self.assertEqual(commandant['nb_unread_reports'], 1)
        self.assertEqual(Colony.objects.get().as_dict()['districts_slots_total'], 3)
        left = StartingValues.objects.get().available_native_planets
        self.assertEqual(len(left), 1)
        self.assertNotIn(int(commandant['native_planet']), left)
        self.assertEqual(server_details.get_server_details('S')['active_commandants'], [commandant['id']])
        self.assertEqual(server_details.get_server_details('S')['active_users'], [self.user.id])

    def test_taken_name_is_a_game_error_and_changes_nothing(self):
        create_commandant('S', 'player', 'Paullus', 'Empire')
        with self.assertRaises(GameError):
            create_commandant('S', 'player', 'PAULLUS', 'Other')
        self.assertEqual(Commandant.objects.count(), 1)
        self.assertEqual(len(StartingValues.objects.get().available_native_planets), 1)

    def test_failure_midway_leaves_nothing(self):
        with patch('data.report.generate_report', side_effect=ValueError):
            with self.assertRaises(ValueError):
                create_commandant('S', 'player', 'Paullus', 'Empire')
        self.assertFalse(Commandant.objects.exists())
        self.assertFalse(Colony.objects.exists())
        self.assertEqual(len(StartingValues.objects.get().available_native_planets), 2)
