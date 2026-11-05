import inspect
import json
from unittest.mock import MagicMock, patch

from bson.objectid import ObjectId
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import Client, RequestFactory, SimpleTestCase
from django.urls import Resolver404, resolve

from backend import views_game
from backend.decorators import commandant_required
from backend.login import LOGIN_MAX_FAILURES_PER_ACCOUNT, throttled_authenticate
from backend.utils import commandant_owns_colony
from data import server_details
from data.commandant import commandant_name_taken
from data.coordinates import get_coordinate_image
from data.report import change_report_status, get_report_by_object_id
from data.resources import pay_resources

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

    colony_id = ObjectId()
    commandant_id = ObjectId()

    def active(self):
        return patch('backend.views_api_buildings.get_active_server_and_commandant_from_request',
                     return_value=('S', {'_id': self.commandant_id, 'colonies': [self.colony_id]}))

    @patch('backend.views_api_buildings.get_active_server_and_commandant_from_request', return_value=(None, None))
    def test_no_active_commandant_answers_json(self, _active):
        for url in ('/api_build_district/', '/api_delete_district/'):
            response = call(url, data={'colony_id': str(self.colony_id)}, user=player())
            self.assertEqual(json.loads(response.content)['redirect'], '/user_account/')
            self.assertEqual(response.status_code, 400)

    def test_foreign_colony_answers_json(self):
        with self.active():
            response = call('/api_delete_district/', data={'colony_id': str(ObjectId())}, user=player())
        self.assertEqual(json.loads(response.content)['redirect'], '/colonies/')
        self.assertEqual(response.status_code, 400)

    @patch('backend.views_api_buildings.delete_district')
    @patch('backend.views_api_buildings.databases')
    def test_delete_success(self, databases, delete):
        district_id = str(ObjectId())
        databases['TSS_S']['districts'].find_one.return_value = {'category': 'industry', 'colony_id': self.colony_id}
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
        return inspect.unwrap(view)(request, 'S', {'_id': ObjectId(), 'colonies': []})

    @patch('backend.decorators.get_active_server_and_commandant_from_request', return_value=(None, None))
    def test_commandant_required_redirects(self, _active):
        request = RequestFactory().get('/')
        view = MagicMock()
        self.assertEqual(commandant_required(view)(request).status_code, 302)
        view.assert_not_called()

    def test_colony_ownership(self):
        colony_id = ObjectId()
        commandant = {'colonies': [colony_id]}
        self.assertTrue(commandant_owns_colony(commandant, str(colony_id)))
        self.assertFalse(commandant_owns_colony(commandant, str(ObjectId())))
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
        report_id = str(ObjectId())
        self.commandant_view(views_game.reports, f'/reports/?action=delete&reports[]={report_id}')
        delete.assert_not_called()
        self.commandant_view(views_game.reports, '/reports/', 'post', {'action': 'delete', 'reports[]': report_id})
        self.assertEqual(delete.call_args[0][1], report_id)
        self.assertEqual(len(delete.call_args[0]), 3)


@patch('backend.views_game.get_commandants_by_object_ids')
@patch('backend.views_game.get_colonies_at_coordinates', return_value=[])
@patch('backend.views_game.coordinates.get_coordinates_of_system')
@patch('backend.views_game.systems')
class SystemMapTests(SimpleTestCase):

    star = {'_id': '100', 'type': 'star', 'subtype': 'G', 'name': 'Delea'}
    planet = {'_id': '101', 'type': 'telluric', 'subtype': 'native', 'name': 'Danus'}

    def view(self, url):
        request = RequestFactory().get(url)
        request.user = player()
        self.commandant = {'_id': ObjectId(), 'colonies': [], 'native_system': 'home'}
        return inspect.unwrap(views_game.geography_system)(request, 'S', self.commandant)

    def test_unknown_system_falls_back_on_the_native_one(self, systems, get_coordinates, _colonies, _owners):
        get_coordinates.return_value = [dict(self.star)]
        systems.get_system_by_seed.side_effect = lambda server, seed: {'_id': seed} if seed == 'home' else None
        context = self.view('/geography_system/?system_id=999').context_data
        self.assertTrue(context['system_not_found'])
        self.assertEqual(context['system']['id'], 'home')

    def test_position_is_zero_padded(self, systems, get_coordinates, _colonies, _owners):
        get_coordinates.return_value = [dict(self.star)]
        self.view('/geography_system/?sector_id=1001&pos_y=65&pos_x=047')
        systems.get_system_by_position.assert_called_once_with('S', '1001', '065', '047')

    def test_colonies_land_on_their_coordinate(self, systems, get_coordinates, colonies, owners):
        # Colonies store the coordinate as an int, coordinates their id as a str
        get_coordinates.return_value = [dict(self.star), dict(self.planet)]
        owner = ObjectId()
        colonies.return_value = [{'_id': ObjectId(), 'name': 'Siravedra', 'coordinate': 101, 'owner': owner}]
        owners.return_value = [{'_id': owner, 'commandant_name': 'Kyu', 'civilisation_name': 'Entente'}]
        star, planet = self.view('/geography_system/').context_data['system_coordinates']
        self.assertEqual(star['colonies'], [])
        self.assertEqual(planet['colonies'][0]['owner_name'], 'Kyu')
        self.assertFalse(planet['has_my_colony'])


