import gzip
import inspect
import json
import random
from collections import Counter
from datetime import datetime, timedelta, timezone as dt_timezone
from importlib import import_module
from unittest.mock import MagicMock, patch

from dateutil import tz
from django.apps import apps
from django.contrib.auth.models import AnonymousUser, User
from django.core.management import call_command
from django.core.cache import cache
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.models import Sum
from django.test import Client, RequestFactory, SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import Resolver404, resolve
from django.utils import timezone

from anticheat.models import ActionLog, Alert, LoginLog, Scan
from anticheat.rules import alternating_accounts, bots, purge_old_logs, refused_actions, scan_due_servers, shared_ip
from backend import views_game
from backend.decorators import commandant_required, log_player_action
from backend.login import LOGIN_MAX_FAILURES_PER_ACCOUNT, throttled_authenticate
from backend.models import SERVER_HOURS, CommandantAccount, ScheduledRun, Server, UserExtended, to_id
from backend.templatetags.tss_dates import rp_date
from backend.templatetags.tss_text import MAX_DEPTH, bbcode
from database.schemas import schema_of, server_schema
from game.models import Building, BuildingType, Colony, Commandant, Cycle, ConversationMessage, Coordinate, District, DistrictType, Entente, EntenteMember, EntenteRole, Modifier, Post, Report, Resource, Sector, StartingValues, System, Technology, Zone
from backend.utils import commandant_owns_colony
from data import conversations, ententes, forums, locations, quadrants
from data import server_details
from data import cycles
from data.admin import raise_alert, set_alert_open
from data.buildings import construct_building
from data.buildings_types import is_buildable
from data.colonies import recalculate_districts_slots
from data.commandant import civilisation_name_taken, commandant_name_taken, create_commandant, delete_commandant, get_commandant, pick_home
from data.coordinates import get_coordinate_image
from data.districts import create_district, delete_district
from data.economy import cycle_balance
from data.errors import GameError
from data.modifiers import add_modifier
from data.schedule import blocking_run, last_due, run_due_steps, unblock
from data.user import get_user_by_name
from geography import galaxy, map_generator as geography_map
from geography.name_generator import ROMAN
from geography.map_generator import excel_importer
from data.report import change_report_status, delete_report, get_commandant_reports, get_report, mark_all_reports_as_read, update_nb_unread_reports
from data.resources import add_resources, pay_resources