class CoordinateImageTests(SimpleTestCase):

    @patch('data.coordinates.images_in_folder', side_effect=lambda folder: [folder + '/a.png', folder + '/b.png'])
    def test_image_is_stable_and_follows_habitability(self, _images):
        native = {'_id': '101', 'type': 'telluric', 'subtype': 'native'}
        self.assertEqual(get_coordinate_image(native), get_coordinate_image(native))
        self.assertRegex(get_coordinate_image(native), '^telluric/(habitable|ocean)/')

    @patch('data.coordinates.images_in_folder', return_value=[])
    def test_no_image_falls_back_on_the_placeholder(self, _images):
        coordinate = {'_id': '100', 'type': 'star', 'subtype': 'G'}
        self.assertEqual(get_coordinate_image(coordinate), 'images/placeholder/star.png')


class DataLayerTests(SimpleTestCase):

    def test_commandant_name_is_searched_on_every_server(self):
        free_server, taken_server = MagicMock(), MagicMock()
        free_server['commandants'].find_one.return_value = None
        taken_server['commandants'].find_one.return_value = {'commandant_name': 'Paullus'}
        with patch('data.commandant.databases', {'TSS_A': free_server, 'TSS_B': taken_server}):
            self.assertTrue(commandant_name_taken('PAULLUS'))
        collation = free_server['commandants'].find_one.call_args[1]['collation'].document
        self.assertEqual(collation['strength'], 2)  # Case insensitive
        taken_server['commandants'].find_one.return_value = None
        with patch('data.commandant.databases', {'TSS_A': free_server, 'TSS_B': taken_server}):
            self.assertFalse(commandant_name_taken('Paullus'))

    @patch('data.resources.collection')
    def test_payment_is_a_single_conditional_query(self, collection):
        commandant_id = ObjectId()
        collection.return_value.update_one.return_value.modified_count = 1
        self.assertTrue(pay_resources('S', commandant_id, {'steel': 100, 'food': 0}))
        collection.return_value.update_one.assert_called_once_with(
            {'_id': commandant_id, 'resources.steel': {'$gte': 100}}, {'$inc': {'resources.steel': -100}})

    @patch('data.resources.collection')
    def test_payment_refused_when_nothing_matches(self, collection):
        collection.return_value.update_one.return_value.modified_count = 0
        self.assertFalse(pay_resources('S', ObjectId(), {'steel': 100}))

    @patch('data.resources.collection')
    def test_nothing_to_pay(self, collection):
        self.assertTrue(pay_resources('S', ObjectId(), {}))
        collection.assert_not_called()

    @patch('data.report.collection')
    def test_report_queries_filter_on_the_owner(self, collection):
        report_id, owner = ObjectId(), ObjectId()
        change_report_status('S', report_id, owner, 'read')
        self.assertEqual(collection.return_value.update_one.call_args[0][0], {'_id': report_id, 'owner': owner})
        self.assertIsNone(get_report_by_object_id('S', 'invalid', owner))
        get_report_by_object_id('S', report_id, owner)
        collection.return_value.find_one.assert_called_once_with({'_id': report_id, 'owner': owner})

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