API_LOGGED_URLS = ['/api_create_commandant/', '/api_build_district/', '/api_build_building/', '/api_delete_district/',
                   '/api_district_set_activation_percent/', '/api_start_research/', '/api_building_set_activation_percent/',
                   '/api_upgrade_building/', '/api_destroy_building/', '/api_relocate_building/']


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

    def setUp(self):
        patcher = patch('backend.api_ui_interactions.orders_closed', return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        journal = patch('backend.decorators.get_active_server_and_commandant_from_request', return_value=(None, None))
        journal.start()
        self.addCleanup(journal.stop)

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
        patcher = patch('backend.login.log_login')
        patcher.start()
        self.addCleanup(patcher.stop)

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

    def view(self, url, native_system='home'):
        request = RequestFactory().get(url)
        request.user = player()
        self.commandant = {'id': 1, 'colonies': [], 'native_system': native_system, 'recent_places': [], 'favourite_places': []}
        with patch('data.commandant.remember_place') as remember:  # Its own tests : MapPlacesTests
            response = inspect.unwrap(views_game.geography_system)(request, 'S', self.commandant)
        remember.assert_called_once()
        return response

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

    def test_a_system_is_found_by_its_readable_place(self, systems, get_coordinates, _colonies, _owners):
        get_coordinates.return_value = [dict(self.star)]
        self.view('/geography_system/?system_id=f4-55.12-3', native_system='1001000000050050')  # A body : its system
        systems.get_system_by_seed.assert_called_once_with('S', '1001003005012055')

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


class ForumsTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('player', 'p@example.com', 'x')
        cls.other_user = User.objects.create_user('other_player', 'o@example.com', 'x')
        cls.staff = User.objects.create_user('staff', 's@example.com', 'x', is_staff=True, is_superuser=True)
        make_server('S')
        make_server('Other')
        with server_schema('S'):
            cls.owner, cls.visitor, cls.staff_commandant = [
                Commandant.objects.create(user=user, commandant_name=name, civilisation_name=name, creation_date=timezone.now()).id
                for user, name in ((cls.user, 'Paullus'), (cls.other_user, 'Varro'), (cls.staff, 'Censeur'))]
        cycles.create_cycle_entry('S')

    def setUp(self):
        self.assembly_id = forums.get_forum_id('S', 'assembly')

    def play(self, user, commandant_id):
        UserExtended.objects.update_or_create(user=user, defaults={'playing_on_server_id': 'S', 'playing_on_commandant': commandant_id,
                                                                   'language': 'fr'})
        self.client.force_login(user)

    def private_forum(self):
        return forums.create_player_forum('S', self.owner, 'Le Repaire', '', True)

    def invitations(self, commandant_id):
        return sum(forums.get_forum_badges('S', commandant_id)[kind] for kind in ('player', 'coalition'))

    def age_messages(self, model, minutes):
        with server_schema('S'):
            model.objects.update(datetime=timezone.now() - timedelta(minutes=minutes))

    # Forums of the server

    def test_each_server_has_its_assembly_and_its_hrp_forum(self):
        for kind in ('assembly', 'hrp'):
            self.assertTrue(forums.get_forum('S', forums.get_forum_id('S', kind), self.owner)['can_post'])
        forums.create_topic('S', self.assembly_id, self.owner, 'Discours', 'Citoyens...')
        self.assertEqual(forums.get_topics('Other', forums.get_forum_id('Other', 'assembly'), 1, self.owner).paginator.count, 0)

    def test_hrp_forum_only_exists_without_mandatory_roleplay(self):
        hrp_id = forums.get_forum_id('S', 'hrp')
        topic_id = forums.create_topic('S', hrp_id, self.owner, 'Bug', 'Texte')
        self.play(self.user, self.owner)
        response = self.client.get('/communication/')
        self.assertContains(response, 'href="/hrp/"')
        self.assertEqual(response.context['nb_communication'], 1)

        server_details.change_server_param('S', 'roleplay', 'RP')
        self.assertIsNone(forums.get_forum('S', hrp_id, self.owner))
        self.assertIsNone(forums.get_topic('S', topic_id, self.owner))
        with self.assertRaises(GameError), transaction.atomic():
            forums.reply_to_topic('S', topic_id, self.owner, 'Texte')
        response = self.client.get('/communication/')
        self.assertNotContains(response, 'href="/hrp/"')
        self.assertEqual(response.context['nb_communication'], 0)
        self.assertEqual(self.client.get('/hrp/', follow=True).redirect_chain[-1][0], '/player_forums/')

    def test_private_forum_stays_closed_to_the_others(self):
        forum_id = self.private_forum()
        topic_id = forums.create_topic('S', forum_id, self.owner, 'Secret', 'Le plan')
        post_id = forums.get_posts('S', topic_id, 1, self.owner)[0]['id']
        self.assertIsNone(forums.get_forum('S', forum_id, self.visitor))
        self.assertIsNone(forums.get_topic('S', topic_id, self.visitor))
        self.assertEqual(forums.get_player_forums('S', self.visitor)['others'], [])
        for refused in (lambda: forums.create_topic('S', forum_id, self.visitor, 'Hop', 'Hop'),
                        lambda: forums.reply_to_topic('S', topic_id, self.visitor, 'Hop'),
                        lambda: forums.flag_post('S', post_id, self.visitor, ''),
                        lambda: forums.join_forum('S', forum_id, self.visitor),
                        lambda: forums.delete_topic('S', topic_id, self.visitor, False),
                        # The staff can't moderate what it can't read
                        lambda: forums.delete_topic('S', topic_id, self.visitor, True),
                        lambda: forums.invite_to_forum('S', forum_id, self.visitor, 'Varro'),
                        lambda: forums.destroy_player_forum('S', forum_id, self.visitor)):
            with self.assertRaises(GameError), transaction.atomic():
                refused()

    def test_invitation_opens_a_private_forum(self):
        forum_id = self.private_forum()
        forums.invite_to_forum('S', forum_id, self.owner, 'varro')  # Whatever the case
        self.assertEqual(self.invitations(self.visitor), 1)
        self.assertIsNone(forums.get_forum('S', forum_id, self.visitor))  # Not before accepting

        forums.answer_invitation('S', forum_id, self.visitor, True)
        self.assertEqual(self.invitations(self.visitor), 0)
        self.assertTrue(forums.get_forum('S', forum_id, self.visitor)['can_post'])

    def test_banned_member_reads_a_public_forum_but_stays_out(self):
        forum_id = forums.create_player_forum('S', self.owner, 'La Cantine', '', False)
        self.assertFalse(forums.get_forum('S', forum_id, self.visitor)['can_post'])
        forums.join_forum('S', forum_id, self.visitor)
        self.assertTrue(forums.get_forum('S', forum_id, self.visitor)['can_post'])

        forums.remove_from_forum('S', forum_id, self.owner, self.visitor)
        self.assertFalse(forums.get_forum('S', forum_id, self.visitor)['can_post'])
        with self.assertRaises(GameError):
            forums.join_forum('S', forum_id, self.visitor)

        forums.remove_from_forum('S', forum_id, self.owner, self.visitor)  # Lifts the ban
        forums.join_forum('S', forum_id, self.visitor)
        self.assertTrue(forums.get_forum('S', forum_id, self.visitor)['can_post'])

    def test_owner_stays_in_his_forum(self):
        forum_id = forums.create_player_forum('S', self.owner, 'La Cantine', '', False)
        forums.leave_forum('S', forum_id, self.owner)
        forums.remove_from_forum('S', forum_id, self.owner, self.owner)
        self.assertEqual(forums.get_forum('S', forum_id, self.owner)['membership'], 'member')

    def test_forum_name_is_unique_whatever_the_case(self):
        forum_id = forums.create_player_forum('S', self.owner, 'La Cantine', '', False)
        with self.assertRaises(GameError), transaction.atomic():
            forums.create_player_forum('S', self.visitor, 'LA CANTINE', '', False)
        other_id = forums.create_player_forum('S', self.visitor, 'Le Port', '', False)
        with self.assertRaises(GameError):
            forums.update_player_forum('S', other_id, self.visitor, 'la cantine', '', False)
        self.assertEqual(forums.get_forum('S', forum_id, self.owner)['name'], 'La Cantine')

    def test_a_commandant_owns_five_taverns_at_most(self):
        for number in range(forums.MAX_OWNED_TAVERNS):
            last_id = forums.create_player_forum('S', self.owner, f'Taverne {number}', '', False)
        with self.assertRaises(GameError), transaction.atomic():
            forums.create_player_forum('S', self.owner, 'Une de trop', '', False)

        self.play(self.user, self.owner)
        self.assertContains(self.client.get('/player_forums/'), 'maximum de 5 tavernes')
        self.assertNotContains(self.client.get('/player_forums/'), 'value="create"')

        forums.create_player_forum('S', self.visitor, 'Celle de Varro', '', False)  # Each one has its own limit
        forums.create_coalition('S', self.owner, 'La Ligue')  # A coalition is no tavern
        forums.destroy_player_forum('S', last_id, self.owner)  # And a destroyed one gives its place back
        forums.create_player_forum('S', self.owner, 'Une de plus', '', False)

    def test_ambiance_text(self):
        forum_id = forums.create_player_forum('S', self.owner, 'La Cantine', '', False)
        forums.update_player_forum('S', forum_id, self.owner, 'La Cantine', 'Une odeur de friture.', False)
        self.assertEqual(forums.get_forum('S', forum_id, self.owner)['description'], 'Une odeur de friture.')

        with self.assertRaises(GameError):
            forums.update_forum_ambiance('S', self.assembly_id, False, 'Pirate')
        forums.update_forum_ambiance('S', forum_id, True, 'Pirate')  # The team's text is only for the forums without owner
        self.assertEqual(forums.get_forum('S', forum_id, self.owner)['description'], 'Une odeur de friture.')

        url = f'/forum/?forum_id={self.assembly_id}'
        self.play(self.user, self.owner)
        self.client.post(url, {'action': 'save_ambiance', 'ambiance': 'Pirate'})
        self.assertNotContains(self.client.get(url), 'Pirate')
        self.assertNotContains(self.client.get(url), 'name="ambiance"')
        self.assertNotContains(self.client.get(url), 'font-italic')  # No text by default

        self.play(self.staff, self.staff_commandant)
        self.client.post(url, {'action': 'save_ambiance', 'ambiance': 'La coupole résonne.'})
        self.assertContains(self.client.get(url), 'La coupole résonne.')
        self.assertContains(self.client.get(url), 'name="ambiance"')

    def test_deleting_the_last_post_removes_the_topic(self):
        topic_id = forums.create_topic('S', self.assembly_id, self.owner, 'Discours', 'Un')
        forums.reply_to_topic('S', topic_id, self.visitor, 'Deux')
        first, second = forums.get_posts('S', topic_id, 1, self.owner)
        with self.assertRaises(GameError):
            forums.delete_post('S', second['id'], self.visitor, False)  # Nobody moderates the assembly but the staff

        self.assertTrue(forums.delete_post('S', second['id'], self.visitor, True))
        topic_row = forums.get_topics('S', self.assembly_id, 1, self.owner)[0]
        self.assertEqual((topic_row['nb_replies'], topic_row['last_author_name']), (0, 'Paullus'))
        self.assertFalse(forums.delete_post('S', first['id'], self.visitor, True))
        self.assertIsNone(forums.get_topic('S', topic_id, self.owner))

    def test_invalid_texts_are_refused(self):
        for title, body in (('', 'Texte'), ('Titre', '   '), ('x' * 151, 'Texte'), ('Titre', 'x' * 20001), ('\x00', 'Texte')):
            with self.assertRaises(GameError), transaction.atomic():
                forums.create_topic('S', self.assembly_id, self.owner, title, body)
        self.assertEqual(forums.get_topics('S', self.assembly_id, 1, self.owner).paginator.count, 0)

    # Edition of a message

    def test_edit_keeps_the_previous_versions(self):
        topic_id = forums.create_topic('S', self.assembly_id, self.owner, 'Discours', 'Premiere version')
        post_id = forums.get_posts('S', topic_id, 1, self.owner)[0]['id']

        forums.edit_post('S', post_id, self.owner, 'Première version')
        forums.edit_post('S', post_id, self.owner, 'Première version')  # Unchanged : no new version
        forums.edit_post('S', post_id, self.owner, 'Tout autre chose')

        post = forums.get_posts('S', topic_id, 1, self.visitor)[0]  # Everybody can check
        self.assertEqual(post['body'], 'Tout autre chose')
        self.assertEqual([version['body'] for version in post['previous_versions']], ['Premiere version', 'Première version'])

        self.play(self.other_user, self.visitor)
        response = self.client.get(f'/topic/?topic_id={topic_id}')
        self.assertContains(response, 'Premiere version')
        self.assertContains(response, 'versions précédentes')

    def test_only_the_author_edits_during_fifteen_minutes(self):
        topic_id = forums.create_topic('S', self.assembly_id, self.owner, 'Discours', 'Texte')
        post_id = forums.get_posts('S', topic_id, 1, self.owner)[0]['id']
        url = f'/topic/?topic_id={topic_id}'

        for commandant_id in (self.visitor, self.staff_commandant):
            self.assertFalse(forums.get_posts('S', topic_id, 1, commandant_id)[0]['can_edit'])
            with self.assertRaises(GameError), transaction.atomic():
                forums.edit_post('S', post_id, commandant_id, 'Pirate')
        with self.assertRaises(GameError), transaction.atomic():
            forums.edit_post('S', post_id, self.owner, '   ')

        self.play(self.user, self.owner)
        self.assertContains(self.client.get(url), f'name="edit_post" value="{post_id}"')
        self.client.post(url, {'edit_post': post_id, f'edited_body_{post_id}': 'Corrigé'})
        self.assertEqual(forums.get_posts('S', topic_id, 1, self.owner)[0]['body'], 'Corrigé')

        self.age_messages(Post, 14)
        self.assertTrue(forums.get_posts('S', topic_id, 1, self.owner)[0]['can_edit'])
        self.age_messages(Post, 16)  # Even with an edit a few minutes ago : the delay counts from the sending
        self.assertFalse(forums.get_posts('S', topic_id, 1, self.owner)[0]['can_edit'])
        self.assertNotContains(self.client.get(url), 'name="edit_post"')
        self.assertContains(self.client.post(url, {'edit_post': post_id, f'edited_body_{post_id}': 'Trop tard'}), 'ne peut plus être modifié')
        self.assertEqual(forums.get_posts('S', topic_id, 1, self.owner)[0]['body'], 'Corrigé')

    def test_banned_member_can_not_edit_anymore(self):
        forum_id = forums.create_player_forum('S', self.owner, 'La Cantine', '', False)
        forums.join_forum('S', forum_id, self.visitor)
        topic_id = forums.create_topic('S', forum_id, self.visitor, 'Sujet', 'Texte')
        post_id = forums.get_posts('S', topic_id, 1, self.visitor)[0]['id']
        forums.remove_from_forum('S', forum_id, self.owner, self.visitor)
        with self.assertRaises(GameError), transaction.atomic():
            forums.edit_post('S', post_id, self.visitor, 'Pirate')

    def test_private_message_can_be_edited_with_the_same_rules(self):
        conversation_id = conversations.start_conversation('S', self.owner, 'Varro', 'Pacte', 'Premiere version')
        message_id = conversations.get_messages('S', conversation_id, 1, self.owner)[0]['id']
        with self.assertRaises(GameError), transaction.atomic():
            conversations.edit_message('S', message_id, self.visitor, 'Pirate')

        url = f'/conversation/?conversation_id={conversation_id}'
        self.play(self.user, self.owner)
        self.client.post(url, {'edit_post': message_id, f'edited_body_{message_id}': 'Première version'})
        message = conversations.get_messages('S', conversation_id, 1, self.visitor)[0]
        self.assertEqual(message['body'], 'Première version')
        self.assertEqual(message['previous_versions'][0]['body'], 'Premiere version')

        self.age_messages(ConversationMessage, 16)
        with self.assertRaises(GameError), transaction.atomic():
            conversations.edit_message('S', message_id, self.owner, 'Trop tard')

    # Unread topics

    def test_topic_is_unread_until_its_last_post_is_displayed(self):
        topic_id = forums.create_topic('S', self.assembly_id, self.owner, 'Discours', 'Texte')
        for number in range(forums.POSTS_PER_PAGE):  # 2 pages
            forums.reply_to_topic('S', topic_id, self.owner, f'Réponse {number}')
        is_unread = lambda: forums.get_topics('S', self.assembly_id, 1, self.visitor)[0]['is_unread']
        url = f'/topic/?topic_id={topic_id}'
        self.play(self.other_user, self.visitor)

        self.assertTrue(is_unread())
        self.assertEqual(forums.get_forum_badges('S', self.visitor)['assembly'], 1)
        self.client.get(url)  # Only the first page
        self.assertTrue(is_unread())

        # The link of an unread topic goes to the first page with something new
        self.assertRedirects(self.client.get(url + '&page=unread'), url + '&page=2')
        self.assertFalse(is_unread())
        self.assertEqual(forums.get_forum_badges('S', self.visitor)['assembly'], 0)

        self.client.get(url)  # Coming back to the beginning unreads nothing
        self.assertFalse(is_unread())

        forums.reply_to_topic('S', topic_id, self.owner, 'Du nouveau')
        self.assertTrue(is_unread())
        self.assertEqual(forums.get_forum_badges('S', self.owner)['assembly'], 1)  # Paullus hasn't opened it yet

    def test_author_has_read_what_he_just_wrote(self):
        self.play(self.user, self.owner)
        url = f'/forum/?forum_id={self.assembly_id}'
        response = self.client.post(url, {'action': 'new_topic', 'title': 'Discours', 'body': 'Texte'}, follow=True)
        topic_url = response.redirect_chain[-1][0]
        self.assertEqual(forums.get_forum_badges('S', self.owner)['assembly'], 0)
        self.client.post(topic_url, {'body': 'Suite'}, follow=True)
        self.assertEqual(forums.get_forum_badges('S', self.owner)['assembly'], 0)

    def test_all_the_topics_of_a_forum_can_be_marked_as_read(self):
        for number in range(3):
            forums.create_topic('S', self.assembly_id, self.owner, f'Sujet {number}', 'Texte')
        self.assertEqual(forums.get_forum_badges('S', self.visitor)['assembly'], 3)

        self.play(self.other_user, self.visitor)
        self.client.post(f'/forum/?forum_id={self.assembly_id}', {'action': 'mark_as_read'})
        self.assertEqual(forums.get_forum_badges('S', self.visitor)['assembly'], 0)
        forums.mark_forum_as_read('S', self.assembly_id, self.visitor)  # Twice changes nothing

    def test_only_the_forums_of_a_member_count_as_unread(self):
        forum_id = forums.create_player_forum('S', self.owner, 'La Cantine', '', False)
        forums.create_topic('S', forum_id, self.owner, 'Sujet', 'Texte')
        self.assertEqual(forums.get_forum_badges('S', self.visitor)['player'], 0)
        forums.join_forum('S', forum_id, self.visitor)
        self.assertEqual(forums.get_forum_badges('S', self.visitor)['player'], 1)
        self.assertEqual(forums.get_player_forums('S', self.visitor)['member'][0]['nb_unread'], 1)
        forums.remove_from_forum('S', forum_id, self.owner, self.visitor)
        self.assertEqual(forums.get_forum_badges('S', self.visitor)['player'], 0)

    # Reports to the team

    def test_flag_keeps_what_the_message_said(self):
        topic_id = forums.create_topic('S', self.assembly_id, self.owner, 'Discours', 'Insulte')
        post_id = forums.get_posts('S', topic_id, 1, self.visitor)[0]['id']
        self.assertTrue(forums.get_posts('S', topic_id, 1, self.visitor)[0]['can_flag'])
        self.assertFalse(forums.get_posts('S', topic_id, 1, self.owner)[0]['can_flag'])  # Not one's own message
        with self.assertRaises(GameError):
            forums.flag_post('S', post_id, self.owner, '')

        self.play(self.other_user, self.visitor)
        url = f'/topic/?topic_id={topic_id}'
        self.client.post(url, {'flag_post': post_id, f'flag_reason_{post_id}': 'Propos injurieux'})
        self.client.post(url, {'flag_post': post_id, f'flag_reason_{post_id}': 'Encore'})  # Counted once
        self.assertContains(self.client.get(url), "Signalé à l'équipe")
        self.assertEqual(forums.count_open_flags('S'), 1)

        forums.edit_post('S', post_id, self.owner, 'Bonjour')  # Hiding it afterwards is useless
        flag = forums.get_flags('S')['open'][0]
        self.assertEqual((flag['body'], flag['author_name'], flag['reports'][0]['reason'], flag['reports'][0]['reporter_name']),
                         ('Insulte', 'Paullus', 'Propos injurieux', 'Varro'))
        self.assertIn('Discours', flag['location'])

    def test_private_message_can_be_flagged_by_its_members_only(self):
        conversation_id = conversations.start_conversation('S', self.owner, 'Varro', 'Pacte', 'Menace')
        message_id = conversations.get_messages('S', conversation_id, 1, self.visitor)[0]['id']
        with self.assertRaises(GameError):
            conversations.flag_message('S', message_id, self.staff_commandant, '')
        with self.assertRaises(GameError):
            conversations.flag_message('S', message_id, self.owner, '')  # Its author

        conversations.flag_message('S', message_id, self.visitor, '')
        self.assertEqual(forums.get_flags('S')['open'][0]['body'], 'Menace')

    def test_team_handles_the_flags_from_the_administration(self):
        topic_id = forums.create_topic('S', self.assembly_id, self.owner, 'Discours', 'Insulte')
        forums.reply_to_topic('S', topic_id, self.owner, 'Normal')
        insult_id, normal_id = [post['id'] for post in forums.get_posts('S', topic_id, 1, self.visitor)]
        forums.flag_post('S', insult_id, self.visitor, '')
        forums.flag_post('S', normal_id, self.visitor, '')
        conversation_id = conversations.start_conversation('S', self.owner, 'Varro', 'Pacte', 'Menace')
        conversations.flag_message('S', conversations.get_messages('S', conversation_id, 1, self.visitor)[0]['id'], self.visitor, '')
        url = '/admin_message_flags/?server_name_selected=S'

        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.post(url, {'action': 'close', 'server': 'S', 'flag_id': forums.get_flags('S')['open'][0]['id']})
        self.assertEqual(forums.count_open_flags('S'), 3)

        self.play(self.staff, self.staff_commandant)
        self.assertContains(self.client.get('/assembly/', follow=True), 'href="/admin_main_dashboard/"')
        self.assertContains(self.client.get(url), 'Menace')
        flags = {flag['body']: flag['id'] for flag in forums.get_flags('S')['open']}

        self.client.post(url, {'action': 'close', 'server': 'S', 'flag_id': flags['Normal']})
        self.assertEqual(len(forums.get_posts('S', topic_id, 1, self.visitor)), 2)

        self.client.post(url, {'action': 'delete_message', 'server': 'S', 'flag_id': flags['Insulte']})
        self.assertEqual([post['body'] for post in forums.get_posts('S', topic_id, 1, self.visitor)], ['Normal'])

        self.client.post(url, {'action': 'delete_message', 'server': 'S', 'flag_id': flags['Menace']})
        self.assertIsNone(conversations.get_conversation('S', conversation_id, self.owner))  # Its only message

        closed = forums.get_flags('S')['closed']
        self.assertEqual(forums.count_open_flags('S'), 0)
        self.assertEqual({flag['handled_by'] for flag in closed}, {'staff'})
        self.assertContains(self.client.get(url), 'Insulte')  # Still readable afterwards
        self.assertRedirects(self.client.get('/admin_message_flags/?server_name_selected=unknown'), '/admin_servers_states/', fetch_redirect_response=False)

    def test_reports_are_counted_by_message_on_all_the_servers(self):
        topic_id = forums.create_topic('S', self.assembly_id, self.owner, 'Discours', 'Grosse insulte')
        forums.reply_to_topic('S', topic_id, self.owner, 'Petite pique')
        big_id, small_id = [post['id'] for post in forums.get_posts('S', topic_id, 1, self.visitor)]
        forums.flag_post('S', big_id, self.visitor, 'Injurieux')
        forums.flag_post('S', big_id, self.staff_commandant, '')
        forums.flag_post('S', small_id, self.visitor, '')
        conversation_id = conversations.start_conversation('S', self.owner, 'Varro', 'Pacte', 'Menace privée')
        conversations.flag_message('S', conversations.get_messages('S', conversation_id, 1, self.visitor)[0]['id'], self.visitor, '')

        with server_schema('Other'):
            far_author, far_reporter = [Commandant.objects.create(user=user, commandant_name=name, civilisation_name=name, creation_date=timezone.now()).id
                                        for user, name in ((self.user, 'Lointain'), (self.other_user, 'Voisin'))]
        far_topic_id = forums.create_topic('Other', forums.get_forum_id('Other', 'assembly'), far_author, 'Ailleurs', 'Autre serveur')
        forums.flag_post('Other', forums.get_posts('Other', far_topic_id, 1, far_reporter)[0]['id'], far_reporter, '')

        # Messages to handle, not reports
        self.assertEqual(forums.count_open_flags('S'), 3)
        self.assertEqual(forums.count_all_open_flags(), 4)
        big = next(flag for flag in forums.get_flags('S')['open'] if flag['message_id'] == big_id)
        self.assertEqual({report['reporter_name'] for report in big['reports']}, {'Varro', 'Censeur'})

        # The threshold is about the forums : a private message has a single possible reporter
        filtered = forums.get_reported_messages(['S', 'Other'], more_than=1)
        self.assertEqual({flag['body'] for flag in filtered['open']}, {'Grosse insulte', 'Menace privée'})
        self.assertEqual(filtered['nb_open'], 4)

        self.play(self.staff, self.staff_commandant)
        response = self.client.get('/admin_message_flags/')
        for body in ('Grosse insulte', 'Petite pique', 'Menace privée', 'Autre serveur', '2 signalements'):
            self.assertContains(response, body)
        self.assertEqual(response.context['nb_open_flags'], 4)

        response = self.client.get('/admin_message_flags/?more_than=1')
        self.assertContains(response, 'Menace privée')
        self.assertContains(response, 'Grosse insulte')
        self.assertNotContains(response, 'Petite pique')
        self.assertNotContains(response, 'Autre serveur')
        self.assertContains(response, 'sur 4')

        self.assertNotContains(self.client.get('/admin_message_flags/?server_name_selected=S'), 'Autre serveur')
        self.assertContains(self.client.get('/admin_message_flags/?more_than=-1'), 'Petite pique')  # An invalid filter hides nothing

        # A decision settles all the reports of the message, on its own server
        self.client.post('/admin_message_flags/', {'action': 'close', 'server': 'S', 'flag_id': big['id']})
        self.assertEqual(forums.count_open_flags('S'), 2)
        self.assertEqual(forums.count_open_flags('Other'), 1)
        self.client.post('/admin_message_flags/', {'action': 'close', 'server': 'unknown', 'flag_id': big['id']})

    def test_player_does_not_see_the_admin_link(self):
        self.play(self.user, self.owner)
        self.assertNotContains(self.client.get('/assembly/', follow=True), 'href="/admin_main_dashboard/"')

    # Votes on the messages

    def vote_line(self, topic_id, commandant_id):
        post = forums.get_posts('S', topic_id, 1, commandant_id)[0]
        return post['score'], {vote['category']: vote['voters'] for vote in post['votes'] if vote['voters']}, \
            [vote['category'] for vote in post['votes'] if vote['is_mine']]

    def test_vote_can_be_changed_and_taken_back(self):
        topic_id = forums.create_topic('S', self.assembly_id, self.owner, 'Discours', 'Citoyens...')
        post_id = forums.get_posts('S', topic_id, 1, self.owner)[0]['id']

        forums.vote_post('S', post_id, self.visitor, 'humour')
        forums.vote_post('S', post_id, self.staff_commandant, 'roleplay')
        self.assertEqual(self.vote_line(topic_id, self.visitor), (2, {'humour': ['Varro'], 'roleplay': ['Censeur']}, ['humour']))

        forums.vote_post('S', post_id, self.visitor, 'remarkable')  # Replaced, not added
        self.assertEqual(self.vote_line(topic_id, self.visitor), (2, {'remarkable': ['Varro'], 'roleplay': ['Censeur']}, ['remarkable']))

        forums.vote_post('S', post_id, self.visitor, 'remarkable')  # Taken back
        self.assertEqual(self.vote_line(topic_id, self.visitor), (1, {'roleplay': ['Censeur']}, []))

    def test_who_can_vote(self):
        topic_id = forums.create_topic('S', self.assembly_id, self.owner, 'Discours', 'Citoyens...')
        post_id = forums.get_posts('S', topic_id, 1, self.owner)[0]['id']
        with self.assertRaises(GameError):
            forums.vote_post('S', post_id, self.owner, 'humour')  # Not on one's own message
        with self.assertRaises(GameError):
            forums.vote_post('S', post_id, self.visitor, 'inconnue')

        private_topic_id = forums.create_topic('S', self.private_forum(), self.owner, 'Secret', 'Le plan')
        with self.assertRaises(GameError):
            forums.vote_post('S', forums.get_posts('S', private_topic_id, 1, self.owner)[0]['id'], self.visitor, 'humour')

        tavern_id = forums.create_player_forum('S', self.owner, 'La Cantine', '', False)
        tavern_topic_id = forums.create_topic('S', tavern_id, self.owner, 'Menu', 'Du jour')
        tavern_post_id = forums.get_posts('S', tavern_topic_id, 1, self.owner)[0]['id']
        forums.vote_post('S', tavern_post_id, self.visitor, 'humour')  # A public forum can be judged without joining it
        forums.join_forum('S', tavern_id, self.visitor)
        forums.remove_from_forum('S', tavern_id, self.owner, self.visitor)
        with self.assertRaises(GameError):
            forums.vote_post('S', tavern_post_id, self.visitor, 'fitting')

        hrp_topic_id = forums.create_topic('S', forums.get_forum_id('S', 'hrp'), self.owner, 'Bug', 'Texte')
        hrp_post = forums.get_posts('S', hrp_topic_id, 1, self.owner)[0]
        self.assertNotIn('roleplay', [vote['category'] for vote in hrp_post['votes']])  # No roleplay out of the game
        with self.assertRaises(GameError):
            forums.vote_post('S', hrp_post['id'], self.visitor, 'roleplay')

    def test_vote_from_the_page(self):
        topic_id = forums.create_topic('S', self.assembly_id, self.owner, 'Discours', 'Citoyens...')
        post_id = forums.get_posts('S', topic_id, 1, self.owner)[0]['id']
        url = f'/topic/?topic_id={topic_id}'

        self.play(self.other_user, self.visitor)
        response = self.client.post(url, {'vote_post': f'{post_id}:humour'})
        self.assertRedirects(response, f'{url}#post-{post_id}', fetch_redirect_response=False)
        self.assertContains(self.client.get(url), 'Score : 1')
        self.assertContains(self.client.get(url), 'Humour décapant : Varro')
        self.assertContains(self.client.post(url, {'vote_post': 'abc:humour'}), 'noter ce message')
        self.assertContains(self.client.post(url, {'vote_post': 'abc'}), 'noter ce message')

        self.play(self.user, self.owner)  # Sees the votes on his own message, but his buttons are disabled
        self.assertContains(self.client.get(url), 'disabled>Humour décapant : 1')

        conversation_id = conversations.start_conversation('S', self.owner, 'Varro', 'Pacte', 'Secret')
        self.assertNotContains(self.client.get(f'/conversation/?conversation_id={conversation_id}'), 'vote_post')

    def test_deleting_a_message_takes_its_votes_away(self):
        topic_id = forums.create_topic('S', self.assembly_id, self.owner, 'Discours', 'Un')
        forums.reply_to_topic('S', topic_id, self.owner, 'Deux')
        first, second = forums.get_posts('S', topic_id, 1, self.owner)
        forums.vote_post('S', first['id'], self.visitor, 'humour')
        forums.vote_post('S', second['id'], self.visitor, 'humour')
        forums.delete_post('S', second['id'], self.visitor, True)
        self.assertEqual(forums.get_posts('S', topic_id, 1, self.owner)[0]['score'], 1)

    # What is displayed next to a message

    def test_respect_adds_up_the_votes_received_in_the_game(self):
        topic_id = forums.create_topic('S', self.assembly_id, self.owner, 'Discours', 'Un')
        forums.reply_to_topic('S', topic_id, self.owner, 'Deux')
        first, second = forums.get_posts('S', topic_id, 1, self.visitor)
        forums.vote_post('S', first['id'], self.visitor, 'humour')
        forums.vote_post('S', first['id'], self.staff_commandant, 'fitting')
        forums.vote_post('S', second['id'], self.visitor, 'humour')
        hrp_topic_id = forums.create_topic('S', forums.get_forum_id('S', 'hrp'), self.owner, 'Bug', 'Texte')
        forums.vote_post('S', forums.get_posts('S', hrp_topic_id, 1, self.owner)[0]['id'], self.visitor, 'humour')

        self.assertEqual(forums.get_posts('S', hrp_topic_id, 1, self.owner)[0]['author_respect'], 3)  # Also shown there
        self.play(self.other_user, self.visitor)
        self.assertContains(self.client.get(f'/topic/?topic_id={topic_id}'), 'Respect diplomatique : 3')

        forums.delete_post('S', second['id'], self.visitor, True)
        self.assertEqual(forums.get_posts('S', topic_id, 1, self.visitor)[0]['author_respect'], 2)

        conversation_id = conversations.start_conversation('S', self.owner, 'Varro', 'Pacte', 'Secret')
        self.assertNotContains(self.client.get(f'/conversation/?conversation_id={conversation_id}'), 'Respect diplomatique')

    def test_up_to_three_images_next_to_a_message(self):
        with server_schema('S'):
            Commandant.objects.filter(id=self.owner).update(portrait='images/a.jpg', flag='images/b.jpg')
        topic_id = forums.create_topic('S', self.assembly_id, self.owner, 'Discours', 'Un')
        forums.reply_to_topic('S', topic_id, self.visitor, 'Sans image')
        url = f'/topic/?topic_id={topic_id}'
        images = lambda: forums.get_posts('S', topic_id, 1, self.visitor)[0]['author_images']

        self.assertEqual(images(), [('images/a.jpg', 'Paullus'), ('images/b.jpg', 'Paullus')])
        self.assertEqual(forums.get_posts('S', topic_id, 1, self.visitor)[1]['author_images'], [])

        coalition_id = forums.create_coalition('S', self.owner, 'La Ligue')
        self.assertEqual(images()[2], (forums.COALITION_FLAG, 'La Ligue'))
        self.play(self.other_user, self.visitor)
        self.assertContains(self.client.get(url), 'alt="La Ligue"')

        conversation_id = conversations.start_conversation('S', self.owner, 'Varro', 'Pacte', 'Secret')
        self.assertContains(self.client.get(f'/conversation/?conversation_id={conversation_id}'), 'alt="La Ligue"')

        forums.destroy_player_forum('S', coalition_id, self.owner)
        self.assertEqual(len(images()), 2)

    def test_messages_are_displayed_formatted_and_escaped_with_their_toolbar(self):
        topic_id = forums.create_topic('S', self.assembly_id, self.owner, 'Discours', '[b]Citoyens[/b] <script>alert(1)</script>')
        self.play(self.user, self.owner)
        response = self.client.get(f'/topic/?topic_id={topic_id}')
        self.assertContains(response, '<strong>Citoyens</strong> &lt;script&gt;')
        self.assertContains(response, 'data-text-toolbar')

    def test_game_dates_show_the_real_date_until_the_rule_is_decided(self):
        self.assertEqual(rp_date(None), '')
        self.play(self.user, self.owner)
        self.assertEqual(rp_date(datetime(2026, 11, 6, 14, 5, tzinfo=dt_timezone.utc)), '06/11/2026 14:05')

        topic_id = forums.create_topic('S', self.assembly_id, self.owner, 'Discours', 'Un')
        conversations.start_conversation('S', self.visitor, 'Paullus', 'Pacte', 'Secret')
        forums.create_player_forum('S', self.visitor, 'La Cantine', '', False)
        tavern_topic = forums.create_topic('S', forums.get_player_forums('S', self.visitor)['member'][0]['id'], self.visitor, 'Menu', 'Du jour')
        with server_schema('S'):
            report = Report.objects.create(owner_id=self.owner, category='other', category_icon='fa-file-alt', datetime=timezone.now(),
                                           tss_calendar=timezone.now(), title='Bienvenue', message='Texte')

        for url in (f'/forum/?forum_id={self.assembly_id}', f'/topic/?topic_id={topic_id}', '/conversations/', '/player_forums/',
                    '/reports/', f'/report/?report_id={report.id}'):
            self.assertContains(self.client.get(url), f'/{timezone.now().year} ', msg_prefix=url)

    # View counter

    def test_view_is_counted_once_by_commandant_after_the_page_asked_for_it(self):
        topic_id = forums.create_topic('S', self.assembly_id, self.owner, 'Discours', 'Citoyens...')
        url = f'/topic/?topic_id={topic_id}'
        views = lambda: forums.get_topics('S', self.assembly_id, 1, self.owner)[0]['nb_views']

        self.play(self.other_user, self.visitor)
        self.client.post('/topic_view/', {'topic_id': topic_id})  # Without having displayed the topic
        self.assertEqual(views(), 0)

        self.assertContains(self.client.get(url), f'data-view-after="{forums.VIEW_DELAY_SECONDS}"')
        self.assertEqual(views(), 0)  # Displaying it isn't enough
        self.assertEqual(self.client.post('/topic_view/', {'topic_id': topic_id}).status_code, 204)
        self.assertEqual(views(), 1)

        self.client.post('/topic_view/', {'topic_id': topic_id})
        self.assertEqual(views(), 1)
        self.assertNotContains(self.client.get(url), 'data-view-after')  # Nothing more to send

        self.play(self.user, self.owner)
        self.client.get(url)
        self.client.post('/topic_view/', {'topic_id': topic_id})
        self.assertEqual(views(), 2)
        self.assertEqual(self.client.get('/topic_view/').status_code, 405)
        self.assertEqual(self.client.post('/topic_view/', {'topic_id': 'abc'}).status_code, 204)
        self.assertContains(self.client.get(f'/forum/?forum_id={self.assembly_id}'), '<td class="text-center">2</td>')

    def test_marking_as_read_is_no_view_and_a_private_topic_stays_closed(self):
        topic_id = forums.create_topic('S', self.assembly_id, self.owner, 'Discours', 'Citoyens...')
        forums.mark_forum_as_read('S', self.assembly_id, self.visitor)
        self.assertEqual(forums.get_topics('S', self.assembly_id, 1, self.owner)[0]['nb_views'], 0)

        forum_id = self.private_forum()
        private_topic_id = forums.create_topic('S', forum_id, self.owner, 'Secret', 'Le plan')
        forums.invite_to_forum('S', forum_id, self.owner, 'Varro')
        forums.answer_invitation('S', forum_id, self.visitor, True)
        forums.mark_forum_as_read('S', forum_id, self.visitor)
        forums.remove_from_forum('S', forum_id, self.owner, self.visitor)
        forums.count_topic_view('S', private_topic_id, self.visitor)  # Banned since : he can't read it any more
        self.assertEqual(forums.get_topics('S', forum_id, 1, self.owner)[0]['nb_views'], 0)

    # Coalitions

    def test_coalition_is_private_and_unique_for_a_commandant(self):
        coalition_id = forums.create_coalition('S', self.owner, 'La Ligue')
        self.assertTrue(forums.get_forum('S', coalition_id, self.owner)['can_post'])
        self.assertIsNone(forums.get_forum('S', coalition_id, self.visitor))
        with self.assertRaises(GameError):
            forums.join_forum('S', coalition_id, self.visitor)
        with self.assertRaises(GameError), transaction.atomic():
            forums.create_coalition('S', self.owner, 'Une autre')

        # Stays private whatever is sent
        forums.update_player_forum('S', coalition_id, self.owner, 'La Ligue', '', False)
        self.assertIsNone(forums.get_forum('S', coalition_id, self.visitor))

        rival_id = forums.create_coalition('S', self.visitor, 'Le Pacte')
        forums.invite_to_forum('S', coalition_id, self.owner, 'Varro')
        self.assertEqual([forum['name'] for forum in forums.get_coalition_invitations('S', self.visitor)], ['La Ligue'])
        with self.assertRaises(GameError), transaction.atomic():
            forums.answer_invitation('S', coalition_id, self.visitor, True)
        self.assertIsNone(forums.get_forum('S', coalition_id, self.visitor))

        forums.destroy_player_forum('S', rival_id, self.visitor)
        forums.answer_invitation('S', coalition_id, self.visitor, True)
        self.assertEqual(forums.get_coalition_id('S', self.visitor), coalition_id)

        forums.leave_forum('S', coalition_id, self.visitor)
        self.assertIsNone(forums.get_coalition_id('S', self.visitor))

    def test_coalition_pages(self):
        self.play(self.user, self.owner)
        self.assertContains(self.client.get('/coalition/'), "aucune coalition")
        self.assertContains(self.client.post('/coalition/', {'action': 'create', 'name': ''}), 'entre 1 et 60')

        response = self.client.post('/coalition/', {'action': 'create', 'name': 'La Ligue'}, follow=True)
        coalition_id = forums.get_coalition_id('S', self.owner)
        self.assertEqual(response.redirect_chain[-1][0], f'/forum/?forum_id={coalition_id}')
        self.assertContains(response, 'La Ligue')

        manage_url = f'/player_forum_manage/?forum_id={coalition_id}'
        self.assertNotContains(self.client.get(manage_url), 'name="is_private"')
        self.client.post(manage_url, {'action': 'destroy'})
        self.assertIsNone(forums.get_coalition_id('S', self.owner))

    # Private messages

    def test_conversation_is_reserved_to_its_members(self):
        conversation_id = conversations.start_conversation('S', self.owner, 'varro', 'Pacte', 'Alliance ?')
        self.assertEqual(conversations.count_unread_conversations('S', self.visitor), 1)
        self.assertEqual(conversations.count_unread_conversations('S', self.owner), 0)
        self.assertEqual(conversations.get_conversation('S', conversation_id, self.visitor)['correspondents'], 'Paullus')

        third = self.staff_commandant
        self.assertIsNone(conversations.get_conversation('S', conversation_id, third))
        with self.assertRaises(GameError):
            conversations.send_message('S', conversation_id, third, 'Hop')
        conversations.hide_conversations('S', [conversation_id], third)  # Someone else's : changes nothing
        self.assertIsNotNone(conversations.get_conversation('S', conversation_id, self.owner))

    def test_nobody_writes_to_himself_or_to_nobody(self):
        for name in ('Paullus', 'Inconnu'):
            with self.assertRaises(GameError), transaction.atomic():
                conversations.start_conversation('S', self.owner, name, 'Sujet', 'Texte')

    def test_removed_conversation_comes_back_with_a_new_message(self):
        conversation_id = conversations.start_conversation('S', self.owner, 'Varro', 'Pacte', 'Alliance ?')
        conversations.hide_conversations('S', [conversation_id, 'invalid'], self.visitor)
        self.assertEqual(conversations.get_conversations('S', self.visitor, 1).paginator.count, 0)
        self.assertEqual(conversations.count_unread_conversations('S', self.visitor), 0)

        conversations.send_message('S', conversation_id, self.owner, 'Alors ?')
        self.assertEqual(conversations.get_conversations('S', self.visitor, 1).paginator.count, 1)

        conversations.hide_conversations('S', [conversation_id], self.visitor)
        conversations.hide_conversations('S', [conversation_id], self.owner)
        self.assertIsNone(conversations.get_conversation('S', conversation_id, self.owner))  # Removed by all : deleted
        self.assertEqual(conversations.get_messages('S', conversation_id, 1, self.owner).paginator.count, 0)

    # Pages

    def test_every_page_answers(self):
        self.play(self.user, self.owner)
        hrp_id = forums.get_forum_id('S', 'hrp')
        topic_id = forums.create_topic('S', self.assembly_id, self.owner, 'Discours', 'Texte')
        forum_id = self.private_forum()
        conversation_id = conversations.start_conversation('S', self.owner, 'Varro', 'Pacte', 'Texte')

        for url in ('/communication/', f'/forum/?forum_id={self.assembly_id}', f'/forum/?forum_id={hrp_id}', f'/forum/?forum_id={forum_id}',
                    f'/topic/?topic_id={topic_id}', '/player_forums/', f'/player_forum_manage/?forum_id={forum_id}',
                    '/coalition/', '/conversations/', f'/conversation/?conversation_id={conversation_id}'):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertRedirects(self.client.get('/assembly/'), f'/forum/?forum_id={self.assembly_id}')
        self.assertRedirects(self.client.get('/hrp/'), f'/forum/?forum_id={hrp_id}')

    def test_no_forum_without_a_commandant(self):
        self.assertEqual(self.client.get('/hrp/').status_code, 302)
        self.client.force_login(self.staff)
        for url in ('/assembly/', '/hrp/', '/coalition/', '/forum/'):
            self.assertRedirects(self.client.get(url), '/user_account/', fetch_redirect_response=False)

    def test_forbidden_or_unknown_ids_send_back_to_a_list(self):
        forum_id = self.private_forum()
        self.play(self.other_user, self.visitor)
        for url, destination in ((f'/forum/?forum_id={forum_id}', '/player_forums/'),
                                 (f'/player_forum_manage/?forum_id={forum_id}', '/player_forums/'),
                                 (f'/player_forum_manage/?forum_id={self.assembly_id}', '/player_forums/'),
                                 ('/forum/?forum_id=abc', '/player_forums/'), ('/topic/?topic_id=abc', '/assembly/'),
                                 ('/conversation/?conversation_id=abc', '/conversations/')):
            self.assertRedirects(self.client.get(url), destination, fetch_redirect_response=False)

    def test_owner_manages_his_forum_from_its_page(self):
        forum_id = forums.create_player_forum('S', self.owner, 'La Cantine', '', False)
        url = f'/player_forum_manage/?forum_id={forum_id}'
        self.play(self.user, self.owner)

        self.client.post(url, {'action': 'save', 'name': 'Le Repaire', 'ambiance': 'Texte', 'is_private': 'on'})
        forum = forums.get_forum('S', forum_id, self.owner)
        self.assertEqual((forum['name'], forum['description'], forum['is_private']), ('Le Repaire', 'Texte', True))

        self.client.post(url, {'action': 'invite', 'invited_name': 'Varro'})
        self.assertEqual(self.invitations(self.visitor), 1)
        self.assertContains(self.client.post(url, {'action': 'invite', 'invited_name': 'Inconnu'}), 'Aucun commandant')

        self.client.post(url, {'action': 'remove', 'commandant_id': self.visitor})
        self.assertEqual(self.invitations(self.visitor), 0)

        self.client.post(url, {'action': 'destroy'})
        self.assertIsNone(forums.get_forum('S', forum_id, self.owner))

    def test_visitor_can_not_use_the_page_of_the_owner(self):
        forum_id = forums.create_player_forum('S', self.owner, 'La Cantine', '', False)
        self.play(self.other_user, self.visitor)
        self.client.post(f'/player_forum_manage/?forum_id={forum_id}', {'action': 'destroy'})
        self.assertIsNotNone(forums.get_forum('S', forum_id, self.owner))

    def test_moderation_buttons_follow_the_rights(self):
        forum_id = forums.create_player_forum('S', self.owner, 'La Cantine', '', False)
        forums.join_forum('S', forum_id, self.visitor)
        topic_id = forums.create_topic('S', forum_id, self.visitor, 'Sujet', 'Un')
        forums.reply_to_topic('S', topic_id, self.visitor, 'Deux')
        url = f'/topic/?topic_id={topic_id}'

        self.play(self.other_user, self.visitor)
        self.assertNotContains(self.client.get(url), 'name="delete_post"')
        post_id = forums.get_posts('S', topic_id, 1, self.visitor)[1]['id']
        self.assertContains(self.client.post(url, {'delete_post': post_id}), 'Vous ne pouvez pas supprimer')

        self.play(self.user, self.owner)
        self.assertContains(self.client.get(url), 'name="delete_post"')
        self.assertRedirects(self.client.post(url, {'delete_post': post_id}), url)
        self.assertEqual(forums.get_posts('S', topic_id, 1, self.owner).paginator.count, 1)
        self.assertRedirects(self.client.post(url, {'delete_topic': '1'}), f'/forum/?forum_id={forum_id}')
        self.assertIsNone(forums.get_topic('S', topic_id, self.owner))

    def test_refused_message_keeps_what_was_typed(self):
        self.play(self.user, self.owner)
        response = self.client.post('/conversations/', {'action': 'new', 'recipient': 'Inconnu', 'subject': 'Pacte', 'body': 'Long texte'})
        self.assertContains(response, 'Aucun commandant')
        self.assertContains(response, 'Long texte')

    def test_messages_are_escaped_and_their_links_clickable(self):
        self.play(self.user, self.owner)
        self.client.post(f'/forum/?forum_id={self.assembly_id}', {'action': 'new_topic', 'title': '<b>Titre</b>',
                                                                  'body': '<script>alert(1)</script>\nhttps://example.com'})
        response = self.client.get(f'/forum/?forum_id={self.assembly_id}')
        self.assertContains(response, '&lt;b&gt;Titre&lt;/b&gt;')
        topic_id = forums.get_topics('S', self.assembly_id, 1, self.owner)[0]['id']
        forums.edit_post('S', forums.get_posts('S', topic_id, 1, self.owner)[0]['id'], self.owner, '<img src=x onerror=alert(2)>')
        forums.flag_post('S', forums.get_posts('S', topic_id, 1, self.owner)[0]['id'], self.visitor, '<i>Motif</i>')

        response = self.client.get(f'/topic/?topic_id={topic_id}')
        self.assertNotContains(response, '<script>alert(1)')
        self.assertNotContains(response, '<img src=x')
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;<br>')  # In the previous version
        self.assertContains(response, 'href="https://example.com"')

        self.play(self.staff, self.staff_commandant)
        response = self.client.get('/admin_message_flags/?server_name_selected=S')
        self.assertNotContains(response, '<img src=x')
        self.assertNotContains(response, '<i>Motif</i>')

    def test_ambiance_is_escaped(self):
        forum_id = forums.create_player_forum('S', self.owner, 'La Cantine', '<script>alert(3)</script>', False)
        self.play(self.user, self.owner)
        self.assertNotContains(self.client.get(f'/forum/?forum_id={forum_id}'), '<script>alert(3)')

    def test_get_changes_nothing(self):
        forum_id = forums.create_player_forum('S', self.owner, 'La Cantine', '', False)
        self.play(self.other_user, self.visitor)
        self.client.get(f'/forum/?forum_id={forum_id}&action=join')
        self.assertIsNone(forums.get_forum('S', forum_id, self.visitor)['membership'])

    def test_post_needs_a_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        for url in ('/forum/', '/topic/', '/topic_view/', '/player_forums/', '/player_forum_manage/', '/coalition/', '/conversations/',
                    '/conversation/', '/admin_message_flags/'):
            self.assertEqual(client.post(url).status_code, 403, url)


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


class EconomyTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('player', 'p@example.com', 'x')
        make_server('S')
        with server_schema('S'):
            cls.commandant = Commandant.objects.create(user=cls.user, commandant_name='Paullus', civilisation_name='Empire',
                                                       creation_date=timezone.now(), resources={'steel': 10, 'water': 3})
            colony = Colony.objects.create(name='Home', owner=cls.commandant, controller=cls.commandant,
                                           coordinate='100100000005505001', colony_type='start')
            cls.colony = colony
            DistrictType.objects.create(internal_name='central', data={'internal_name': 'central', 'name_fr': 'central', 'category': 'central_district',
                                                                       'districts_slots': 1, 'build_cost': {}, 'maintenance': {}})
            DistrictType.objects.create(internal_name='farming', data={'internal_name': 'farming', 'name_fr': 'farming', 'category': 'farming_district',
                                                                       'districts_slots': 0, 'build_cost': {}, 'maintenance': {'steel': 4}})
            cls.central = District.objects.create(colony=colony, district_type='central', category='central_district',
                                                  population=2_000_000, buildings_slots_free=1, buildings_slots_total=1)
            cls.farming = District.objects.create(colony=colony, district_type='farming', category='farming_district')
            for name, data in (('water', {'pop_consumption_9': 1}),
                               ('food_a', {'pop_consumption_9': 1, 'sub_category': 'food'}),
                               ('food_b', {'pop_consumption_9': 1, 'sub_category': 'food'}),
                               ('steel', {}),
                               ('drug', {'pop_consumption_9': 5, 'category': 'resources_cat_illicits'})):
                Resource.objects.create(internal_name=name, data={'internal_name': name, 'name_fr': name, 'name_en': name,
                                                                  'unit_notation': 'Mt', 'icon': 'x.png'} | data)
            for name, data in (('well', {'production': 'water', 'production_quantity': 4, 'maintenance': {'steel': 2}, 'central_district': True}),
                               ('farm', {'production': 'food_b', 'farming_district': True}),
                               ('text_row', {'production': 'Eau en texte', 'central_district': True}),
                               ('too_old', {'production': 'water', 'tech_hidden': 9, 'central_district': True}),
                               ('too_new', {'production': 'water', 'tech_available': 10, 'central_district': True})):
                BuildingType.objects.create(internal_name=name, data={'internal_name': name, 'name_fr': name, 'name_en': name,
                                                                      'category': 'vital_needs', 'build_cost': {'steel': 1},
                                                                      'maintenance': {}, 'illustration': 'x.png'} | data)
            cycles.create_cycle_entry('S')

    def build(self, district, building_type, **fields):
        with server_schema('S'):
            return Building.objects.create(building_type=building_type, home_district=district, **fields)

    def resources(self):
        return get_commandant('S', self.commandant.id)['resources']


class EconomyTests(EconomyTestCase):

    def test_production_maintenance_and_needs_of_the_population(self):
        well = self.build(self.central, 'well')
        cycles.end_cycle('S')
        # Water : 3 + 4 produced - 2 for the 2 Mo of population. Steel : well 2, then district 4. No food : shortage
        self.assertEqual(self.resources(), {'steel': 4, 'water': 5})
        with server_schema('S'):
            well.refresh_from_db()
            report = Report.objects.get(owner=self.commandant)
        self.assertEqual((well.last_cycle_production, well.last_cycle_productivity_percent), (4, 100))
        self.assertIn('4.00 Mt water', report.message)
        self.assertIn('2.00 Mt food_a', report.message)
        self.assertEqual(get_commandant('S', self.commandant.id)['nb_unread_reports'], 1)

    def test_activation_scales_production_and_maintenance(self):
        self.build(self.central, 'well', activation_percent=50)
        cycles.end_cycle('S')
        self.assertEqual(self.resources(), {'steel': 5, 'water': 3})  # Steel 10 - 4 - 1, water 3 + 2 - 2

    def test_missing_maintenance_lowers_productivity(self):
        with server_schema('S'):
            Commandant.objects.filter(id=self.commandant.id).update(resources={'steel': 1, 'water': 0})
        well = self.build(self.central, 'well')
        farm = self.build(self.farming, 'farm')
        cycles.end_cycle('S')
        with server_schema('S'):
            well.refresh_from_db()
            farm.refresh_from_db()
        # The well of the oldest district takes the only steel, half of its need. Its district is then left with nothing.
        self.assertEqual(well.last_cycle_productivity_percent, 50)
        self.assertEqual(well.last_cycle_production, 2)
        self.assertEqual(well.last_cycle_missing_resources, {'steel': 1})
        self.assertEqual(farm.last_cycle_productivity_percent, 0)
        self.assertEqual(self.resources(), {'steel': 0, 'water': 0})

    def test_foods_replace_each_other(self):
        with server_schema('S'):
            Commandant.objects.filter(id=self.commandant.id).update(resources={'food_a': 1, 'food_b': 5})
        cycles.end_cycle('S')
        self.assertEqual(self.resources(), {'food_a': 0, 'food_b': 4})

    def test_illicits_and_unknown_productions_change_nothing(self):
        self.build(self.central, 'text_row')
        with server_schema('S'):
            Commandant.objects.filter(id=self.commandant.id).update(resources={'drug': 3, 'water': 9, 'food_a': 9, 'steel': 9})
        cycles.end_cycle('S')
        self.assertEqual(self.resources(), {'drug': 3, 'water': 7, 'food_a': 7, 'steel': 5})

    def test_forecast_writes_nothing(self):
        well = self.build(self.central, 'well')
        balance = cycle_balance('S', self.commandant.id, self.resources())
        self.assertEqual(balance['produced'], {'water': 4})
        self.assertEqual(self.resources(), {'steel': 10, 'water': 3})
        with server_schema('S'):
            well.refresh_from_db()
        self.assertEqual(well.last_cycle_production, 0)

    def test_a_failure_cancels_the_whole_cycle(self):
        self.build(self.central, 'well')
        with patch('data.economy.create_report', side_effect=ValueError), self.assertRaises(ValueError):
            cycles.end_cycle('S')
        self.assertEqual(cycles.get_current_cycle('S')['cycle_nb'], 1)
        self.assertIsNone(cycles.get_current_cycle('S')['datetime_end'])
        self.assertEqual(self.resources(), {'steel': 10, 'water': 3})

    def test_building_is_limited_by_district_and_technology(self):
        for building_type, category, expected in (('well', 'central_district', True), ('well', 'farming_district', False),
                                                  ('too_old', 'central_district', False), ('too_new', 'central_district', False)):
            with server_schema('S'):
                data = BuildingType.objects.get(internal_name=building_type).data
            self.assertEqual(is_buildable(data, category), expected, building_type)

    def test_construction_takes_a_slot_once(self):
        self.assertTrue(construct_building('S', self.central.id, 'well'))
        self.assertFalse(construct_building('S', self.central.id, 'well'))
        with server_schema('S'):
            self.assertEqual(Building.objects.count(), 1)
            self.assertEqual(District.objects.get(id=self.central.id).buildings_slots_free, 0)
            District.objects.filter(id=self.central.id).update(buildings_slots_free=20)  # As in the old districts
        self.assertFalse(construct_building('S', self.central.id, 'well'))


class ModifiersTests(EconomyTestCase):
    # The test coordinate : sector 1001000000, position 055-050, in the last quadrant of its sector

    TYPES = {
        'boom': {'name_fr': 'Boom', 'description_fr': 'd', 'categories': ['economic', 'military'], 'duration': None, 'decreasing': False,
                 'effects': [{'stat': 'production', 'percent': 50}]},
        'flat': {'name_fr': 'Flat', 'description_fr': 'd', 'categories': ['economic'], 'duration': 2, 'decreasing': False,
                 'effects': [{'stat': 'production', 'flat': 1, 'resource': 'water'}]},
        'other_resource': {'name_fr': 'Other', 'description_fr': 'd', 'categories': ['other'], 'duration': None, 'decreasing': False,
                           'effects': [{'stat': 'production', 'flat': 1, 'resource': 'food_a'}]},
        'fading': {'name_fr': 'Fading', 'description_fr': 'd', 'categories': ['economic'], 'duration': 4, 'decreasing': True,
                   'effects': [{'stat': 'production', 'percent': 100}]},
        'disaster': {'name_fr': 'Disaster', 'description_fr': 'd', 'categories': ['military'], 'duration': None, 'decreasing': False,
                     'effects': [{'stat': 'production', 'percent': -200}]},
    }

    def setUp(self):
        patcher = patch.dict('data.modifiers.MODIFIER_TYPES', self.TYPES)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.build(self.central, 'well')  # 4 water per cycle
        with server_schema('S'):
            Commandant.objects.filter(id=self.commandant.id).update(resources={'steel': 1000, 'water': 3})

    def produced(self):
        return cycle_balance('S', self.commandant.id, self.resources())['produced']['water']

    def test_every_scope_reaches_the_buildings_it_contains(self):
        for scope, target in (('coordinate', '100100000005505001'), ('district', self.central.id), ('system', '1001000000055050'),
                              ('commandant', self.commandant.id), ('quadrant', '1001000000:11'), ('sector', '1001000000')):
            modifier = add_modifier('S', 'boom', scope, target)
            self.assertEqual(self.produced(), 6, scope)
            with server_schema('S'):
                modifier.delete()

    def test_what_is_elsewhere_changes_nothing(self):
        for scope, target in (('coordinate', '100100000005505002'), ('district', self.farming.id), ('system', '1001000000055051'),
                              ('commandant', self.commandant.id + 1), ('quadrant', '1001000000:00'), ('sector', '1001000001'),
                              ('sector', '100100000005505001')):
            add_modifier('S', 'boom', scope, target)
        self.assertEqual(self.produced(), 4)

    def test_flat_is_added_before_percent_and_only_on_its_resource(self):
        add_modifier('S', 'other_resource', 'commandant', self.commandant.id)
        self.assertEqual(self.produced(), 4)
        add_modifier('S', 'flat', 'commandant', self.commandant.id)
        self.assertEqual(self.produced(), 5)
        add_modifier('S', 'boom', 'commandant', self.commandant.id)
        self.assertEqual(self.produced(), 7.5)

    def test_a_malus_never_makes_a_production_negative(self):
        add_modifier('S', 'disaster', 'commandant', self.commandant.id)
        self.assertEqual(cycle_balance('S', self.commandant.id, self.resources())['produced'], {})

    def test_decreasing_effect_fades_then_ends(self):
        add_modifier('S', 'fading', 'commandant', self.commandant.id)
        productions = []
        for _ in range(5):
            productions.append(self.produced())
            cycles.end_cycle('S')
        self.assertEqual(productions, [8, 7, 6, 5, 4])
        with server_schema('S'):
            self.assertFalse(Modifier.objects.exists())

    def test_fixed_effect_stays_until_its_end(self):
        add_modifier('S', 'flat', 'commandant', self.commandant.id)
        productions = []
        for _ in range(3):
            productions.append(self.produced())
            cycles.end_cycle('S')
        self.assertEqual(productions, [5, 5, 4])

    def test_permanent_effect_stays(self):
        add_modifier('S', 'boom', 'commandant', self.commandant.id)
        cycles.end_cycle('S')
        with server_schema('S'):
            self.assertIsNone(Modifier.objects.get().cycles_left)
        self.assertEqual(self.produced(), 6)

    def test_the_end_of_cycle_applies_the_boost(self):
        add_modifier('S', 'boom', 'commandant', self.commandant.id)
        cycles.end_cycle('S')
        self.assertEqual(self.resources()['water'], 3 + 6 - 2)

    def test_colonial_optimism(self):
        from data.modifiers import MODIFIER_TYPES
        self.assertEqual(MODIFIER_TYPES['colonial_optimism']['categories'], ['economic'])
        add_modifier('S', 'colonial_optimism', 'coordinate', '100100000005505001')
        self.assertEqual(self.produced(), 4.4)
        cycles.end_cycle('S')
        self.assertAlmostEqual(self.produced(), 4.36)


class ModifiersPageTests(EconomyTestCase):

    def setUp(self):
        patcher = patch.dict('data.modifiers.MODIFIER_TYPES', ModifiersTests.TYPES)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client.force_login(self.user)
        CommandantAccount.objects.create(server_id='S', commandant_id=self.commandant.id, user=self.user, commandant_name='Paullus')
        UserExtended.objects.update_or_create(user=self.user, defaults={'playing_on_server_id': 'S', 'playing_on_commandant': self.commandant.id})
        add_modifier('S', 'boom', 'commandant', self.commandant.id)  # Economic and military
        add_modifier('S', 'flat', 'district', self.central.id)  # Economic
        add_modifier('S', 'disaster', 'sector', '1001000000')  # Military, negative
        add_modifier('S', 'other_resource', 'sector', '1001000001')  # Elsewhere : not displayed

    def names(self, **filters):
        response = self.client.get('/modifiers/', filters)
        self.assertEqual(response.status_code, 200)
        return [modifier['name'] for modifier in response.context['modifiers']]

    def test_only_what_touches_the_empire_is_listed(self):
        self.assertEqual(self.names(), ['Boom', 'Flat', 'Disaster'])

    def test_filters(self):
        self.assertEqual(self.names(scope='sector'), ['Disaster'])
        self.assertEqual(self.names(scope='district'), ['Flat'])
        self.assertEqual(self.names(sign='positive'), ['Boom', 'Flat'])
        self.assertEqual(self.names(sign='negative'), ['Disaster'])
        self.assertEqual(self.names(category='economic'), ['Boom', 'Flat'])
        self.assertEqual(self.names(category='military'), ['Boom', 'Disaster'])
        self.assertEqual(self.names(category='other'), [])
        self.assertEqual(self.names(category='military', sign='positive'), ['Boom'])
        self.assertEqual(self.names(scope='unknown'), [])

    def test_display_of_the_effects_and_durations(self):
        response = self.client.get('/modifiers/')
        self.assertContains(response, '+50 % Production')
        self.assertContains(response, '+1 Production : water')
        self.assertContains(response, '-200 % Production')
        self.assertIn('Home', response.context['modifiers'][2]['target_name'])  # Not the whole text : it depends on the language
        self.assertContains(response, '2 cycle(s)')
        self.assertContains(response, 'Permanent')

    def test_filters_are_kept_between_groups(self):
        self.assertContains(self.client.get('/modifiers/', {'scope': 'sector', 'category': 'military'}),
                            'href="?scope=sector&sign=positive&category=military"')


class QuadrantRulesTests(SimpleTestCase):

    def test_a_system_is_placed_on_the_whole_map_by_its_seed(self):
        self.assertEqual(quadrants.position('1001002003055050'), (255, 350))
        self.assertEqual(quadrants.position('100100000000000001'), (0, 0))

    def test_deposits_are_stable_and_follow_the_body(self):
        seed = '100100000005505001'
        self.assertEqual(quadrants.deposits_of_body(seed, 'jovian', 'standard'), quadrants.deposits_of_body(seed, 'jovian', 'standard'))
        self.assertEqual(quadrants.deposits_of_body(seed, 'star', 'standard'), {})
        for number in range(200):
            deposits = quadrants.deposits_of_body(f'1001000000055{number:03}01', 'jovian', 'gas_rich')
            self.assertLessEqual(set(deposits), {'hydrogen', 'methane'})
            self.assertTrue(all(1 <= richness <= 100 for richness in deposits.values()))

    def test_a_rich_system_holds_more(self):
        seeds = [f'1001000000055{number:03}01' for number in range(200)]
        total = lambda system_type: sum(sum(quadrants.deposits_of_body(seed, 'asteroid_belt', system_type).values()) for seed in seeds)
        self.assertGreater(total('resources_rich'), total('standard'))
        self.assertEqual(total('gas_rich'), total('standard'))

    def test_the_centre_of_a_zone_is_inside_it_even_for_a_ring(self):
        ring = [[0, 0, 5], [4, 0, 5]] + [[row, column, 1] for row in (1, 2, 3) for column in (0, 4)]  # Its barycentre is the hole
        y, x = geography_map.centre_of(ring)
        cell = (y // galaxy.CELL, x // galaxy.CELL)
        self.assertTrue(any(row == cell[0] and start <= cell[1] < start + length for row, start, length in ring), cell)
        self.assertEqual(geography_map.centre_of([[2, 3, 1]]), (2 * galaxy.CELL + galaxy.CELL // 2, 3 * galaxy.CELL + galaxy.CELL // 2))

    def test_the_vortex_follows_the_rule_of_the_generator(self):
        # (seed, y, x, star) : the bigger of two stars has to reach the other one
        def vortex(*systems):
            return quadrants._vortex([(seed, y, x, star, '', 'standard', 1) for seed, y, x, star in systems])
        reach = galaxy.STARS['M'][1]
        self.assertEqual(vortex(('a', 0, 0, 'M'), ('b', 0, reach, 'M')), [0, 1])
        self.assertEqual(vortex(('a', 0, 0, 'M'), ('b', 0, reach + 1, 'M')), [])
        self.assertEqual(vortex(('a', 0, 0, 'M'), ('b', 0, reach + 1, 'supergiant')), [0, 1])
        self.assertEqual(vortex(), [])


class QuadrantMapFixture(EconomyTestCase):
    # One sector of 100 x 100 cut into two zones : Berceau 1 west of x = 55, Marche 1 east of it

    def setUp(self):
        cache.clear()
        self.client.force_login(self.user)
        CommandantAccount.objects.create(server_id='S', commandant_id=self.commandant.id, user=self.user, commandant_name='Paullus')
        UserExtended.objects.update_or_create(user=self.user, defaults={'playing_on_server_id': 'S', 'playing_on_commandant': self.commandant.id})
        with server_schema('S'):
            self.commandant.native_system = '1001000000055050'
            self.commandant.native_sector = '1001000000'
            self.commandant.save()
            self.rival = Commandant.objects.create(user=self.user, commandant_name='Rival', civilisation_name='Rivals', creation_date=timezone.now())
            Sector.objects.create(seed='1001000000', pos_y=0, pos_x=0, sector_type='berceau', systems_coordinates=[[55, 50], [60, 70], [10, 10]])
            Zone.objects.create(region=1, kind='berceau', name='Berceau 1', y=50, x=27, nb_systems=2, neighbours=[2],
                                shape=[[row, 0, 11] for row in range(20)])
            Zone.objects.create(region=2, kind='marche', name='Marche 1', y=50, x=77, nb_systems=1, neighbours=[1],
                                shape=[[row, 11, 9] for row in range(20)])
            for seed, kind, region in (('1001000000055050', 'native', 1), ('1001000000060070', 'standard', 2), ('1001000000010010', 'standard', 1)):
                System.objects.create(seed=seed, system_type=kind, sector_id=seed[:10], pos_y=seed[10:13], pos_x=seed[13:16], region=region,
                                      system_coordinates={seed + '00': 'supergiant', seed + '01': 'asteroid_belt standard'})
                Coordinate.objects.create(seed=seed + '00', type='star', subtype='supergiant', sector_id=seed[:10], system_id=seed, sys_y=int(seed[10:13]),
                                          sys_x=int(seed[13:16]), sys_coordinate=0, name='Star' + seed[-3:])
                Coordinate.objects.create(seed=seed + '01', type='asteroid_belt', subtype='standard', sector_id=seed[:10], system_id=seed, sys_y=int(seed[10:13]),
                                          sys_x=int(seed[13:16]), sys_coordinate=1, name='Belt' + seed[-3:])
            Colony.objects.create(name='Outpost', owner=self.rival, controller=self.rival, coordinate='100100000006007001', colony_type='start')
            entente = Entente.objects.create(category='military', name='Pact', owner=self.rival, creation_date=timezone.now())
            EntenteMember.objects.create(entente=entente, commandant=self.rival, status='member', datetime=timezone.now())
            EntenteMember.objects.create(entente=entente, commandant=self.commandant, status='applicant', datetime=timezone.now())
            Resource.objects.create(internal_name='common_metal', data={'internal_name': 'common_metal', 'name_fr': 'Métaux', 'name_en': 'Metals'})
            Resource.objects.create(internal_name='tungsten', data={'internal_name': 'tungsten', 'name_fr': 'Tungstène', 'name_en': 'Tungsten'})

    def commandant_now(self):
        with server_schema('S'):
            return Commandant.objects.get(id=self.commandant.id)


class QuadrantMapTests(QuadrantMapFixture):

    def map_of(self, **params):
        response = self.client.get('/geography_quadrant/', params)
        self.assertEqual(response.status_code, 200)
        return response

    def test_the_native_zone_is_the_default_and_a_wrong_one_is_reported(self):
        response = self.map_of()
        self.assertEqual(response.context['zone_map']['id'], 1)
        self.assertFalse(response.context['zone_not_found'])
        for params in ({'zone': 'nope'}, {'zone': '99'}, {'system_id': '12'}, {'zone': "1' OR 1=1"}):
            response = self.map_of(**params)
            self.assertEqual(response.context['zone_map']['id'], 1)
            self.assertTrue(response.context['zone_not_found'])

    def test_a_zone_is_found_by_its_number_or_by_any_place_inside_it(self):
        for params in ({'zone': '2'}, {'system_id': '1001000000060070'}, {'system_id': '100100000006007001'}, {'system_id': 'A1-70.60'}):
            self.assertEqual(self.map_of(**params).context['zone_map']['id'], 2, params)

    def test_the_systems_of_the_zone_and_dimmed_those_around_it(self):
        zone = self.map_of(zone='1').context['zone_map']
        systems = zone['systems']
        self.assertEqual(systems['name'], ['Star010', 'Star050', 'Star070'])  # Star070 is in Marche 1, 15 units from the border
        self.assertEqual(systems['zone'], [1, 1, 2])
        self.assertEqual((systems['y'], systems['x']), ([10, 55, 60], [10, 50, 70]))
        self.assertEqual(systems['types'][systems['type'][1]]['key'], 'native')
        self.assertEqual([shown['id'] for shown in zone['zones']], [1, 2])
        self.assertEqual(zone['title'], 'Quadrant Berceau 1')

    def test_an_arrow_leads_to_each_zone_around_from_their_shared_border(self):
        exits = self.map_of(zone='1').context['zone_map']['exits']
        self.assertEqual([(exit_['zone'], exit_['name']) for exit_ in exits], [(2, 'Marche 1')])
        self.assertEqual(exits[0]['x'], 52)  # The last column of cells of Berceau 1
        self.assertEqual((round(exits[0]['dy']), round(exits[0]['dx'])), (0, 1))  # Toward the east
        self.assertContains(self.map_of(zone='1'), 'href="/geography_quadrant/?zone=2"')
        self.assertEqual(self.map_of(zone='2').context['zone_map']['exits'][0]['dx'], -1)

    def test_the_vortex_links_the_systems_the_bigger_star_reaches(self):
        # 20.6 units between Star050 and Star070, the reach of a supergiant is 28 ; Star010 is too far from both
        self.assertEqual(self.map_of(zone='1').context['zone_map']['vortex'], [1, 2])

    def test_what_is_known_of_the_others_stays_public(self):
        zone = self.map_of(zone='2').context['zone_map']
        rival = next(empire for empire in zone['empires'] if empire['id'] == self.rival.id)
        self.assertEqual(rival['civilisation'], 'Rivals')
        self.assertEqual(set(rival), {'id', 'commandant', 'civilisation', 'is_mine', 'ententes'})
        colony = zone['colonies'][zone['systems']['name'].index('Star070')][0]
        self.assertEqual((colony['name'], colony['is_mine'], colony['id']), ('Outpost', False, None))  # No link to the page of a colony of another player
        self.assertEqual([entente['name'] for entente in zone['ententes']], ['Pact'])

    def test_an_application_isnt_a_membership(self):
        memberships = ententes.memberships_of_commandants('S', [self.commandant.id, self.rival.id])
        self.assertNotIn(self.commandant.id, memberships)
        self.assertEqual(memberships[self.rival.id][0]['name'], 'Pact')

    def test_my_colony_links_to_its_page(self):
        zone = self.map_of(zone='1').context['zone_map']
        self.assertEqual(zone['colonies'][zone['systems']['name'].index('Star050')][0]['id'], self.colony.id)

    def test_only_the_resources_of_the_server_are_offered(self):
        known = {resource['id'] for resource in self.map_of(zone='1').context['zone_map']['resources']}
        with server_schema('S'):
            of_server = set(Resource.objects.values_list('internal_name', flat=True))
        self.assertEqual(known, of_server & {resource for chances in quadrants.DEPOSIT_CHANCES.values() for resource in chances})
        self.assertIn('tungsten', known)

    def test_a_server_without_zones_says_its_map_has_to_be_generated_again(self):
        with server_schema('S'):
            Zone.objects.all().delete()
        self.assertIsNone(self.map_of().context['zone_map'])
        self.assertIsNone(self.client.get('/geography_sector/').context['sector_map'])

    def test_a_player_name_cant_break_out_of_the_page(self):
        with server_schema('S'):
            Commandant.objects.filter(id=self.rival.id).update(civilisation_name='</script><script>alert(1)</script>')
        self.assertNotContains(self.map_of(zone='2'), '<script>alert(1)')


class SectorMapTests(QuadrantMapFixture):

    def sector_of(self):
        response = self.client.get('/geography_sector/')
        self.assertEqual(response.status_code, 200)
        return response

    def whole_map(self, **headers):
        response = self.client.get('/api_sector_map/', {'v': 1}, **headers)
        self.assertEqual(response.status_code, 200)
        return response

    def deposits(self, resource, zone='1'):
        response = self.client.get('/api_zone_deposits/', {'zone': zone, 'resource': resource})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_the_page_holds_the_colonies_and_the_native_zone(self):
        sector = self.sector_of().context['sector_map']
        self.assertEqual((sector['native_zone'], sector['server_seed'], sector['mode']), (1, '1001', 'sector'))
        mine, other = sector['colonies']['1001000000055050'][0], sector['colonies']['1001000000060070'][0]
        self.assertEqual((mine['id'], mine['is_mine']), (self.colony.id, True))
        self.assertEqual((other['name'], other['id'], other['is_mine']), ('Outpost', None, False))  # As public as on a quadrant
        self.assertEqual([entente['name'] for entente in sector['ententes']], ['Pact'])

    def test_the_whole_map_comes_apart_in_columns_compressed_and_kept_by_the_browser(self):
        response = self.whole_map(HTTP_ACCEPT_ENCODING='gzip')
        self.assertEqual(response['Content-Encoding'], 'gzip')
        self.assertIn('private', response['Cache-Control'])
        whole = json.loads(gzip.decompress(response.content))
        self.assertEqual((whole['height'], whole['width'], whole['cell']), (100, 100, 5))
        self.assertEqual([zone['id'] for zone in whole['zones']], [1, 2])
        systems = whole['systems']
        self.assertEqual(systems['name'], ['Star010', 'Star050', 'Star070'])
        self.assertEqual((systems['y'], systems['x'], systems['zone']), ([10, 55, 60], [10, 50, 70], [1, 1, 2]))
        self.assertEqual(systems['types'][systems['type'][1]]['key'], 'native')
        self.assertEqual(systems['stars'][systems['star'][0]]['key'], 'supergiant')

    def test_the_apis_of_the_maps_need_a_session_and_a_get(self):
        for url in ('/api_sector_map/', '/api_zone_deposits/', '/api_system_bodies/'):
            self.assertEqual(self.client.post(url).status_code, 405, url)
        self.client.logout()
        for url in ('/api_sector_map/', '/api_zone_deposits/', '/api_system_bodies/'):
            self.assertEqual(self.client.get(url).status_code, 401, url)

    def test_the_number_of_queries_doesnt_depend_on_the_number_of_systems(self):
        def queries():
            with server_schema('S'), CaptureQueriesContext(connection) as context:
                quadrants._sector_systems()
            return len(context)

        before = queries()
        with server_schema('S'):
            for x in range(20, 40):
                seed = f'1001000000020{x:03}'
                System.objects.create(seed=seed, system_type='standard', sector_id=seed[:10], pos_y=seed[10:13], pos_x=seed[13:16], region=1)
                Coordinate.objects.create(seed=seed + '00', type='star', subtype='G', sector_id=seed[:10], system_id=seed, sys_y=20, sys_x=x, sys_coordinate=0, name='N')
        self.assertEqual(queries(), before)

    def test_the_deposits_of_a_zone_add_up_the_bodies_of_its_own_systems(self):
        expected = {}
        for rank, (seed, system_type) in enumerate((('1001000000010010', 'standard'), ('1001000000055050', 'native'))):  # Not Star070 : only around
            for resource, richness in quadrants.deposits_of_body(seed + '01', 'asteroid_belt', system_type).items():
                expected.setdefault(resource, {})[rank] = richness
        self.assertTrue(expected)
        for resource, values in expected.items():
            deposits = self.deposits(resource)
            self.assertEqual(dict(zip(deposits['indexes'], deposits['values'])), values)

    def test_the_rare_deposits_add_up_all_the_rare_resources(self):
        total = sum(richness for seed, system_type in (('1001000000010010', 'standard'), ('1001000000055050', 'native'))
                    for resource, richness in quadrants.deposits_of_body(seed + '01', 'asteroid_belt', system_type).items()
                    if resource in quadrants.RARE_RESOURCES)
        self.assertEqual(sum(self.deposits('__rare')['values']), total)

    def test_a_wrong_request_for_deposits_gives_nothing(self):
        empty = {'indexes': [], 'values': []}
        self.assertEqual(self.deposits('nothing'), empty)
        for zone in ('99', 'x', "1' OR 1=1", '1234567'):
            self.assertEqual(self.deposits('common_metal', zone=zone), empty, zone)

    def test_the_bodies_of_a_system_and_their_deposits(self):
        bodies = self.client.get('/api_system_bodies/', {'system': '1001000000055050'}).json()['bodies']
        self.assertEqual([(body['orbit'], body['name']) for body in bodies], [(0, 'Star050'), (1, 'Belt050')])
        self.assertEqual(bodies[1]['deposits'], quadrants.deposits_of_body('100100000005505001', 'asteroid_belt', 'native'))
        for wrong in ('1001000000099099', 'x', "1' OR 1=1"):
            self.assertEqual(self.client.get('/api_system_bodies/', {'system': wrong}).json()['bodies'], [], wrong)

    def test_a_player_name_cant_break_out_of_the_page(self):
        with server_schema('S'):
            Commandant.objects.filter(id=self.rival.id).update(civilisation_name='</script><script>alert(1)</script>')
        self.assertNotContains(self.sector_of(), '<script>alert(1)')


class MapPlacesTests(QuadrantMapFixture):

    def favourite(self, kind, place_id, **extra):
        return self.client.post('/geography_favourite/', {'kind': kind, 'id': place_id, **extra})

    def test_the_last_places_looked_at_come_first_and_only_once(self):
        self.client.get('/geography_quadrant/', {'zone': '1'})
        self.client.get('/geography_system/', {'system_id': '1001000000060070'})
        self.client.get('/geography_quadrant/', {'zone': '2'})
        self.client.get('/geography_quadrant/', {'zone': '1'})
        self.assertEqual(self.commandant_now().recent_places, [
            {'kind': 'zone', 'id': '1', 'name': 'Berceau 1'}, {'kind': 'zone', 'id': '2', 'name': 'Marche 1'},
            {'kind': 'system', 'id': '1001000000060070', 'name': 'Star070'}])

    def test_only_the_ten_last_places_are_kept(self):
        with server_schema('S'):
            Commandant.objects.filter(id=self.commandant.id).update(
                recent_places=[{'kind': 'system', 'id': f'10010000000000{number:02}', 'name': str(number)} for number in range(10)])
        self.client.get('/geography_quadrant/', {'zone': '2'})
        places = self.commandant_now().recent_places
        self.assertEqual(len(places), 10)
        self.assertEqual((places[0]['name'], places[-1]['name']), ('Marche 1', '8'))

    def test_the_page_lists_the_places_without_the_one_on_screen(self):
        self.client.get('/geography_quadrant/', {'zone': '2'})
        response = self.client.get('/geography_quadrant/', {'zone': '1'})
        self.assertEqual([(place['name'], place['url']) for place in response.context['recent_places']], [('Marche 1', '/geography_quadrant/?zone=2')])
        self.assertEqual(response.context['current_place'], {'kind': 'zone', 'id': '1', 'name': 'Berceau 1'})
        self.assertContains(response, 'href="/geography_quadrant/?zone=2"')

    def test_a_favourite_is_added_then_removed_with_the_name_of_the_map(self):
        response = self.favourite('zone', '2', name='<b>Mine</b>')
        self.assertRedirects(response, '/geography_quadrant/?zone=2', fetch_redirect_response=False)
        self.assertEqual(self.commandant_now().favourite_places, [{'kind': 'zone', 'id': '2', 'name': 'Marche 1'}])
        self.assertTrue(self.client.get('/geography_quadrant/', {'zone': '2'}).context['is_favourite'])
        self.favourite('system', '1001000000055050')
        self.assertEqual([place['name'] for place in self.commandant_now().favourite_places], ['Marche 1', 'Star050'])
        self.favourite('zone', '2')
        self.assertEqual([place['name'] for place in self.commandant_now().favourite_places], ['Star050'])

    def test_a_place_that_doesnt_exist_isnt_kept(self):
        for kind, place_id in (('zone', '99'), ('zone', 'x'), ('system', '1001000000099099'), ('sector', '1001000000'), ('zone', "1' OR 1=1")):
            self.assertEqual(self.favourite(kind, place_id).status_code, 302)
        self.assertEqual(self.commandant_now().favourite_places, [])

    def test_a_full_list_of_favourites_refuses_a_new_one_but_can_still_lose_one(self):
        full = [{'kind': 'system', 'id': f'10010000000000{number:02}', 'name': str(number)} for number in range(50)]
        with server_schema('S'):
            Commandant.objects.filter(id=self.commandant.id).update(favourite_places=full)
        self.favourite('zone', '2')
        self.assertEqual(len(self.commandant_now().favourite_places), 50)
        with server_schema('S'):
            Coordinate.objects.create(seed='100100000000000000', type='star', subtype='M', sector_id='1001000000', system_id='1001000000000000',
                                      sys_y=0, sys_x=0, sys_coordinate=0, name='0')
        self.favourite('system', '1001000000000000')
        self.assertEqual(len(self.commandant_now().favourite_places), 49)

    def test_favourites_need_a_post(self):
        self.assertEqual(self.client.get('/geography_favourite/').status_code, 405)


class EconomyPagesTests(EconomyTestCase):

    def setUp(self):
        self.client.force_login(self.user)
        CommandantAccount.objects.create(server_id='S', commandant_id=self.commandant.id, user=self.user, commandant_name='Paullus')
        UserExtended.objects.update_or_create(user=self.user, defaults={'playing_on_server_id': 'S', 'playing_on_commandant': self.commandant.id})

    def post_build(self, **data):
        return self.client.post('/api_build_building/', {'colony_id': self.colony.id, 'district_id': self.central.id, 'building_type': 'well'} | data)

    def test_api_builds_and_pays(self):
        self.assertEqual(self.post_build().status_code, 200)
        self.assertEqual(self.resources()['steel'], 9)
        self.assertEqual(self.post_build().status_code, 400)  # No slot left, and not paid
        self.assertEqual(self.resources()['steel'], 9)

    def test_api_refuses_what_can_not_be_built_there(self):
        for data in ({'building_type': 'too_new'}, {'building_type': 'farm'}, {'building_type': 'unknown'}, {'district_id': 'abc'}):
            self.assertEqual(self.post_build(**data).status_code, 400, data)
        self.assertEqual(self.resources()['steel'], 10)

    def test_api_refuses_the_district_of_another_colony(self):
        with server_schema('S'):
            other = Commandant.objects.create(user=self.user, commandant_name='Other', civilisation_name='Other', creation_date=timezone.now())
            colony = Colony.objects.create(name='Far', owner=other, controller=other, coordinate='1', colony_type='start')
            district = District.objects.create(colony=colony, district_type='central', category='central_district', buildings_slots_free=1)
        self.assertEqual(self.post_build(district_id=district.id).status_code, 400)

    def test_colony_page_offers_what_is_buildable_in_each_district(self):
        response = self.client.get('/colony/', {'colony_id': self.colony.id})
        self.assertContains(response, f'id="modal-build-building-{self.central.id}"')
        trees = next(district for district in response.context['districts'] if district['id'] == str(self.central.id))['construction_trees']
        nodes = {node['internal_name']: node for category in trees for production in category['productions'] for node in production['tree']['buildings']}
        self.assertTrue(nodes['well']['selectable'])
        self.assertFalse(nodes['too_new']['selectable'])  # Shown locked, above what it comes from
        self.assertNotIn('too_old', nodes)  # Obsolete

    def test_resources_page_shows_the_forecast(self):
        self.build(self.central, 'well')
        response = self.client.get('/resources/')
        row = next(resource for resource in response.context['resources'] if resource['name'] == 'water')
        self.assertEqual((row['stock'], row['produced'], row['consumed'], row['balance'], row['self_sustainability']), (3, 4, 2, 2, 200))
        self.assertContains(response, '200 %')



class BuildingsOrdersTests(EconomyTestCase):
    # Steel : forge (1) -> mill (5) -> plant (12, out of reach). In the central district only, the smelter elsewhere.

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        with server_schema('S'):
            for name, data in (('forge', {'tech_available': 1, 'build_cost': {'steel': 3}, 'farming_district': True}),
                               ('mill', {'tech_available': 5, 'build_cost': {'steel': 4}}),
                               ('plant', {'tech_available': 12}),
                               ('smelter', {'tech_available': 6, 'central_district': False, 'farming_district': True})):
                BuildingType.objects.create(internal_name=name, data={'internal_name': name, 'name_fr': name, 'category': 'raw_materials',
                                                                      'production': 'steel', 'central_district': True, 'build_cost': {},
                                                                      'maintenance': {}} | data)
            cls.forge = Building.objects.create(building_type='forge', name_fr='forge', home_district=cls.central)
            District.objects.filter(id=cls.central.id).update(buildings_slots_total=2)
            cls.fields = District.objects.create(colony=cls.colony, district_type='farming', category='farming_district', buildings_slots_total=1)

    def setUp(self):
        self.client.force_login(self.user)
        CommandantAccount.objects.create(server_id='S', commandant_id=self.commandant.id, user=self.user, commandant_name='Paullus')
        UserExtended.objects.update_or_create(user=self.user, defaults={'playing_on_server_id': 'S', 'playing_on_commandant': self.commandant.id})

    def order(self, url, **data):
        return self.client.post(url, {'colony_id': self.colony.id, 'building_id': self.forge.id} | data)

    def reload(self):
        with server_schema('S'):
            return Building.objects.filter(id=self.forge.id).first()

    def test_each_building_comes_from_the_one_it_replaces(self):
        response = self.client.get('/colony/', {'colony_id': self.colony.id})
        central = next(district for district in response.context['districts'] if district['id'] == str(self.central.id))
        category = next(category for category in central['construction_trees'] if category['key'] == 'raw_materials')
        tree = {node['internal_name']: node for node in category['productions'][0]['tree']['buildings']}
        self.assertEqual({name: node['parents'] for name, node in tree.items()}, {'forge': [], 'mill': ['forge'], 'plant': ['mill']})
        self.assertEqual((tree['forge']['grid_column'], tree['mill']['grid_column']), (1, 1))  # One chain, upright
        self.assertGreater(tree['forge']['grid_row'], tree['mill']['grid_row'])  # The lowest level at the bottom
        self.assertEqual({name: node['selectable'] for name, node in tree.items()}, {'forge': True, 'mill': True, 'plant': False})

    def test_the_upgrade_tree_frames_the_building_and_offers_what_it_can_become(self):
        response = self.client.get('/colony/', {'colony_id': self.colony.id})
        building = next(building for district in response.context['districts'] for building in district['buildings']
                        if building['id'] == self.forge.id)
        nodes = {node['internal_name']: node for node in building['upgrade_tree']['buildings']}
        self.assertEqual({name for name, node in nodes.items() if node['current']}, {'forge'})
        self.assertEqual({name for name, node in nodes.items() if node['selectable']}, {'mill'})  # plant : level 12
        self.assertEqual([target['id'] for target in building['relocation_targets']], [self.fields.id])
        self.assertContains(response, f'id="modal-building-{self.forge.id}"')
        self.assertContains(response, 'btree-current')

    def test_upgrade(self):
        for target in ('plant', 'smelter', 'forge', 'well'):  # Out of reach, not in its lineage, itself, another production
            self.assertEqual(self.order('/api_upgrade_building/', building_type=target).status_code, 400, target)
        self.assertEqual(self.order('/api_upgrade_building/', building_type='mill').status_code, 200)
        self.assertEqual((self.reload().building_type, self.reload().name_fr), ('mill', 'mill'))
        self.assertEqual(self.resources()['steel'], 6)

    def test_destroy_refunds_and_frees_the_slot(self):
        self.assertEqual(self.order('/api_destroy_building/').status_code, 200)
        self.assertIsNone(self.reload())
        self.assertEqual(self.resources()['steel'], 12)  # 10 + 75 % of 3
        with server_schema('S'):
            self.assertEqual(District.objects.get(id=self.central.id).buildings_slots_free, 2)

    def test_relocate(self):
        with server_schema('S'):
            other = Commandant.objects.create(user=self.user, commandant_name='Other', civilisation_name='Other', creation_date=timezone.now())
            far = Colony.objects.create(name='Far', owner=other, controller=other, coordinate='1', colony_type='start')
            foreign = District.objects.create(colony=far, district_type='farming', category='farming_district', buildings_slots_total=1)
        for district in (foreign, self.central, self.farming):  # Not his, its own, no free slot
            self.assertEqual(self.order('/api_relocate_building/', district_id=district.id).status_code, 400, district.category)
        self.assertEqual(self.resources()['steel'], 10)

        self.assertEqual(self.order('/api_relocate_building/', district_id=self.fields.id).status_code, 200)
        self.assertEqual(self.reload().home_district_id, self.fields.id)
        self.assertEqual(self.resources()['steel'], 8)  # Half of 3, rounded up
        with server_schema('S'):
            self.assertEqual(District.objects.get(id=self.fields.id).buildings_slots_free, 0)

    def test_activation(self):
        self.assertEqual(self.order('/api_building_set_activation_percent/', activation_percent='40').status_code, 200)
        self.assertEqual(self.reload().activation_percent, 40)
        for value in ('140', '-5', 'x'):
            self.assertEqual(self.order('/api_building_set_activation_percent/', activation_percent=value).status_code, 400, value)

    def test_a_building_of_another_colony_is_refused(self):
        with server_schema('S'):
            colony = Colony.objects.create(name='Mine', owner=self.commandant, controller=self.commandant, coordinate='2', colony_type='start')
        response = self.client.post('/api_destroy_building/', {'colony_id': colony.id, 'building_id': self.forge.id})
        self.assertEqual(response.status_code, 400)  # Not in commandant['colonies'] either
        self.assertIsNotNone(self.reload())


class AuditFixesTests(EconomyTestCase):

    def setUp(self):
        self.client.force_login(self.user)
        CommandantAccount.objects.create(server_id='S', commandant_id=self.commandant.id, user=self.user, commandant_name='Paullus')
        UserExtended.objects.update_or_create(user=self.user, defaults={'playing_on_server_id': 'S', 'playing_on_commandant': self.commandant.id})

    def post_district(self, district_type):
        return self.client.post('/api_build_district/', {'colony_id': self.colony.id, 'district_type': district_type})

    def nb_districts(self):
        with server_schema('S'):
            return District.objects.count()

    def test_api_refuses_a_central_district(self):
        before = self.nb_districts()
        self.assertEqual(self.post_district('central').status_code, 400)
        self.assertEqual(self.nb_districts(), before)

    def test_api_refuses_a_district_beyond_the_tech_level(self):
        with server_schema('S'):
            DistrictType.objects.create(internal_name='future', data={'internal_name': 'future', 'name_fr': 'future', 'category': 'farming_district',
                                                                      'districts_slots': 0, 'build_cost': {}, 'maintenance': {}, 'tech_available': 10})
        before = self.nb_districts()
        self.assertEqual(self.post_district('future').status_code, 400)
        self.assertEqual(self.nb_districts(), before)

    def test_the_colony_page_does_not_ask_the_database_for_each_resource(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get('/colony/', {'colony_id': self.colony.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sum('"game_resource"' in query['sql'] for query in queries), 2)  # One per menu
        self.assertLessEqual(sum('set_config' in query['sql'] for query in queries), 10)

        farming = next(district for district in response.context['buildable_districts'] if district['internal_name'] == 'farming')
        self.assertEqual(farming['maintenance']['steel']['name'], 'steel')
        self.assertEqual(farming['maintenance']['steel']['commandant_storage'], 10)

    def make_report(self, status='unread', title='Report'):
        with server_schema('S'):
            return Report.objects.create(owner=self.commandant, status=status, category='other', category_icon='x', title=title, message='m',
                                         datetime=timezone.now(), tss_calendar=timezone.now())

    def test_opening_an_archived_report_keeps_it_in_the_archives(self):
        report = self.make_report('archived')
        self.client.get('/report/', {'report_id': report.id})
        self.assertEqual(get_report('S', report.id, self.commandant.id)['status'], 'archived')

    def test_opening_a_report_updates_the_badge(self):
        report = self.make_report()
        update_nb_unread_reports('S', self.commandant.id)
        self.assertEqual(get_commandant('S', self.commandant.id)['nb_unread_reports'], 1)
        self.client.get('/report/', {'report_id': report.id})
        self.assertEqual(get_commandant('S', self.commandant.id)['nb_unread_reports'], 0)

    def test_reports_start_with_the_most_recent_and_filter_in_the_database(self):
        ids = [self.make_report(title=f'Title {i}').id for i in range(7)]
        self.make_report('archived', 'Hidden')
        page, unread = get_commandant_reports('S', self.commandant.id, 1, filter_status='not_archived')
        self.assertEqual([report['id'] for report in page], ids[:-6:-1])
        self.assertEqual(page.paginator.count, 7)
        self.assertEqual(unread, {'other': 7, 'all': 7})
        found = get_commandant_reports('S', self.commandant.id, 1, search_text='title 3')[0]
        self.assertEqual([report['id'] for report in found], [ids[3]])

    def test_mark_all_as_read_only_touches_the_category(self):
        self.make_report()
        mark_all_reports_as_read('S', self.commandant.id, 'combat')
        self.assertEqual(get_commandant_reports('S', self.commandant.id)[1]['all'], 1)
        mark_all_reports_as_read('S', self.commandant.id, 'all')
        self.assertEqual(get_commandant_reports('S', self.commandant.id)[1], {'all': 0})

    def end_cycle_order(self, **data):
        User.objects.filter(id=self.user.id).update(is_staff=True)
        return self.client.post('/cycle_monitoring/', {'admin_action': 'end_cycle'} | data)

    def test_double_click_on_the_end_of_the_cycle_passes_one_cycle(self):
        number = cycles.get_current_cycle('S')['cycle_nb']
        self.end_cycle_order(cycle_nb=number)
        self.end_cycle_order(cycle_nb=number)
        self.assertEqual(cycles.get_current_cycle('S')['cycle_nb'], number + 1)

    def test_end_of_the_cycle_needs_its_number(self):
        number = cycles.get_current_cycle('S')['cycle_nb']
        self.end_cycle_order()
        self.assertEqual(cycles.get_current_cycle('S')['cycle_nb'], number)

    def test_end_of_the_cycle_reads_the_shared_tables_once(self):
        with server_schema('S'):
            Commandant.objects.create(user=self.user, commandant_name='Other', civilisation_name='Other', creation_date=timezone.now())
        with CaptureQueriesContext(connection) as queries:
            cycles.end_cycle('S')
        self.assertEqual(sum('"game_buildingtype"' in query['sql'] for query in queries), 1)
        self.assertEqual(sum('"game_districttype"' in query['sql'] for query in queries), 1)


class AccountNamesTests(TestCase):

    def create_user(self, username, email):
        return self.client.post('/create_user/', {'username': username, 'email': email, 'password': 'Xq7!vLp2mZ'})

    def test_username_length_matches_the_message(self):
        self.assertEqual(self.create_user('a' * 4, 'a@example.com').status_code, 400)
        self.assertEqual(self.create_user('b' * 5, 'b@example.com').status_code, 200)
        self.assertEqual(self.create_user('c' * 25, 'c@example.com').status_code, 200)
        self.assertEqual(self.create_user('d' * 26, 'd@example.com').status_code, 400)

    def test_case_does_not_make_another_account(self):
        self.assertEqual(self.create_user('Alice1', 'alice@example.com').status_code, 200)
        self.assertEqual(self.create_user('alice1', 'other@example.com').status_code, 400)
        self.assertEqual(self.create_user('Bob_the_first', 'ALICE@example.com').status_code, 400)

    def test_spaces_and_null_characters_are_removed(self):
        self.assertEqual(self.create_user('       ', 'e@example.com').status_code, 400)
        self.assertEqual(self.create_user('  Carol1 ', 'f@example.com').status_code, 200)
        self.assertTrue(User.objects.filter(username='Carol1').exists())

    def test_commandant_names_are_cleaned(self):
        user = User.objects.create_user('player', 'p@example.com', 'x')
        make_server('S')
        self.client.force_login(user)
        for commandant_name, civilisation_name in (('      ', 'Empire'), ('Paullus', '      '), ('ab\x00c', 'Empire')):
            response = self.client.post('/api_create_commandant/', {'server': 'S', 'commandant_name': commandant_name, 'civilisation_name': civilisation_name})
            self.assertEqual(response.status_code, 400, commandant_name)


class AdministrationRightsTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user('staff', 's@example.com', 'x', is_staff=True)
        cls.admin = User.objects.create_user('admin', 'a@example.com', 'x', is_staff=True, is_superuser=True)
        make_server('S')

    def edit(self, param, value):
        return self.client.post('/admin_servers_states_edit/', {'server_name': 'S', 'type': param, 'value': value})

    def test_the_administration_refuses_the_staff(self):
        self.client.force_login(self.staff)
        for url in ('/admin_main_dashboard/', '/admin_user_accounts/', '/admin_servers_states/', '/admin_message_flags/'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertTrue(response['Location'].startswith('/admin_login/'), url)
        self.edit('status', 'stop')
        self.assertEqual(server_details.get_server_details('S')['status'], 'open')

    def test_superuser_edits_only_the_allowed_values(self):
        self.client.force_login(self.admin)
        self.edit('status', 'stop')
        self.edit('admin_only_visibility', 'true')
        details = server_details.get_server_details('S')
        self.assertEqual((details['status'], details['admin_only_visibility']), ('stop', True))
        for param, value in (('server_name', 'Renamed'), ('status', 'invented'), ('admin_only_visibility', 'maybe'), ('version', '9')):
            self.edit(param, value)
        details = server_details.get_server_details('S')
        self.assertEqual((details['server_name'], details['status'], details['admin_only_visibility'], details['version']), ('S', 'stop', True, 1))


class ReadOnlyTests(EconomyTestCase):
    # A finished server or a dead commandant : everything can be looked at, nothing can be done

    def setUp(self):
        self.client.force_login(self.user)
        CommandantAccount.objects.create(server_id='S', commandant_id=self.commandant.id, user=self.user, commandant_name='Paullus')
        UserExtended.objects.update_or_create(user=self.user, defaults={'playing_on_server_id': 'S', 'playing_on_commandant': self.commandant.id})

    def stop_server(self):
        Server.objects.filter(pk='S').update(status='stop')

    def kill_commandant(self):
        server_details.set_dead_commandant('S', self.commandant.id)

    def test_every_order_api_is_refused(self):
        self.stop_server()
        steel = self.resources()['steel']
        for url in [url for url in API_LOGGED_URLS if url != '/api_create_commandant/']:
            response = self.client.post(url, {'colony_id': self.colony.id, 'district_type': 'farming', 'district_id': self.farming.id,
                                              'building_type': 'farm', 'activation_percent': 50, 'technology': 'x'})
            self.assertEqual(response.status_code, 403, url)
        self.assertEqual(self.resources()['steel'], steel)

    def test_a_dead_commandant_gives_no_order(self):
        self.kill_commandant()
        self.assertEqual(self.client.post('/api_build_building/', {}).status_code, 403)
        self.client.post('/cycle_monitoring/', {'commandant_cycle_status': 'commandant_cycle_finished'})
        self.assertEqual(cycles.get_current_cycle('S')['commandants_cycle_finished'], [])

    def test_an_open_server_still_takes_orders(self):
        self.assertEqual(self.client.post('/api_build_building/', {'colony_id': 'x'}).status_code, 400)

    def test_forms_of_the_pages_change_nothing(self):
        forum_id = forums.get_forum_id('S', 'assembly')
        self.stop_server()
        response = self.client.post(f'/forum/?forum_id={forum_id}', {'action': 'new_topic', 'title': 'Title', 'body': 'Body'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], f'/forum/?forum_id={forum_id}')
        with server_schema('S'):
            self.assertFalse(Post.objects.exists())

    def test_the_end_of_the_cycle_is_refused_even_to_the_staff(self):
        User.objects.filter(id=self.user.id).update(is_staff=True)
        number = cycles.get_current_cycle('S')['cycle_nb']
        self.stop_server()
        self.client.post('/cycle_monitoring/', {'admin_action': 'end_cycle', 'cycle_nb': number})
        self.assertEqual(cycles.get_current_cycle('S')['cycle_nb'], number)

    def test_pages_stay_readable_with_the_banner(self):
        self.stop_server()
        forum_id = forums.get_forum_id('S', 'assembly')
        for url in ('/resources/', '/colonies/', '/reports/', '/cycle_monitoring/', '/technologies/', '/diplomacy/', f'/forum/?forum_id={forum_id}'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertContains(response, 'data-read-only')

    def test_no_banner_on_an_open_server(self):
        self.assertNotContains(self.client.get('/resources/'), 'data-read-only')

    def test_looking_is_no_activity(self):
        self.stop_server()
        self.client.get('/resources/')
        self.assertIsNone(get_commandant('S', self.commandant.id)['time_last_activity'])
        Server.objects.filter(pk='S').update(status='open')
        self.client.get('/resources/')
        self.assertIsNotNone(get_commandant('S', self.commandant.id)['time_last_activity'])

    def test_a_dead_account_can_be_reopened_from_the_account_page(self):
        self.kill_commandant()
        UserExtended.objects.filter(user=self.user).update(playing_on_server=None, playing_on_commandant=None)
        response = self.client.get('/user_account/')
        self.assertEqual([account['read_only'] for account in response.context['accounts']], [True])
        self.client.get('/commandant_login/', {'server': 'S', 'commandant_id': self.commandant.id})
        self.assertContains(self.client.get('/resources/'), 'data-read-only')


class ResearchTests(EconomyTestCase):

    TECHS = (
        {'internal_name': 'root', 'name': 'Root', 'tech_type': 'social', 'tech_level': 0, 'price': {'steel': 2}, 'difficulty': 2},
        {'internal_name': 'next', 'name': 'Next', 'tech_type': 'social', 'tech_level': 0, 'requisite': 'root', 'unlock': 'Campement'},
        {'internal_name': 'later', 'name': 'Later', 'tech_type': 'social', 'tech_level': 1, 'requisite': 'next', 'price': {'steel': 1000}},
        {'internal_name': 'other', 'name': 'Other', 'tech_type': 'biology', 'tech_level': 1, 'requisite': 'root'},
        {'internal_name': 'both', 'name': 'Both', 'tech_type': 'social', 'tech_level': 2, 'requisite': 'later, other '},
        {'internal_name': 'also', 'name': 'Also', 'tech_type': 'social', 'tech_level': 2, 'requisite': 'other'},
        {'internal_name': 'no_level', 'name': 'No level', 'tech_type': 'biology', 'tech_level': None, 'requisite': 'other'},
        {'internal_name': 'itself', 'name': 'Itself', 'tech_type': 'biology', 'tech_level': 3, 'requisite': 'itself'},
    )

    def setUp(self):
        self.client.force_login(self.user)
        CommandantAccount.objects.create(server_id='S', commandant_id=self.commandant.id, user=self.user, commandant_name='Paullus')
        UserExtended.objects.update_or_create(user=self.user, defaults={'playing_on_server_id': 'S', 'playing_on_commandant': self.commandant.id})
        with server_schema('S'):
            Resource.objects.create(internal_name='merchandises_low_tech', data={'internal_name': 'merchandises_low_tech', 'name_fr': 'Marchandises',
                                                                                 'unit_notation': 'Mt', 'icon': 'x.png'})
            for tech in self.TECHS:
                Technology.objects.create(internal_name=tech['internal_name'], data=tech)

    def set_researches(self, **researches):
        with server_schema('S'):
            Commandant.objects.filter(id=self.commandant.id).update(technologies=researches)

    def researches(self):
        return get_commandant('S', self.commandant.id)['technologies']

    def tree(self, **params):
        response = self.client.get('/technologies/', params)
        self.assertEqual(response.status_code, 200)
        return response

    def post_start(self, technology):
        return self.client.post('/api_start_research/', {'technology': technology})

    def test_research_pays_at_start_and_ends_with_the_cycles(self):
        self.assertEqual(self.post_start('root').status_code, 200)
        self.assertEqual((self.researches(), self.resources()['steel']), ({'root': 2}, 8))

        cycles.end_cycle('S')
        self.assertEqual(self.researches(), {'root': 1})
        with server_schema('S'):
            self.assertFalse(Report.objects.filter(owner=self.commandant.id, category='technologies').exists())

        cycles.end_cycle('S')
        self.assertEqual(self.researches(), {'root': 0})
        with server_schema('S'):
            self.assertIn('Root', Report.objects.get(owner=self.commandant.id, category='technologies').message)

        cycles.end_cycle('S')  # Nothing left in progress
        self.assertEqual(self.researches(), {'root': 0})

    def test_refused_researches_cost_nothing(self):
        for technology, researches in (('unknown', {}), ('', {}),
                                       ('next', {}),  # Its requisite is missing
                                       ('next', {'root': 1}),  # Its requisite is still in progress
                                       ('root', {'root': 0}),  # Already researched
                                       ('other', {'root': 0, 'next': 1}),  # Another one in progress
                                       ('later', {'root': 0, 'next': 0}),  # Too expensive
                                       ('itself', {})):  # Requires itself, until the Excel is fixed
            self.set_researches(**researches)
            self.assertEqual(self.post_start(technology).status_code, 400, technology)
            self.assertEqual((self.researches(), self.resources()['steel']), (researches, 10), technology)

    def test_every_requisite_of_the_list_is_needed(self):
        self.set_researches(root=0, next=0, later=0)
        self.assertEqual(self.post_start('both').status_code, 400)
        with server_schema('S'):
            Commandant.objects.filter(id=self.commandant.id).update(resources={'merchandises_low_tech': 6})
        self.set_researches(root=0, next=0, later=0, other=0)
        self.assertEqual(self.post_start('both').status_code, 200)
        self.assertEqual(self.researches()['both'], 3)  # The default duration of its era
        self.assertEqual(self.resources()['merchandises_low_tech'], 0)  # The default price of its era

    def test_one_page_per_category_with_the_latest_era_on_top(self):
        context = self.tree().context
        self.assertEqual(list(context['categories']), ['social', 'biology'])
        self.assertEqual(context['selected_category'], 'social')
        self.assertEqual([era['name'] for era in context['eras']], ['Middle-Tech', 'Low-Tech', 'Époque coloniale'])
        self.assertEqual(self.tree(category='biology').context['selected_category'], 'biology')
        self.assertEqual(self.tree(category='unknown').context['selected_category'], 'social')

    def test_requisite_of_another_category_is_one_small_icon(self):
        response = self.tree()
        techs = {tech['internal_name']: tech for tech in response.context['techs']}
        self.assertEqual(sorted(techs), ['also', 'both', 'later', 'next', 'other', 'root'])
        self.assertTrue(techs['other']['foreign'])
        self.assertContains(response, 'id="tech-node-other" class="tech-ghost', count=1)
        self.assertContains(response, 'id="modal-tech-other"', count=1)
        self.assertEqual(techs['both']['parents'], ['later', 'other'])

    def test_no_two_technologies_on_the_same_spot(self):
        for category in ('social', 'biology'):
            spots = [(tech['level'], tech['grid_row'], tech['grid_column']) for tech in self.tree(category=category).context['techs']]
            self.assertEqual(len(spots), len(set(spots)), spots)

    def test_later_rows_are_above_in_the_era(self):
        techs = {tech['internal_name']: tech for tech in self.tree().context['techs']}
        self.assertLess(techs['next']['grid_row'], techs['root']['grid_row'])

    def test_era_without_a_level_follows_its_requisite(self):
        techs = {tech['internal_name']: tech for tech in self.tree(category='biology').context['techs']}
        self.assertEqual(techs['no_level']['level'], 1)
        self.assertEqual(techs['itself']['status'], 'locked')
        self.assertEqual(techs['itself']['parents'], [])

    def eras(self):
        return {era['name']: era['kind'] for era in self.tree().context['eras']}

    def test_eras_future_and_past(self):
        self.assertEqual(self.eras(), {'Middle-Tech': 'future', 'Low-Tech': 'future', 'Époque coloniale': 'open'})

        self.set_researches(root=0)  # 'other' becomes available in the next era : nothing researchable is ever hidden
        self.assertEqual(self.eras(), {'Middle-Tech': 'future', 'Low-Tech': 'open', 'Époque coloniale': 'open'})

        self.set_researches(root=0, next=0)
        self.assertEqual(self.eras(), {'Middle-Tech': 'future', 'Low-Tech': 'open', 'Époque coloniale': 'past'})

    def test_last_era_stays_when_everything_is_researched(self):
        self.set_researches(**{tech['internal_name']: 0 for tech in self.TECHS})
        self.assertEqual(self.eras(), {'Middle-Tech': 'open', 'Low-Tech': 'past', 'Époque coloniale': 'past'})

    def test_modal_gives_the_costs_and_the_order(self):
        response = self.tree()
        techs = {tech['internal_name']: tech for tech in response.context['techs']}
        self.assertEqual(techs['root']['costs']['steel']['quantity'], 2)
        self.assertEqual(techs['root']['cycles'], 2)
        self.assertEqual(techs['next']['costs']['merchandises_low_tech']['quantity'], 2)  # The default of the empty column
        self.assertEqual(techs['next']['cycles'], 1)
        self.assertContains(response, 'Campement')
        self.assertContains(response, 'value="root"')
        self.assertNotContains(response, 'value="next"')  # Locked

        self.set_researches(root=1)
        self.assertContains(self.tree(), 'class="tech-current"')


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
        with server_schema('S'):
            optimism = Modifier.objects.get()
        self.assertEqual((optimism.modifier_type, optimism.scope, optimism.target, optimism.cycles_left),
                         ('colonial_optimism', 'coordinate', commandant['native_planet'], 10))
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

    def test_a_new_player_joins_the_current_cycle(self):
        cycles.create_cycle_entry('S')
        create_commandant('S', 'player', 'Paullus', 'Empire')
        with server_schema('S'):
            commandant_id = Commandant.objects.get().id
        self.assertEqual(cycles.get_current_cycle('S')['commandants_cycle_playing'], [commandant_id])

    def test_only_one_commandant_per_server(self):
        create_commandant('S', 'player', 'Paullus', 'Empire')
        with self.assertRaises(GameError):
            create_commandant('S', 'player', 'Varro', 'Royaume')
        self.assertEqual(CommandantAccount.objects.count(), 1)

    def test_a_dead_commandant_leaves_its_place_on_the_server(self):
        create_commandant('S', 'player', 'Paullus', 'Empire')
        CommandantAccount.objects.update(status='dead')
        create_commandant('S', 'player', 'Varro', 'Royaume')
        self.assertEqual(CommandantAccount.objects.count(), 2)

    def test_only_one_exclusive_server_at_a_time(self):
        Server.objects.update(exclusive=True)
        create_commandant('S', 'player', 'Paullus', 'Empire')
        with self.assertRaises(GameError):
            create_commandant('Other', 'player', 'Varro', 'Royaume')
        with server_schema('Other'):
            self.assertFalse(Commandant.objects.exists())

    def test_a_free_server_comes_on_top_of_an_exclusive_one(self):
        Server.objects.filter(pk='S').update(exclusive=True)
        create_commandant('S', 'player', 'Paullus', 'Empire')
        create_commandant('Other', 'player', 'Varro', 'Royaume')
        self.assertEqual(CommandantAccount.objects.count(), 2)

    def test_a_finished_exclusive_server_no_longer_counts(self):
        Server.objects.update(exclusive=True)
        create_commandant('S', 'player', 'Paullus', 'Empire')
        Server.objects.filter(pk='S').update(status='stop')
        create_commandant('Other', 'player', 'Varro', 'Royaume')
        self.assertEqual(CommandantAccount.objects.count(), 2)

    def test_commandants_of_a_sector_share_their_native_entente(self):
        create_commandant('S', 'player', 'Paullus', 'Empire')
        User.objects.create_user('player2', 'p2@example.com', 'x')
        create_commandant('S', 'player2', 'Varro', 'Royaume')
        with server_schema('S'):
            entente = Entente.objects.get()
            self.assertEqual(entente.native_sector, '1001000000')
            self.assertEqual(set(Commandant.objects.values_list('native_entente', flat=True)), {entente.id})
        details = ententes.get_entente('S', entente.id, None)
        self.assertEqual(details['name'], 'Natifs du secteur 0-0')
        self.assertEqual([member['name'] for member in details['members']], ['Paullus', 'Varro'])


class EntentesTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('player', 'p@example.com', 'x')
        cls.other_user = User.objects.create_user('other_player', 'o@example.com', 'x')
        for user in (cls.user, cls.other_user):
            UserExtended.objects.update_or_create(user=user, defaults={'language': 'fr'})
        make_server('S')
        with server_schema('S'):
            cls.founder, cls.visitor = [
                Commandant.objects.create(user=user, commandant_name=name, civilisation_name=name, creation_date=timezone.now()).id
                for user, name in ((cls.user, 'Paullus'), (cls.other_user, 'Varro'))]
        cycles.create_cycle_entry('S')

    def setUp(self):
        self.entente = ententes.found_entente('S', self.founder, 'La Ligue', 'economic', 'Commerce')

    def play(self, user, commandant_id):
        UserExtended.objects.filter(user=user).update(playing_on_server_id='S', playing_on_commandant=commandant_id)
        self.client.force_login(user)

    def status(self, commandant_id, entente=None):
        return ententes.get_entente('S', entente or self.entente, commandant_id)['status']

    def report_titles(self, commandant_id):
        with server_schema('S'):
            return list(Report.objects.filter(owner_id=commandant_id).order_by('id').values_list('title', flat=True))

    def native_entente(self):
        with server_schema('S'):
            commandant = Commandant.objects.get(id=self.visitor)
            commandant.native_sector = '1001002005'
            ententes.join_native_entente('S', commandant)
            return commandant.native_entente_id

    def test_founder_is_the_first_member(self):
        details = ententes.get_entente('S', self.entente, self.founder)
        self.assertEqual((details['status'], details['is_owner'], details['can_apply']), ('member', True, False))
        self.assertEqual(details['category_label'], 'Économique')
        self.assertEqual([member['id'] for member in details['members']], [self.founder])

    def test_founding_is_refused_with_a_bad_category_or_a_name_taken(self):
        for name, category in (('Autre', 'piracy'), ('LA LIGUE', 'military'), ('', 'military'), ('x' * 61, 'military')):
            with self.subTest(name=name, category=category), self.assertRaises(GameError):
                ententes.found_entente('S', self.visitor, name, category, '')

    def test_number_of_founded_ententes_is_limited(self):
        for number in range(ententes.MAX_OWNED_ENTENTES - 1):
            ententes.found_entente('S', self.founder, f'Ligue {number}', 'other', '')
        with self.assertRaises(GameError):
            ententes.found_entente('S', self.founder, 'Ligue de trop', 'other', '')
        ententes.found_entente('S', self.visitor, 'La sienne', 'other', '')

    def test_accepted_application_makes_a_member(self):
        ententes.apply_to_entente('S', self.entente, self.visitor, 'Je viens en paix')
        self.assertEqual(self.status(self.visitor), 'applicant')
        self.assertEqual(ententes.get_entente('S', self.entente, self.visitor)['my_application'], 'Je viens en paix')
        self.assertEqual(ententes.count_pending_answers('S', self.founder), 1)

        ententes.answer_application('S', self.entente, self.founder, self.visitor, True)
        ententes.answer_application('S', self.entente, self.founder, self.visitor, True)  # Twice sends a single report
        self.assertEqual(self.status(self.visitor), 'member')
        self.assertEqual(ententes.count_pending_answers('S', self.founder), 0)
        self.assertEqual(self.report_titles(self.visitor), ['Candidature acceptée'])

    def test_refused_applicant_can_apply_again(self):
        ententes.apply_to_entente('S', self.entente, self.visitor, '')
        ententes.answer_application('S', self.entente, self.founder, self.visitor, False)
        self.assertIsNone(self.status(self.visitor))
        self.assertEqual(self.report_titles(self.visitor), ['Candidature refusée'])
        ententes.apply_to_entente('S', self.entente, self.visitor, '')
        self.assertEqual(self.status(self.visitor), 'applicant')

    def test_applications_are_only_shown_to_the_founder(self):
        ententes.apply_to_entente('S', self.entente, self.visitor, 'Secret')
        self.assertEqual(ententes.get_entente('S', self.entente, self.founder)['applications'][0]['application'], 'Secret')
        self.assertEqual(ententes.get_entente('S', self.entente, self.visitor)['applications'], [])
        self.assertEqual(ententes.get_ententes('S', self.visitor)['others'][0]['nb_applications'], 0)
        self.assertEqual(ententes.get_ententes('S', self.founder)['mine'][0]['nb_applications'], 1)
        self.assertEqual([member['id'] for member in ententes.get_entente('S', self.entente, self.visitor)['members']], [self.founder])

    def test_orders_of_a_founder_are_refused_to_the_others(self):
        ententes.apply_to_entente('S', self.entente, self.visitor, '')
        for refused in (lambda: ententes.answer_application('S', self.entente, self.visitor, self.visitor, True),
                        lambda: ententes.exclude_member('S', self.entente, self.visitor, self.founder),
                        lambda: ententes.update_entente_description('S', self.entente, self.visitor, 'Hop'),
                        lambda: ententes.dissolve_entente('S', self.entente, self.visitor)):
            with self.assertRaises(GameError):
                refused()
        self.assertEqual(self.status(self.visitor), 'applicant')

    def test_applying_changes_nothing_for_a_member(self):
        ententes.apply_to_entente('S', self.entente, self.founder, '')
        self.assertEqual(self.status(self.founder), 'member')

    def test_founder_stays_until_dissolving(self):
        ententes.leave_entente('S', self.entente, self.founder)
        ententes.exclude_member('S', self.entente, self.founder, self.founder)
        self.assertEqual(self.status(self.founder), 'member')

    def test_member_can_leave_or_be_excluded(self):
        for remove in (lambda: ententes.leave_entente('S', self.entente, self.visitor),
                       lambda: ententes.exclude_member('S', self.entente, self.founder, self.visitor)):
            ententes.apply_to_entente('S', self.entente, self.visitor, '')
            ententes.answer_application('S', self.entente, self.founder, self.visitor, True)
            remove()
            self.assertIsNone(self.status(self.visitor))
        self.assertEqual(self.report_titles(self.visitor)[-1], "Exclusion d'une entente")

    def test_dissolving_warns_members_and_applicants_and_frees_the_name(self):
        ententes.apply_to_entente('S', self.entente, self.visitor, '')
        ententes.dissolve_entente('S', self.entente, self.founder)
        self.assertIsNone(ententes.get_entente('S', self.entente, self.founder))
        self.assertEqual(self.report_titles(self.visitor), ['Entente dissoute'])
        self.assertEqual(self.report_titles(self.founder), [])
        ententes.found_entente('S', self.visitor, 'La Ligue', 'other', '')

    def test_native_entente_is_closed(self):
        native = self.native_entente()
        details = ententes.get_entente('S', native, self.founder)
        self.assertEqual(details['name'], 'Natifs du secteur 2-5')
        self.assertFalse(details['can_apply'])
        with self.assertRaises(GameError):
            ententes.apply_to_entente('S', native, self.founder, '')
        ententes.leave_entente('S', native, self.visitor)
        self.assertEqual(self.status(self.visitor, native), 'member')
        self.assertEqual(ententes.get_ententes('S', self.visitor)['mine'][0]['id'], native)

    # Roles

    def join(self, commandant_id):
        ententes.apply_to_entente('S', self.entente, commandant_id, '')
        ententes.answer_application('S', self.entente, self.founder, commandant_id, True)

    def role_id(self, name):
        with server_schema('S'):
            return EntenteRole.objects.get(entente_id=self.entente, name=name).id

    def role_of(self, commandant_id):
        members = ententes.get_entente('S', self.entente, self.founder)['members']
        return next(member['role_name'] for member in members if member['id'] == commandant_id)

    def give_role(self, commandant_id, name, options):
        ententes.create_role('S', self.entente, self.founder, name, options)
        ententes.set_member_role('S', self.entente, self.founder, commandant_id, self.role_id(name))

    def third_member(self):
        with server_schema('S'):
            third = Commandant.objects.create(user=self.user, commandant_name='Kyu', civilisation_name='Kyu', creation_date=timezone.now()).id
        self.join(third)
        return third

    def test_default_roles_are_owner_and_member(self):
        self.join(self.visitor)
        self.assertEqual(self.role_of(self.founder), 'Propriétaire')
        self.assertEqual(self.role_of(self.visitor), 'Membre')
        details = ententes.get_entente('S', self.entente, self.visitor)
        self.assertEqual([(role['name'], role['options'], role['nb_members']) for role in details['roles']], [('Membre', [], 1)])
        self.assertFalse(details['can_invite'] or details['can_manage_roles'])

    def test_ownership_only_changes_hands(self):
        self.join(self.visitor)
        with self.assertRaises(GameError):
            ententes.transfer_ownership('S', self.entente, self.visitor, self.visitor)
        with self.assertRaises(GameError):  # Not a member
            ententes.transfer_ownership('S', self.entente, self.founder, self.founder)

        ententes.transfer_ownership('S', self.entente, self.founder, self.visitor)
        self.assertEqual(self.role_of(self.visitor), 'Propriétaire')
        self.assertEqual(self.role_of(self.founder), 'Membre')
        self.assertEqual(self.report_titles(self.visitor)[-1], "Propriété d'une entente")
        self.assertFalse(ententes.get_entente('S', self.entente, self.founder)['is_owner'])
        ententes.update_entente_description('S', self.entente, self.visitor, 'Nouveau')
        with self.assertRaises(GameError):
            ententes.dissolve_entente('S', self.entente, self.founder)

    def test_owner_has_no_role_to_change(self):
        self.join(self.visitor)
        self.give_role(self.visitor, 'Second', ['manage_roles'])
        with self.assertRaises(GameError):
            ententes.set_member_role('S', self.entente, self.visitor, self.founder, self.role_id('Second'))
        with self.assertRaises(GameError):
            ententes.set_member_role('S', self.entente, self.founder, self.founder, self.role_id('Second'))
        self.assertEqual(self.role_of(self.founder), 'Propriétaire')

    def test_option_invite_opens_the_applications(self):
        self.join(self.visitor)
        third = self.third_member()
        ententes.leave_entente('S', self.entente, third)
        ententes.apply_to_entente('S', self.entente, third, 'Secret')
        self.assertEqual(ententes.get_entente('S', self.entente, self.visitor)['applications'], [])
        self.assertEqual(ententes.count_pending_answers('S', self.visitor), 0)
        with self.assertRaises(GameError):
            ententes.answer_application('S', self.entente, self.visitor, third, True)

        self.give_role(self.visitor, 'Recruteur', ['invite_member'])
        self.assertEqual(ententes.get_entente('S', self.entente, self.visitor)['applications'][0]['application'], 'Secret')
        self.assertEqual(ententes.count_pending_answers('S', self.visitor), 1)
        ententes.answer_application('S', self.entente, self.visitor, third, True)
        self.assertEqual(self.status(third), 'member')

    def test_option_exclude_stops_at_the_owner_and_at_more_options(self):
        self.join(self.visitor)
        third = self.third_member()
        with self.assertRaises(GameError):
            ententes.exclude_member('S', self.entente, self.visitor, third)

        self.give_role(self.visitor, 'Garde', ['exclude_member'])
        ententes.exclude_member('S', self.entente, self.visitor, self.founder)
        self.assertEqual(self.status(self.founder), 'member')

        self.give_role(third, 'Chef', ['exclude_member', 'manage_finances'])
        with self.assertRaises(GameError):
            ententes.exclude_member('S', self.entente, self.visitor, third)
        details = ententes.get_entente('S', self.entente, self.visitor)
        self.assertEqual([member['can_exclude'] for member in details['members']], [False, False, False])

        ententes.update_role('S', self.entente, self.founder, self.role_id('Chef'), 'Chef', ['exclude_member'])
        ententes.exclude_member('S', self.entente, self.visitor, third)
        self.assertIsNone(self.status(third))

    def test_role_manager_cannot_raise_any_rights(self):
        self.join(self.visitor)
        third = self.third_member()
        self.give_role(self.visitor, 'Second', ['manage_roles'])
        all_options = list(ententes.role_options())

        # What isn't held can't be given, neither to a new role nor to an existing one
        ententes.create_role('S', self.entente, self.visitor, 'Faux', all_options)
        ententes.update_role('S', self.entente, self.visitor, self.role_id('Second'), 'Second', all_options)
        with server_schema('S'):
            self.assertEqual(EntenteRole.objects.get(id=self.role_id('Faux')).options, ['manage_roles'])
            self.assertEqual(EntenteRole.objects.get(id=self.role_id('Second')).options, ['manage_roles'])

        # A role with more options stays out of reach
        ententes.create_role('S', self.entente, self.founder, 'Chef', ['manage_roles', 'manage_finances'])
        chef = self.role_id('Chef')
        for refused in (lambda: ententes.update_role('S', self.entente, self.visitor, chef, 'Hop', []),
                        lambda: ententes.delete_role('S', self.entente, self.visitor, chef),
                        lambda: ententes.set_member_role('S', self.entente, self.visitor, self.visitor, chef)):
            with self.assertRaises(GameError):
                refused()
        self.assertEqual(self.role_of(self.visitor), 'Second')

        # And so does a member who holds it
        ententes.set_member_role('S', self.entente, self.founder, third, chef)
        with self.assertRaises(GameError):
            ententes.set_member_role('S', self.entente, self.visitor, third, self.role_id('Second'))

    def test_role_manager_keeps_out_of_the_orders_of_the_owner(self):
        self.join(self.visitor)
        self.give_role(self.visitor, 'Second', list(ententes.role_options()))
        for refused in (lambda: ententes.transfer_ownership('S', self.entente, self.visitor, self.visitor),
                        lambda: ententes.dissolve_entente('S', self.entente, self.visitor),
                        lambda: ententes.update_entente_description('S', self.entente, self.visitor, 'Hop')):
            with self.assertRaises(GameError):
                refused()

    def test_role_names_and_deletion(self):
        self.join(self.visitor)
        self.give_role(self.visitor, 'Second', ['shared_radar'])
        for name in ('Membre', 'PROPRIÉTAIRE', 'owner', 'second', '', 'x' * 41):
            with self.subTest(name=name), self.assertRaises(GameError):
                ententes.create_role('S', self.entente, self.founder, name, [])

        # The default role keeps its name, its options can change, and it can't be deleted
        with server_schema('S'):
            default = EntenteRole.objects.get(entente_id=self.entente, is_default=True).id
        ententes.update_role('S', self.entente, self.founder, default, 'Renommé', ['shared_radar'])
        with server_schema('S'):
            self.assertEqual(EntenteRole.objects.get(id=default).name, '')
            self.assertEqual(EntenteRole.objects.get(id=default).options, ['shared_radar'])
        with self.assertRaises(GameError):
            ententes.delete_role('S', self.entente, self.founder, default)

        ententes.delete_role('S', self.entente, self.founder, self.role_id('Second'))
        self.assertEqual(self.role_of(self.visitor), 'Membre')

    def test_roles_of_another_entente_are_refused(self):
        self.join(self.visitor)
        other = ententes.found_entente('S', self.founder, 'Autre', 'other', '')
        ententes.create_role('S', other, self.founder, 'Etranger', [])
        with server_schema('S'):
            foreign = EntenteRole.objects.get(name='Etranger').id
        with self.assertRaises(GameError):
            ententes.set_member_role('S', self.entente, self.founder, self.visitor, foreign)
        with self.assertRaises(GameError):
            ententes.update_role('S', self.entente, self.founder, foreign, 'Hop', [])

    def test_options_of_the_roles_are_hidden_from_the_outsiders(self):
        self.assertEqual(ententes.get_entente('S', self.entente, self.visitor)['roles'], [])

    def test_native_entente_has_no_roles(self):
        native = self.native_entente()
        details = ententes.get_entente('S', native, self.visitor)
        self.assertEqual(details['roles'], [])
        self.assertEqual(details['members'][0]['role_name'], 'Membre')
        for refused in (lambda: ententes.create_role('S', native, self.visitor, 'Chef', []),
                        lambda: ententes.invite_to_entente('S', native, self.visitor, 'Paullus')):
            with self.assertRaises(GameError):
                refused()

    # Invitations

    def test_invitation_accepted_or_declined(self):
        ententes.invite_to_entente('S', self.entente, self.founder, 'varro')
        ententes.invite_to_entente('S', self.entente, self.founder, 'Varro')  # Twice sends a single report
        self.assertEqual(self.status(self.visitor), 'invited')
        self.assertEqual(self.report_titles(self.visitor), ['Invitation dans une entente'])
        self.assertEqual(ententes.count_pending_answers('S', self.visitor), 1)
        self.assertEqual(ententes.get_ententes('S', self.visitor)['invited'][0]['id'], self.entente)

        ententes.answer_invitation('S', self.entente, self.visitor, False)
        self.assertIsNone(self.status(self.visitor))
        with self.assertRaises(GameError):
            ententes.answer_invitation('S', self.entente, self.visitor, True)

        ententes.invite_to_entente('S', self.entente, self.founder, 'Varro')
        ententes.answer_invitation('S', self.entente, self.visitor, True)
        self.assertEqual(self.status(self.visitor), 'member')
        self.assertEqual(self.role_of(self.visitor), 'Membre')
        self.assertEqual(ententes.count_pending_answers('S', self.visitor), 0)

    def test_invitation_rights(self):
        with self.assertRaises(GameError):
            ententes.invite_to_entente('S', self.entente, self.visitor, 'Paullus')
        with self.assertRaises(GameError):
            ententes.invite_to_entente('S', self.entente, self.founder, 'Inconnu')
        with self.assertRaises(GameError):  # Already a member
            ententes.invite_to_entente('S', self.entente, self.founder, 'Paullus')

    def test_inviting_an_applicant_admits_them(self):
        ententes.apply_to_entente('S', self.entente, self.visitor, '')
        ententes.invite_to_entente('S', self.entente, self.founder, 'Varro')
        self.assertEqual(self.status(self.visitor), 'member')
        self.assertEqual(self.role_of(self.visitor), 'Membre')

    def test_pages_of_the_roles(self):
        url = f'/entente/?entente_id={self.entente}'
        self.join(self.visitor)
        self.play(self.user, self.founder)
        self.assertContains(self.client.get(url), 'Créer un rôle')

        self.client.post(url, {'action': 'create_role', 'role_name': 'Amiral', 'options': ['shared_fleets', 'pirate']})
        role = self.role_id('Amiral')
        with server_schema('S'):
            self.assertEqual(EntenteRole.objects.get(id=role).options, ['shared_fleets'])
        self.client.post(url, {'action': 'set_role', 'commandant_id': self.visitor, 'role_id': role})
        self.assertEqual(self.role_of(self.visitor), 'Amiral')
        response = self.client.post(url, {'action': 'create_role', 'role_name': 'Membre'})
        self.assertContains(response, 'Ce nom est réservé')

        self.client.post(url, {'action': 'update_role', 'role_id': role, 'role_name': 'Amirale', 'options': ['shared_radar']})
        self.assertEqual(self.role_of(self.visitor), 'Amirale')

        self.play(self.other_user, self.visitor)
        response = self.client.get(url)
        self.assertContains(response, 'Vision radar partagée')
        self.assertNotContains(response, 'Créer un rôle')
        self.assertNotContains(response, 'Inviter un commandant')
        self.assertNotContains(response, 'Céder')

        self.play(self.user, self.founder)
        self.client.post(url, {'action': 'invite', 'invited_name': 'Paullus'})
        self.client.post(url, {'action': 'delete_role', 'role_id': role})
        self.assertEqual(self.role_of(self.visitor), 'Membre')
        self.client.post(url, {'action': 'transfer', 'commandant_id': self.visitor})
        self.assertEqual(self.role_of(self.visitor), 'Propriétaire')

    def test_migration_gives_a_default_role_to_the_existing_ententes(self):
        self.join(self.visitor)
        native = self.native_entente()
        with server_schema('S'):
            EntenteRole.objects.all().delete()
            import_module('game.migrations.0006_entente_roles').create_default_roles(apps, None)
            role = EntenteRole.objects.get(entente_id=self.entente)
            self.assertTrue(role.is_default)
            self.assertFalse(EntenteRole.objects.filter(entente_id=native).exists())
            self.assertEqual(EntenteMember.objects.get(entente_id=self.entente, commandant_id=self.visitor).role, role)
            self.assertIsNone(EntenteMember.objects.get(entente_id=self.entente, commandant_id=self.founder).role)

    def test_migration_gathers_the_existing_commandants(self):
        with server_schema('S'):
            Commandant.objects.filter(id=self.visitor).update(native_sector='1001002005')
            import_module('game.migrations.0005_ententes').create_native_ententes(apps, None)
            self.assertEqual(Commandant.objects.get(id=self.visitor).native_entente.native_sector, '1001002005')
            self.assertIsNone(Commandant.objects.get(id=self.founder).native_entente)  # No sector : only in the tests
            self.assertEqual(EntenteMember.objects.filter(commandant_id=self.visitor).count(), 1)

    def test_pages_from_the_list_to_the_application(self):
        native = self.native_entente()
        url = f'/entente/?entente_id={self.entente}'
        self.play(self.other_user, self.visitor)

        response = self.client.get('/diplomacy/')
        self.assertContains(response, 'La Ligue')
        self.assertContains(response, 'Natifs du secteur 2-5')
        self.assertContains(self.client.get(url), 'Envoyer ma candidature')
        self.assertNotContains(self.client.get(f'/entente/?entente_id={native}'), 'Envoyer ma candidature')
        self.assertRedirects(self.client.get('/entente/?entente_id=999'), '/diplomacy/')

        self.client.post(url, {'action': 'apply', 'application': 'Bonjour'})
        self.assertContains(self.client.get(url), 'Retirer ma candidature')

        self.play(self.user, self.founder)
        self.assertContains(self.client.get('/diplomacy/'), '<span class="badge badge-warning right">1</span>', html=True)
        self.assertContains(self.client.get(url), 'Bonjour')
        self.client.post(url, {'action': 'accept', 'commandant_id': self.visitor})
        self.assertEqual(self.status(self.visitor), 'member')
        self.client.post(url, {'action': 'exclude', 'commandant_id': self.visitor})
        self.assertIsNone(self.status(self.visitor))

        response = self.client.post('/diplomacy/', {'name': 'La Ligue', 'category': 'other'})
        self.assertContains(response, 'Ce nom est déjà pris')
        response = self.client.post('/diplomacy/', {'name': 'Le Temple', 'category': 'religious', 'description': '<script>'}, follow=True)
        self.assertContains(response, 'Religieuse')
        self.assertContains(response, '&lt;script&gt;')

        self.client.post(url, {'action': 'dissolve'})
        self.assertIsNone(ententes.get_entente('S', self.entente, self.founder))


class ArchivesTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        user = User.objects.create_user('player', 'p@example.com', 'x')
        make_server('Current')
        server_details.create_server('Old', 1, status='stop', admin_only_visibility=False)
        server_details.create_server('Dead', 1, status='dead', admin_only_visibility=False)
        server_details.create_server('Trial', 1, status='test', admin_only_visibility=False)
        server_details.create_server('Hidden', 1, status='open', admin_only_visibility=True)
        with server_schema('Old'):
            cls.author = Commandant.objects.create(user=user, commandant_name='Paullus', civilisation_name='Rome', creation_date=timezone.now()).id
        cls.topic_id = forums.create_topic('Old', forums.get_forum_id('Old', 'assembly'), cls.author, 'Discours du senat', 'Citoyens...')

    def test_anybody_finds_the_current_and_past_servers_but_no_other(self):
        response = self.client.get('/archives/')
        self.assertEqual([server['server_name'] for server in response.context['servers']], ['Dead', 'Old', 'Current'])
        self.assertNotContains(response, 'Trial')
        self.assertNotContains(response, 'Hidden')

    def test_anybody_reads_an_assembly_without_any_form(self):
        for url, text in (('/archives/?server=Old', 'Discours du senat'), (f'/archives/?server=Old&topic_id={self.topic_id}', 'Citoyens...')):
            response = self.client.get(url)
            self.assertContains(response, text)
            for tag in ('<form', '<textarea', '<button type="submit"'):
                self.assertNotContains(response, tag)

    def test_writing_is_refused(self):
        for url in ('/archives/?server=Old', f'/archives/?server=Old&topic_id={self.topic_id}'):
            self.assertEqual(self.client.post(url, {'action': 'new_topic', 'title': 'Spam', 'body': 'Spam'}).status_code, 405)
        self.assertEqual(forums.get_topics('Old', forums.get_forum_id('Old', 'assembly'), 1, None).paginator.count, 1)

    def test_reading_counts_nothing(self):
        self.client.get(f'/archives/?server=Old&topic_id={self.topic_id}')
        self.assertEqual(forums.get_topics('Old', forums.get_forum_id('Old', 'assembly'), 1, None)[0]['nb_views'], 0)

    def test_other_forums_stay_out_of_the_archives(self):
        public_tavern = forums.create_player_forum('Old', self.author, 'La Taverne', '', False)
        private_tavern = forums.create_player_forum('Old', self.author, 'Le Repaire', '', True)
        coalition = forums.create_coalition('Old', self.author, 'La Ligue')
        for forum_id in (public_tavern, private_tavern, coalition, forums.get_forum_id('Old', 'hrp')):
            topic_id = forums.create_topic('Old', forum_id, self.author, 'Secret', 'Secret')
            self.assertRedirects(self.client.get(f'/archives/?server=Old&topic_id={topic_id}'), '/archives/', fetch_redirect_response=False)

    def test_forbidden_or_unknown_ids_send_back_to_the_list(self):
        for url in ('/archives/?server=Trial', '/archives/?server=Trial&topic_id=1', '/archives/?server=Hidden','/archives/?server=Nope', '/archives/?server=',
                    '/archives/?server=Old&topic_id=abc', '/archives/?server=Old&topic_id=999999', '/archives/?server=Old&topic_id='):
            self.assertRedirects(self.client.get(url), '/archives/', fetch_redirect_response=False)


class TextFormattingTests(SimpleTestCase):

    def test_styles_alignments_sizes_and_colors(self):
        self.assertEqual(bbcode('[b]a[/b][i]b[/i][u]c[/u][s]d[/s]'), '<strong>a</strong><em>b</em><u>c</u><s>d</s>')
        self.assertEqual(bbcode('[center]a[/center]'), '<div class="text-center">a</div>')
        self.assertEqual(bbcode('[size=5]a[/size]'), '<span style="font-size:1.5rem">a</span>')
        self.assertEqual(bbcode('[color=#FF0000]a[/color]'), '<span style="color:#FF0000">a</span>')
        self.assertEqual(bbcode('[B]a[/B]'), '<strong>a</strong>')

    def test_new_lines(self):
        self.assertEqual(bbcode('a\r\nb'), 'a<br>b')
        self.assertEqual(bbcode('a\n[center]b[/center]\nc'), 'a<div class="text-center">b</div>c')

    def test_links(self):
        link = '<a href="https://a.fr/?x=1&amp;y=2" target="_blank" rel="nofollow noopener noreferrer">'
        self.assertEqual(bbcode('[url=https://a.fr/?x=1&y=2]ici[/url]'), link + 'ici</a>')
        self.assertEqual(bbcode('[url]https://a.fr/?x=1&y=2[/url]'), link + 'https://a.fr/?x=1&amp;y=2</a>')
        self.assertIn('<a href="https://a.fr"', bbcode('voir https://a.fr'))
        self.assertEqual(bbcode('[url=https://a.fr]https://b.fr[/url]').count('<a '), 1)  # No link in a link

    def test_everything_is_escaped(self):
        self.assertEqual(bbcode('<b onclick="x">&'), '&lt;b onclick=&quot;x&quot;&gt;&amp;')
        self.assertEqual(bbcode('[b]<img src=x>[/b]'), '<strong>&lt;img src=x&gt;</strong>')

    def test_refused_values_stay_as_typed(self):
        for text in ('[url=javascript:alert(1)]a[/url]', '[url=data:text/html,x]a[/url]', '[url]javascript:alert(1)[/url]', '[url=]a[/url]',
                     '[url=https://a.fr" onclick="x]a[/url]', '[color=red;background:url(x)]a[/color]', '[color=#12]a[/color]',
                     '[size=8]a[/size]', '[size=1;position:fixed]a[/size]', '[b=x]a'):
            result = bbcode(text)
            self.assertNotIn('<a ', result, text)
            self.assertNotIn('<span', result, text)
            self.assertNotIn('<strong', result, text)

    def test_no_external_content_is_embedded(self):
        for text in ('[img]https://a.fr/b.png[/img]', '[video]https://youtu.be/x[/video]', '[iframe]https://a.fr[/iframe]', '<iframe src="https://a.fr"></iframe>'):
            result = bbcode(text)
            for tag in ('<img', '<video', '<iframe', '<embed', '<object'):
                self.assertNotIn(tag, result, text)
        self.assertIn('<a href="https://youtu.be/x"', bbcode('https://youtu.be/x'))

    def test_the_page_around_stays_balanced(self):
        self.assertEqual(bbcode('[center]a'), '<div class="text-center">a</div>')
        self.assertEqual(bbcode('a[/center]'), 'a[/center]')
        self.assertEqual(bbcode('[b][i]a[/b]c[/i]'), '<strong><em>a</em></strong>c[/i]')
        self.assertEqual(bbcode('[b]' * 1000).count('<strong>'), MAX_DEPTH)
        self.assertEqual(bbcode('[b]' * 1000).count('</strong>'), MAX_DEPTH)


class ServerConfigTests(TestCase):

    def test_the_sheet_config_of_the_excels_reaches_the_server(self):
        for excel, gameplay, hours in (('TSS.xlsx', 'saga', (22, 8, 4)), ('TSS_boardgame.xlsx', 'skirmish', (22, None, None))):
            make_server(excel)
            server_details.set_server_config(excel, excel_importer(excel, 'Config')[0])
            details = server_details.get_server_details(excel)
            self.assertEqual((details['gameplay'], details['delay_first_cycle']), (gameplay, True))
            self.assertEqual((details['hour_cycle'], details['hour_first_combat_round'], details['hour_anticheat_checks']), hours)

    def test_an_hour_left_out_is_no_automatic_step(self):
        make_server('S')
        server_details.set_server_config('S', {'gameplay_type': 'saga', 'hour_cycle': 22})
        details = server_details.get_server_details('S')
        self.assertEqual((details['hour_cycle'], details['hour_anticheat_checks'], details['delay_first_cycle']), (22, None, False))

    def test_a_wrong_config_stops_the_creation(self):
        make_server('S')
        valid = {'gameplay_type': 'saga', 'delay_first_cycle': True, **{hour: 3 for hour in SERVER_HOURS}}
        server_details.set_server_config('S', valid)
        for wrong in ({'invented': 1}, {'gameplay_type': 'chess'}, {'hour_cycle': 24}, {'hour_cycle': -1}, {'hour_cycle': 4.5}, {'hour_cycle': 'noon'},
                      {'delay_first_cycle': 'yes'}, {'delay_first_cycle': None}):
            with self.assertRaises(Exception, msg=wrong):
                server_details.set_server_config('S', valid | wrong)

    def test_the_database_refuses_a_wrong_hour_set_by_hand(self):
        make_server('S')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Server.objects.filter(pk='S').update(hour_anticheat_checks=24)


class AnticheatTestCase(TestCase):

    now = datetime(2026, 7, 10, 2, 30, tzinfo=dt_timezone.utc)  # 4:30 in Paris

    @classmethod
    def setUpTestData(cls):
        make_server('S')
        cls.users = [User.objects.create_user(name, name + '@example.com', 'x') for name in ('alice', 'bob', 'carol')]
        cls.commandants = {}
        with server_schema('S'):
            for user in cls.users:
                commandant = Commandant.objects.create(user=user, commandant_name=user.username, civilisation_name=user.username, creation_date=timezone.now())
                cls.commandants[user.username] = commandant.id
                CommandantAccount.objects.get_or_create(server_id='S', commandant_id=commandant.id, user=user, defaults={'commandant_name': user.username})
        cycles.create_cycle_entry('S')

    def action(self, user, minutes_ago=60, method='GET', status=200, ip='1.1.1.1', fingerprint='a', path='/colonies/', seconds_ago=0):
        ActionLog.objects.create(date=self.now - timedelta(minutes=minutes_ago, seconds=seconds_ago), server_id='S', user=user,
                                 commandant_id=self.commandants[user.username], method=method, path=path, status=status, ip=ip, fingerprint=fingerprint)

    def alert(self, rule):
        return Alert.objects.filter(server='S', rule=rule)

    def run_rule(self, rule, days=7):
        rule('S', self.now - timedelta(days=days))


class AnticheatJournalTests(AnticheatTestCase):

    def play(self, user):
        UserExtended.objects.update_or_create(user=user, defaults={'playing_on_server_id': 'S', 'playing_on_commandant': self.commandants[user.username], 'language': 'fr'})
        self.client.force_login(user)

    def test_an_action_is_logged_without_its_free_texts(self):
        alice = self.users[0]
        self.play(alice)
        self.client.post('/conversations/', {'action': 'new', 'recipient': 'bob', 'subject': 'Secret', 'body': 'Un message prive', 'forum_id': '12'},
                         HTTP_USER_AGENT='Firefox', REMOTE_ADDR='9.9.9.9')
        log = ActionLog.objects.get(user=alice, method='POST')
        self.assertEqual((log.server_id, log.commandant_id, str(log.ip), log.path), ('S', self.commandants['alice'], '9.9.9.9', '/conversations/'))
        self.assertEqual(log.params, {'action': 'new', 'recipient': '...', 'subject': '...', 'body': '...', 'forum_id': '12'})
        self.assertEqual(len(log.fingerprint), 16)

    def test_the_api_routes_are_logged_with_their_refusal(self):
        alice = self.users[0]
        self.play(alice)
        response = self.client.post('/api_delete_district/', {'colony_id': '999'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ActionLog.objects.get(user=alice, path='/api_delete_district/').status, 400)

    def test_an_admin_controlling_an_account_is_not_logged(self):
        alice = self.users[0]
        self.play(alice)
        request = RequestFactory().get('/colonies/')
        request.user = alice
        request.user.is_hijacked = True
        log_player_action(lambda request: MagicMock(status_code=200))(request)
        self.assertFalse(ActionLog.objects.exists())

    def test_a_failing_journal_doesnt_lose_the_action(self):
        self.play(self.users[0])
        with patch('data.admin.ActionLog.objects.create', side_effect=DatabaseError):
            self.assertEqual(self.client.get('/colonies/').status_code, 200)

    def test_an_order_on_a_finished_server_raises_an_alert(self):
        self.play(self.users[0])
        Server.objects.filter(pk='S').update(status='stop')
        self.client.post('/api_delete_district/', {'colony_id': '1'})
        self.client.post('/api_delete_district/', {'colony_id': '1'})
        alert = self.alert('cheat_log').get()
        self.assertEqual(alert.nb_seen, 2)
        self.assertIn('consultation', alert.message)

    def test_asking_for_the_commandant_of_another_raises_an_alert(self):
        self.play(self.users[0])
        self.client.get('/commandant_login/', {'server': 'S', 'commandant_id': self.commandants['bob']})
        self.assertEqual(self.alert('cheat_log').count(), 1)
        self.client.get('/commandant_login/', {'server': 'Unknown', 'commandant_id': '1'})
        self.assertEqual(Alert.objects.count(), 1)

    def test_too_many_districts_raises_an_alert(self):
        with server_schema('S'):
            colony = Colony.objects.create(name='Home', owner_id=self.commandants['alice'], controller_id=self.commandants['alice'],
                                           coordinate='100100000005505001', colony_type='start')
            District.objects.create(colony=colony, district_type='farming', category='farming_district')
            DistrictType.objects.create(internal_name='farming', data={'internal_name': 'farming', 'category': 'farming_district', 'districts_slots': 0})
        recalculate_districts_slots('S', colony.id)
        self.assertEqual(self.alert('cheat_log').get().details['commandant'], self.commandants['alice'])

    def test_the_logins_are_logged(self):
        cache.clear()
        throttled_authenticate(RequestFactory().post('/player_login/', {'username': 'alice', 'password': 'wrong'}))
        throttled_authenticate(RequestFactory().post('/player_login/', {'username': 'alice', 'password': 'x'}))
        self.assertEqual(list(LoginLog.objects.order_by('date').values_list('username', 'success', 'user')),
                         [('alice', False, None), ('alice', True, self.users[0].id)])


class AnticheatRulesTests(AnticheatTestCase):

    def test_shared_ip_grows_with_the_proofs(self):
        alice, bob, carol = self.users
        self.action(alice)
        self.action(bob, fingerprint='other')
        self.action(carol, ip='2.2.2.2')
        self.run_rule(shared_ip)
        alert = self.alert('shared_ip').get()
        self.assertEqual((alert.subject, alert.severity), ('alice + bob', 'low'))

        self.action(bob)
        self.run_rule(shared_ip)
        alert = self.alert('shared_ip').get()
        self.assertEqual((alert.severity, alert.nb_seen), ('medium', 2))

        with server_schema('S'):
            entente = Entente.objects.create(name='E', owner_id=self.commandants['alice'], creation_date=timezone.now())
            for user in (alice, bob):
                EntenteMember.objects.create(entente=entente, commandant_id=self.commandants[user.username], status='member', datetime=timezone.now())
        self.run_rule(shared_ip)
        self.assertEqual(self.alert('shared_ip').get().severity, 'high')

    def test_shared_ip_also_reads_the_logins(self):
        alice, bob, carol = self.users
        self.action(alice)
        LoginLog.objects.create(date=self.now, user=bob, username='bob', success=True, ip='1.1.1.1', fingerprint='b')
        LoginLog.objects.create(date=self.now, user=carol, username='carol', success=False, ip='1.1.1.1', fingerprint='b')
        self.run_rule(shared_ip)
        self.assertEqual(self.alert('shared_ip').get().subject, 'alice + bob')

    def test_shared_ip_ignores_a_big_network_the_superusers_and_old_actions(self):
        alice, bob, _carol = self.users
        self.action(alice, minutes_ago=60 * 24 * 8)
        self.action(bob, minutes_ago=60 * 24 * 8)
        with patch('anticheat.rules.MAX_USERS_ON_SHARED_IP', 2):
            for user in self.users:
                self.action(user, ip='5.5.5.5')
            self.run_rule(shared_ip)
        self.assertFalse(self.alert('shared_ip').exists())

        User.objects.filter(pk=bob.pk).update(is_superuser=True)
        self.action(alice, ip='6.6.6.6')
        self.action(bob, ip='6.6.6.6')
        self.run_rule(shared_ip)
        self.assertFalse(self.alert('shared_ip').filter(subject__contains='bob').exists())

    def test_a_closed_alert_stays_closed(self):
        alice, bob, _carol = self.users
        self.action(alice)
        self.action(bob)
        self.run_rule(shared_ip)
        alert = self.alert('shared_ip').get()
        set_alert_open(alert.id, False, 'admin')
        self.run_rule(shared_ip)
        alert.refresh_from_db()
        self.assertEqual((alert.is_open, alert.nb_seen, alert.handled_by), (False, 2, 'admin'))

    def test_alternating_accounts(self):
        alice, bob, carol = self.users
        for session in range(6):  # self.now is at the start of a bucket of 10 minutes : each of these actions fills one
            start = session * 120
            for minutes_ago, user in ((30, alice), (20, alice), (10, bob), (0, bob), (20, carol), (0, carol)):
                self.action(user, minutes_ago=start + minutes_ago)
        self.run_rule(alternating_accounts)
        alert = self.alert('alternating_accounts').get()  # carol plays at the same time as both
        self.assertEqual((alert.subject, alert.details['handovers']), ('alice + bob', 6))

    def test_regular_actions_are_a_bot_and_a_human_is_not(self):
        alice, bob, _carol = self.users
        for i in range(60):
            self.action(alice, minutes_ago=i * 5)
            self.action(bob, minutes_ago=i * i % 500, seconds_ago=i)
        self.run_rule(bots, days=3)
        self.assertEqual(self.alert('bot_regular').get().subject, 'alice')

    def test_fast_actions(self):
        for i in range(120):
            self.action(self.users[0], seconds_ago=i * 0.5)
        self.run_rule(bots, days=3)
        self.assertEqual(self.alert('bot_fast').get().subject, 'alice')

    def test_no_sleep(self):
        alice, bob, _carol = self.users
        for hour in range(0, 60, 3):
            self.action(alice, minutes_ago=hour * 60)
        for hour in list(range(0, 18, 3)) + list(range(30, 60, 3)):
            self.action(bob, minutes_ago=hour * 60)
        self.run_rule(bots, days=3)
        self.assertEqual(self.alert('no_sleep').get().subject, 'alice')

    def test_orders_without_any_page_are_direct_calls(self):
        alice, bob, _carol = self.users
        for i in range(25):
            self.action(alice, minutes_ago=i * 7, method='POST', seconds_ago=i)
            self.action(bob, minutes_ago=i * 7, method='POST', seconds_ago=i)
            self.action(bob, minutes_ago=i * 7, seconds_ago=i + 5)
        self.run_rule(bots, days=3)
        self.assertEqual(self.alert('blind_posts').get().subject, 'alice')

    def test_a_small_activity_raises_nothing(self):
        for i in range(5):
            self.action(self.users[0], minutes_ago=i, method='POST')
        self.run_rule(bots, days=3)
        self.assertFalse(Alert.objects.exists())

    def test_refused_actions(self):
        alice, bob, _carol = self.users
        for _ in range(20):
            self.action(alice, status=400, path='/api_delete_district/')
            self.action(bob, status=200, path='/api_delete_district/')
        for _ in range(19):
            self.action(bob, status=403, path='/api_build_district/')
        self.run_rule(refused_actions, days=1)
        self.assertEqual(self.alert('refused_actions').get().subject, 'alice : /api_delete_district/')


class AnticheatScanTests(AnticheatTestCase):

    def at(self, hour, day=10):
        # In Paris, UTC+2 in July
        return datetime(2026, 7, day, hour, 5, tzinfo=dt_timezone(timedelta(hours=2)))

    def test_only_at_the_local_hour_and_once_a_day(self):
        self.assertEqual(scan_due_servers(self.at(3)), [])
        self.assertEqual(scan_due_servers(self.at(4)), ['S'])
        self.assertEqual(scan_due_servers(self.at(4)), [])
        self.assertEqual(scan_due_servers(self.at(5)), [])
        self.assertEqual(scan_due_servers(self.at(4, day=11)), ['S'])
        self.assertEqual(Scan.objects.count(), 2)

    def test_the_hour_changed_by_hand_is_read_at_the_next_run(self):
        Server.objects.filter(pk='S').update(hour_anticheat_checks=6)
        self.assertEqual(scan_due_servers(self.at(4)), [])
        self.assertEqual(scan_due_servers(self.at(6)), ['S'])

    def test_a_later_hour_doesnt_scan_the_same_day_twice(self):
        self.assertEqual(scan_due_servers(self.at(4)), ['S'])
        Server.objects.filter(pk='S').update(hour_anticheat_checks=6)
        self.assertEqual(scan_due_servers(self.at(6)), [])
        self.assertEqual(scan_due_servers(self.at(6, day=11)), ['S'])

    def test_a_missed_day_leaves_no_hole(self):
        calls = []
        with patch('anticheat.rules.RULES', ((lambda server, since: calls.append(since), 1),)):
            scan_due_servers(self.at(4))
            scan_due_servers(self.at(4, day=14))
        self.assertEqual(calls[1], self.at(4))

    def test_the_finished_and_test_servers_are_not_scanned(self):
        for status in ('stop', 'dead', 'test'):
            Server.objects.filter(pk='S').update(status=status)
            self.assertEqual(scan_due_servers(self.at(4)), [])

    def test_a_broken_rule_doesnt_stop_the_others(self):
        calls = []

        def broken(server, since):
            raise ValueError('Oops')

        with patch('anticheat.rules.RULES', ((broken, 1), (lambda server, since: calls.append(server), 1))):
            scan_due_servers(self.at(4))
        self.assertEqual(calls, ['S'])
        scan = Scan.objects.get()
        self.assertIn('Oops', scan.errors)
        self.assertIsNotNone(scan.finished_at)

    def test_every_rule_runs_on_a_real_journal(self):
        self.action(self.users[0])
        self.action(self.users[1])
        scan_due_servers(self.at(4))
        self.assertEqual(Scan.objects.get().errors, '')
        self.assertTrue(self.alert('shared_ip').exists())

    def test_the_journal_is_purged(self):
        alice = self.users[0]
        self.action(alice, minutes_ago=60 * 24 * 91)
        self.action(alice, minutes_ago=60 * 24 * 89)
        LoginLog.objects.create(date=self.now - timedelta(days=91), username='alice', success=False, fingerprint='a')
        purge_old_logs(self.now)
        self.assertEqual(ActionLog.objects.count(), 1)
        self.assertFalse(LoginLog.objects.exists())

    def test_the_tables_are_in_their_schema(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'TSS_anticheat'")
            self.assertEqual({row[0] for row in cursor.fetchall()}, {'action_log', 'login_log', 'alert', 'scan'})

    def test_the_command_runs_at_any_hour(self):
        call_command('run_schedule', stdout=MagicMock())

    def test_no_anticheat_without_its_hour(self):
        Server.objects.filter(pk='S').update(hour_anticheat_checks=None)
        self.assertEqual(scan_due_servers(self.at(4)), [])


class AnticheatAdminTests(AnticheatTestCase):

    def test_the_page_is_for_the_superusers(self):
        self.client.force_login(self.users[0])
        self.assertEqual(self.client.get('/admin_cheat_alerts/').status_code, 302)

    def test_the_page_tells_a_missing_scan_and_handles_the_alerts(self):
        self.client.force_login(User.objects.create_user('admin', 'a@example.com', 'x', is_staff=True, is_superuser=True))
        raise_alert('S', 'shared_ip', 'alice + bob', 'high', '<b>Message</b>')

        response = self.client.get('/admin_cheat_alerts/')
        self.assertContains(response, '&lt;b&gt;Message&lt;/b&gt;')
        self.assertContains(response, 'En retard')
        self.assertContains(response, '4 h (Europe/Paris)')

        alert = Alert.objects.get()
        self.client.post('/admin_cheat_alerts/', {'alert_id': alert.id, 'action': 'close'})
        alert.refresh_from_db()
        self.assertEqual((alert.is_open, alert.handled_by), (False, 'admin'))
        self.assertContains(self.client.get('/admin_cheat_alerts/'), 'Rouvrir')

        self.client.post('/admin_cheat_alerts/', {'alert_id': alert.id, 'action': 'reopen'})
        alert.refresh_from_db()
        self.assertTrue(alert.is_open)
        self.assertEqual(self.client.post('/admin_cheat_alerts/', {'alert_id': 'invented'}).status_code, 302)

        Scan.objects.create(server_id='S', local_date=timezone.now().date(), started_at=timezone.now())
        self.assertNotContains(self.client.get('/admin_cheat_alerts/'), 'En retard')


class ScheduleTests(TestCase):
    # Far in the future : the cycles created during the test start at the real now, long before

    paris = tz.gettz('Europe/Paris')

    @classmethod
    def setUpTestData(cls):
        make_server('S')
        Server.objects.filter(pk='S').update(opening_date=datetime(2100, 1, 1, tzinfo=dt_timezone.utc))
        cycles.create_cycle_entry('S')

    def at(self, hour, minute=5, day=10):
        return datetime(2100, 7, day, hour, minute, tzinfo=self.paris)

    def cycle_nb(self):
        return cycles.get_current_cycle('S')['cycle_nb']

    def test_the_cycle_passes_at_its_hour_once(self):
        self.assertEqual(run_due_steps(self.at(21, 55)), [])
        self.assertEqual(run_due_steps(self.at(22, 5)), ['S : end_cycle'])
        self.assertEqual(run_due_steps(self.at(22, 10)), [])
        self.assertEqual(self.cycle_nb(), 2)
        self.assertEqual(ScheduledRun.objects.get().status, 'done')

    def test_a_missed_hour_is_never_caught_up(self):
        self.assertEqual(run_due_steps(self.at(22, 16)), [])
        self.assertEqual(run_due_steps(self.at(9, day=12)), [])
        self.assertEqual(self.cycle_nb(), 1)
        self.assertEqual(run_due_steps(self.at(22, day=12)), ['S : end_cycle'])

    def test_a_failure_blocks_the_server_until_an_admin_unblocks_it(self):
        with patch('data.schedule.cycles.end_cycle', side_effect=DatabaseError('Disk full')):
            self.assertEqual(run_due_steps(self.at(22)), [])
        run = ScheduledRun.objects.get()
        self.assertEqual((run.status, run.note), ('failed', 'DatabaseError : Disk full'))

        self.assertEqual(run_due_steps(self.at(22, day=11)), [])
        unblock('S', 'admin')
        self.assertEqual(run_due_steps(self.at(22, 20, day=11)), [])  # The blocking step isn't played again, nor the missed one
        self.assertEqual(run_due_steps(self.at(22, day=12)), ['S : end_cycle'])
        self.assertEqual(self.cycle_nb(), 2)
        self.assertEqual(ScheduledRun.objects.get(due=self.at(22, 0)).handled_by, 'admin')

    def test_a_step_never_finished_blocks_the_server(self):
        ScheduledRun.objects.create(server_id='S', step='end_cycle', due=self.at(22, 0, day=9), started_at=self.at(22, 0, day=9), status='running')
        self.assertEqual(run_due_steps(self.at(22)), [])

    def test_the_first_cycle_can_be_delayed(self):
        Server.objects.filter(pk='S').update(opening_date=self.at(21, 0), delay_first_cycle=True)
        self.assertEqual(run_due_steps(self.at(22)), [])
        self.assertEqual(run_due_steps(self.at(22, day=11)), ['S : end_cycle'])

    def test_no_cycle_before_the_opening(self):
        Server.objects.filter(pk='S').update(opening_date=self.at(22, 3))
        self.assertEqual(run_due_steps(self.at(22, 6)), [])
        Server.objects.filter(pk='S').update(opening_date=self.at(21, 0))
        self.assertEqual(run_due_steps(self.at(22, 7)), ['S : end_cycle'])

    def test_the_hour_changed_by_hand_is_read_at_the_next_run(self):
        Server.objects.filter(pk='S').update(hour_cycle=23)
        self.assertEqual(run_due_steps(self.at(22)), [])
        self.assertEqual(run_due_steps(self.at(23)), ['S : end_cycle'])

    def test_nothing_automatic_without_hour_on_a_skirmish_or_a_finished_server(self):
        for change in ({'hour_cycle': None}, {'gameplay': 'skirmish'}, {'status': 'stop'}, {'status': 'dead'}):
            with transaction.atomic():
                Server.objects.filter(pk='S').update(**change)
                self.assertEqual(run_due_steps(self.at(22)), [], change)
                transaction.set_rollback(True)

    def test_a_cycle_passed_by_hand_just_before_isnt_followed_by_another(self):
        with server_schema('S'):
            Cycle.objects.update(datetime_start=self.at(21))
        self.assertEqual(run_due_steps(self.at(22)), ['S : end_cycle (skipped)'])
        self.assertEqual(self.cycle_nb(), 1)
        self.assertIsNone(blocking_run('S'))

    def test_the_summer_time_changes(self):
        # 2:00 is seen twice on 2026-10-25 and never on 2026-03-29
        first, second = (datetime(2026, 10, 25, utc_hour, 5, tzinfo=dt_timezone.utc) for utc_hour in (0, 1))
        self.assertEqual(last_due(2, self.paris, first), last_due(2, self.paris, second))
        self.assertEqual(last_due(2, self.paris, first).astimezone(dt_timezone.utc).hour, 0)
        due = last_due(2, self.paris, datetime(2026, 3, 29, 1, 5, tzinfo=dt_timezone.utc))
        self.assertEqual(due.astimezone(dt_timezone.utc), datetime(2026, 3, 29, 1, 0, tzinfo=dt_timezone.utc))

    def test_the_opening_date_is_the_opening_to_the_players(self):
        admin = User.objects.create_user('admin', 'a@example.com', 'x', is_staff=True, is_superuser=True)
        self.client.force_login(admin)
        for status, opening_changed in (('close', False), ('open', False), ('test', False), ('open', True)):
            before = Server.objects.get(pk='S').opening_date
            self.client.post('/admin_servers_states_edit/', {'server_name': 'S', 'type': 'status', 'value': status})
            self.assertEqual(Server.objects.get(pk='S').opening_date != before, opening_changed, status)

    def test_the_admins_see_and_unblock_a_blocked_server(self):
        ScheduledRun.objects.create(server_id='S', step='end_cycle', due=self.at(22, 0), started_at=self.at(22, 0), status='failed', note='Disk full')
        self.client.force_login(User.objects.create_user('staff', 's@example.com', 'x', is_staff=True))
        self.client.post('/admin_unblock_schedule/', {'server_name': 'S'})
        self.assertIsNotNone(blocking_run('S'))

        self.client.force_login(User.objects.create_user('admin', 'a@example.com', 'x', is_staff=True, is_superuser=True))
        self.assertContains(self.client.get('/admin_servers_states/'), 'Serveur bloqué')
        self.client.post('/admin_unblock_schedule/', {'server_name': 'S'})
        self.assertIsNone(blocking_run('S'))
        self.assertContains(self.client.get('/admin_servers_states/'), 'Disk full')


class MapTrialTests(TestCase):

    def setUp(self):
        self.client.force_login(User.objects.create_user('admin', 'a@example.com', 'x', is_staff=True, is_superuser=True))

    def test_only_a_superuser_tries_maps(self):
        self.client.logout()
        self.assertRedirects(self.client.get('/admin_map_trial/'), '/admin_login/?next=/admin_map_trial/', fetch_redirect_response=False)

    def test_a_wrong_number_is_refused_without_generating(self):
        with patch('geography.galaxy.generate') as generate:
            response = self.client.post('/admin_map_trial/', {'players': '1', 'gameplay': 'saga', 'area_per_player': 'beaucoup'})
        self.assertContains(response, 'Joueurs max : un nombre entier de 2 à 300')
        self.assertContains(response, 'Surface par joueur : un nombre entier')
        generate.assert_not_called()

    def test_a_map_is_made_from_its_seed_and_nothing_is_saved(self):
        self.assertContains(self.client.get('/admin_map_trial/'), 'Générer')  # The first request creates the profile of the admin
        with CaptureQueriesContext(connection) as queries:
            response = self.client.post('/admin_map_trial/', {'players': '6', 'gameplay': 'skirmish', 'seed': 'essai'})
        self.assertContains(response, 'Graine essai')
        self.assertContains(response, 'data:image/png;base64,', count=6)  # Three pictures, each shown and downloadable
        self.assertFalse([q['sql'] for q in queries.captured_queries if q['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))])


class MapGenerationTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        make_server('S')
        with server_schema('S'):
            StartingValues.objects.create(start_type='default_land_colony')
        cls.drawn = geography_map.generate_map('S', 'TSS_boardgame.xlsx')

    def test_the_map_is_written_in_the_tables_of_the_game(self):
        with server_schema('S'):
            systems, bodies = System.objects.count(), Coordinate.objects.count()
            self.assertEqual(systems, len(set(map(tuple, zip(self.drawn.ys.tolist(), self.drawn.xs.tolist())))))
            self.assertEqual(Sector.objects.aggregate(total=Sum('nb_systems'))['total'], systems)
            self.assertGreater(bodies, systems)  # A star and its planets
            self.assertFalse(System.objects.exclude(seed__regex=r'^1001\d{12}$').exists())  # The seed 1001 of the Excel
            self.assertFalse(Coordinate.objects.exclude(seed__regex=r'^1001\d{14}$').exists())
            self.assertFalse(System.objects.filter(zone=None).exists())
            self.assertFalse(System.objects.filter(region=None).exists())

    def test_the_zones_are_written_with_their_shape_their_neighbours_and_a_name(self):
        with server_schema('S'):
            zones = {zone.region: zone for zone in Zone.objects.all()}
            self.assertEqual(set(System.objects.values_list('region', flat=True)) - set(zones), set())  # Each system in a zone of the map
            for region, nb_systems in Counter(System.objects.values_list('region', flat=True)).items():
                self.assertEqual(zones[region].nb_systems, nb_systems)
            self.assertEqual(len({zone.name for zone in zones.values()}), len(zones))
            cells = set()
            for zone in zones.values():
                self.assertTrue(zone.shape)
                self.assertEqual(zone.name.split(' ')[0], galaxy.ZONES[zone.kind]['label'].split(' ')[0])
                for neighbour in zone.neighbours:
                    self.assertIn(zone.region, zones[neighbour].neighbours)
                for row, start, length in zone.shape:
                    covered = {(row, column) for column in range(start, start + length)}
                    self.assertFalse(cells & covered)  # A cell belongs to a single zone
                    cells |= covered

    def test_every_system_has_its_own_name_and_its_bodies_its_name_and_orbit(self):
        with server_schema('S'):
            stars = Coordinate.objects.filter(type='star')
            self.assertEqual(stars.values('name').distinct().count(), stars.count())
            star = stars.first()
            for body in Coordinate.objects.filter(system_id=star.system_id).exclude(type='star'):
                self.assertEqual(body.name, f'{star.name} {ROMAN[body.sys_coordinate]}')

    def test_every_home_is_a_free_native_planet_around_a_star_of_the_excel(self):
        with server_schema('S'):
            natives = StartingValues.objects.get().available_native_planets
            self.assertEqual(len(natives), 10)  # No row max_players in TSS_boardgame.xlsx : the 10 players of a skirmish
            planets = Coordinate.objects.filter(seed__in=[str(seed) for seed in natives])
            self.assertEqual(set(planets.values_list('subtype', flat=True)), {'native'})
            for planet in planets:
                star = Coordinate.objects.get(seed=planet.system_id + '00')
                self.assertEqual(star.type, 'star')
                self.assertIn(star.subtype, ('F', 'G', 'K'))
                self.assertEqual(System.objects.get(seed=planet.system_id).zone, 'berceau')

    def test_a_habitable_world_has_its_planet_and_a_star_of_its_type(self):
        type_stars = geography_map.type_stars('TSS_boardgame.xlsx')
        with server_schema('S'):
            for system in System.objects.filter(system_type__startswith='habitable'):
                self.assertIn(f'telluric {system.system_type}', system.system_coordinates.values())
                self.assertIn(Coordinate.objects.get(seed=system.seed + '00').subtype,
                              list(type_stars[system.system_type]) + ['G'])  # G : the only star allowed on the bank of a rift


class LocationsTests(SimpleTestCase):

    def test_a_seed_and_its_readable_place_convert_both_ways(self):
        for seed, place in (('1001003005', 'F4'), ('1001003005012055', 'F4-55.12'), ('100100300501205503', 'F4-55.12-3'),
                            ('1001000026000000', 'AA1-00.00'), ('1001041701099000', 'ZZ42-00.99')):
            self.assertEqual(locations.readable(seed), place)
            self.assertEqual(locations.seed_of(place, '1001999999'), seed)
            self.assertEqual(locations.seed_of(place.lower(), '1001'), seed)
        self.assertEqual(locations.seed_of(' 100100300501205503 ', '1002'), '100100300501205503')  # A seed stays itself

    def test_anything_else_is_not_a_place(self):
        for text in ('', 'F0', 'F4-123.5', 'F4-5.5-100', '12345', '1001:01', 'ABCD4'):
            self.assertIsNone(locations.seed_of(text, '1001'), text)
        self.assertEqual(locations.readable('1001003005:01'), '1001003005:01')


class HomeAllocationTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        make_server('S')
        with server_schema('S'):
            # Region 1 : homes at X 0, 10 and 30 of the sector 1001000000, the one at 0 taken ; region 2 : two free homes
            for x, region in ((0, 1), (10, 1), (30, 1), (60, 2), (80, 2)):
                System.objects.create(seed=f'1001000000050{x:03}', system_type='native', region=region, sector_id='1001000000',
                                      pos_y='050', pos_x=f'{x:03}')
        cls.free = [int(f'1001000000050{x:03}01') for x in (10, 30, 60, 80)]

    def test_the_most_settled_cradle_first_and_the_farthest_home_in_it(self):
        with server_schema('S'):
            self.assertEqual(pick_home(self.free), int('100100000005003001'))

    def test_an_empty_cradle_opens_when_the_others_are_full(self):
        with server_schema('S'):
            self.assertIn(pick_home(self.free[2:]), self.free[2:])
            self.assertIn(pick_home([123]), [123])  # A planet the map doesn't know : as before, at random
