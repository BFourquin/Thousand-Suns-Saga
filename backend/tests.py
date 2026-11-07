import inspect
import json
import random
from datetime import datetime, timedelta, timezone as dt_timezone
from importlib import import_module
from unittest.mock import MagicMock, patch

from django.apps import apps
from django.contrib.auth.models import AnonymousUser, User
from django.core.cache import cache
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import Client, RequestFactory, SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import Resolver404, resolve
from django.utils import timezone

from backend import views_game
from backend.decorators import commandant_required
from backend.login import LOGIN_MAX_FAILURES_PER_ACCOUNT, throttled_authenticate
from backend.models import CommandantAccount, Server, UserExtended, to_id
from backend.templatetags.tss_dates import rp_date
from backend.templatetags.tss_text import MAX_DEPTH, bbcode
from database.schemas import schema_of, server_schema
from game.models import Building, BuildingType, Colony, Commandant, ConversationMessage, Coordinate, District, DistrictType, Entente, EntenteMember, EntenteRole, Modifier, Post, Report, Resource, Sector, StartingValues, System, Technology
from backend.utils import commandant_owns_colony
from data import conversations, ententes, forums, quadrants
from data import server_details
from data import cycles
from data.buildings import construct_building
from data.buildings_types import is_buildable
from data.commandant import civilisation_name_taken, commandant_name_taken, create_commandant, delete_commandant, get_commandant
from data.coordinates import get_coordinate_image
from data.districts import create_district, delete_district
from data.economy import cycle_balance
from data.errors import GameError
from data.modifiers import add_modifier
from data.user import get_user_by_name
from data.report import change_report_status, delete_report, get_commandant_reports, get_report, mark_all_reports_as_read, update_nb_unread_reports
from data.resources import add_resources, pay_resources

API_LOGGED_URLS = ['/api_create_commandant/', '/api_build_district/', '/api_build_building/', '/api_delete_district/',
                   '/api_district_set_activation_percent/', '/api_start_research/']


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

    def test_a_quadrant_is_found_by_its_id_or_by_a_seed(self):
        self.assertEqual(quadrants.quadrant_id('1001000000:11'), '1001000000:11')
        self.assertEqual(quadrants.quadrant_id('1001000000055050'), '1001000000:11')
        self.assertEqual(quadrants.quadrant_id('100100000005505001'), '1001000000:11')
        for wrong in ('', 'x', '1001000000', '1001000000:2', '1001000000:22', '1001000000150050', "1' OR 1=1"):
            self.assertIsNone(quadrants.quadrant_id(wrong), wrong)

    def test_a_sector_is_found_by_its_seed_a_quadrant_or_a_lower_seed(self):
        for text in ('1001000000', '1001000000:11', '1001000000055050', '100100000005505001'):
            self.assertEqual(quadrants.sector_id_of(text), '1001000000')
        for wrong in ('', 'x', '100100000', '10010000001', '1001000000:1', "1' OR 1=1"):
            self.assertIsNone(quadrants.sector_id_of(wrong), wrong)

    def test_neighbours_cross_the_borders_of_the_sectors(self):
        self.assertEqual(quadrants.neighbour_quadrant('1001000000:00', 0, 1), '1001000000:01')
        self.assertEqual(quadrants.neighbour_quadrant('1001000000:01', 0, 1), '1001000001:00')
        self.assertEqual(quadrants.neighbour_quadrant('1001000000:11', 1, 0), '1001001000:01')
        self.assertIsNone(quadrants.neighbour_quadrant('1001000000:00', -1, 0))
        self.assertIsNone(quadrants.neighbour_quadrant('1001000000:00', 0, -1))

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

    def test_vortex_networks_are_trees_and_continue_on_both_sides_of_a_border(self):
        rng = random.Random(1)
        sectors = {sector: [(rng.randint(0, 99), rng.randint(0, 99)) for _ in range(800)] for sector in ('1001000000', '1001000001', '1001001000')}
        vortex = quadrants.vortex_of_quadrant('1001000000:11', sectors)

        self.assertEqual(vortex, quadrants.vortex_of_quadrant('1001000000:11', sectors))
        self.assertGreater(len(vortex['nodes']), 10)
        for network in set(vortex['nodes'].values()):
            nodes = [node for node, of_network in vortex['nodes'].items() if of_network == network]
            links = [link for link in vortex['links'] if link['network'] == network]
            self.assertEqual(len(links), len(nodes) - 1)

        self.assertEqual({exit_['direction'] for exit_ in vortex['exits']}, {'north', 'south', 'west', 'east'})
        for exit_ in vortex['exits']:
            back = quadrants.vortex_of_quadrant(exit_['quadrant'], sectors)['exits']
            self.assertIn((exit_['to'], exit_['from'], '1001000000:11', exit_['network']),
                          [(other['from'], other['to'], other['quadrant'], other['network']) for other in back])


class QuadrantMapFixture(EconomyTestCase):

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
            Sector.objects.create(seed='1001000000', pos_y=0, pos_x=0, sector_type='native', systems_coordinates=[[55, 50], [60, 70], [10, 10]])
            for seed, kind in (('1001000000055050', 'native'), ('1001000000060070', 'standard'), ('1001000000010010', 'standard')):
                System.objects.create(seed=seed, system_type=kind, sector_id=seed[:10], pos_y=seed[10:13], pos_x=seed[13:16])
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


class QuadrantMapTests(QuadrantMapFixture):

    def map_of(self, **params):
        response = self.client.get('/geography_quadrant/', params)
        self.assertEqual(response.status_code, 200)
        return response

    def test_only_the_systems_of_the_quadrant_are_on_the_map(self):
        quadrant = self.map_of(quadrant='1001000000:11').context['quadrant_map']
        self.assertEqual({system['id'] for system in quadrant['systems']}, {'1001000000055050', '1001000000060070'})
        self.assertEqual(quadrant['origin'], {'y': 50, 'x': 50})

    def test_the_native_quadrant_is_the_default_and_a_wrong_one_is_reported(self):
        response = self.map_of()
        self.assertEqual(response.context['quadrant_map']['id'], '1001000000:11')
        self.assertFalse(response.context['quadrant_not_found'])
        for params in ({'quadrant': 'nope'}, {'quadrant': '1001999999:00'}, {'system_id': '12'}):
            response = self.map_of(**params)
            self.assertEqual(response.context['quadrant_map']['id'], '1001000000:11')
            self.assertTrue(response.context['quadrant_not_found'])

    def test_a_system_opens_its_quadrant(self):
        self.assertEqual(self.map_of(system_id='1001000000010010').context['quadrant_map']['id'], '1001000000:00')

    def test_what_is_known_of_the_others_stays_public(self):
        response = self.map_of(quadrant='1001000000:11')
        quadrant = response.context['quadrant_map']
        rival = next(empire for empire in quadrant['empires'] if empire['id'] == self.rival.id)
        self.assertEqual(rival['civilisation'], 'Rivals')
        self.assertEqual(set(rival), {'id', 'commandant', 'civilisation', 'is_mine', 'ententes'})
        colony = next(system for system in quadrant['systems'] if system['id'] == '1001000000060070')['colonies'][0]
        self.assertEqual((colony['name'], colony['is_mine'], colony['id']), ('Outpost', False, None))  # No link to the page of a colony of another player
        self.assertEqual([entente['name'] for entente in quadrant['ententes']], ['Pact'])

    def test_an_application_isnt_a_membership(self):
        memberships = ententes.memberships_of_commandants('S', [self.commandant.id, self.rival.id])
        self.assertNotIn(self.commandant.id, memberships)
        self.assertEqual(memberships[self.rival.id][0]['name'], 'Pact')

    def test_my_colony_links_to_its_page(self):
        quadrant = self.map_of(quadrant='1001000000:11').context['quadrant_map']
        colony = next(system for system in quadrant['systems'] if system['id'] == '1001000000055050')
        self.assertEqual(colony['colonies'][0]['id'], self.colony.id)

    def test_only_the_resources_of_the_server_are_offered(self):
        known = {resource['id'] for resource in self.map_of(quadrant='1001000000:11').context['quadrant_map']['resources']}
        self.assertLessEqual(known, {'common_metal', 'tungsten'})

    def test_a_player_name_cant_break_out_of_the_page(self):
        with server_schema('S'):
            Commandant.objects.filter(id=self.rival.id).update(civilisation_name='</script><script>alert(1)</script>')
        self.assertNotContains(self.map_of(quadrant='1001000000:11'), '<script>alert(1)')


class SectorMapTests(QuadrantMapFixture):

    def sector_of(self, **params):
        response = self.client.get('/geography_sector/', params)
        self.assertEqual(response.status_code, 200)
        return response

    def deposits(self, resource, sector='1001000000'):
        response = self.client.get('/api_sector_deposits/', {'sector': sector, 'resource': resource})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_all_the_systems_of_the_sector_are_on_the_map_in_aligned_columns(self):
        sector = self.sector_of().context['sector_map']
        systems = sector['systems']
        self.assertEqual(systems['name'], ['Star010', 'Star050', 'Star070'])
        self.assertEqual((systems['y'], systems['x']), ([10, 55, 60], [10, 50, 70]))
        self.assertEqual(sector['types'][systems['type'][1]]['key'], 'native')
        self.assertEqual(sector['stars'][systems['star'][0]]['key'], 'supergiant')

    def test_a_system_or_a_quadrant_opens_its_sector_and_a_wrong_one_is_reported(self):
        self.assertFalse(self.sector_of(system_id='1001000000010010').context['sector_not_found'])
        self.assertFalse(self.sector_of(sector='1001000000:11').context['sector_not_found'])
        for params in ({'sector': 'nope'}, {'sector': '1001999999'}):
            response = self.sector_of(**params)
            self.assertTrue(response.context['sector_not_found'])
            self.assertEqual(response.context['sector_map']['id'], '1001000000')

    def test_the_colonies_stay_as_public_as_on_a_quadrant(self):
        sector = self.sector_of().context['sector_map']
        mine, other = sector['colonies'][1][0], sector['colonies'][2][0]
        self.assertEqual((mine['id'], mine['is_mine']), (self.colony.id, True))
        self.assertEqual((other['name'], other['id'], other['is_mine']), ('Outpost', None, False))
        self.assertEqual([entente['name'] for entente in sector['ententes']], ['Pact'])

    def test_each_vortex_refers_to_a_system_of_the_map(self):
        with server_schema('S'):
            Sector.objects.filter(seed='1001000000').update(systems_coordinates=[[10, 10], [55, 50], [60, 70]])
        sector = self.sector_of().context['sector_map']
        for ranks in list(sector['vortex']['nodes'].values()) + list(sector['vortex']['links'].values()):
            self.assertTrue(all(0 <= rank < 3 for rank in ranks))

    def test_the_vortex_of_two_quadrants_of_a_sector_are_linked_once(self):
        rng = random.Random(2)
        positions = sorted({(rng.randint(0, 99), rng.randint(0, 99)) for _ in range(800)})
        with server_schema('S'):
            Sector.objects.filter(seed='1001000000').update(systems_coordinates=positions)
            ranks = {f'1001000000{y:03}{x:03}': rank for rank, (y, x) in enumerate(positions)}
            vortex = quadrants._vortex_of_sector('1001000000', {}, ranks)
        nodes = sum(len(of_network) for of_network in vortex['nodes'].values())
        self.assertEqual(nodes, sum(round(len([1 for y, x in positions if y // 50 == qy and x // 50 == qx]) * quadrants.VORTEX_SHARE)
                                    for qy in range(2) for qx in range(2)))
        self.assertEqual(vortex['exits'], [])  # No neighbouring sector
        for network, links in vortex['links'].items():
            pairs = [frozenset(links[i:i + 2]) for i in range(0, len(links), 2)]
            self.assertEqual(len(pairs), len(set(pairs)), network)
            # A tree in each quadrant, and at most a link across each of the 4 borders inside the sector
            self.assertGreaterEqual(len(pairs), len(vortex['nodes'][network]) - 4)

    def test_the_deposits_are_only_sent_when_asked_for_and_add_up_the_bodies(self):
        self.assertNotIn('deposits', self.sector_of().context['sector_map']['systems'])
        expected = {}
        for rank, seed in enumerate(('1001000000010010', '1001000000055050', '1001000000060070')):
            for resource, richness in quadrants.deposits_of_body(seed + '01', 'asteroid_belt', 'standard').items():
                expected.setdefault(resource, {})[rank] = richness
        self.assertTrue(expected)
        for resource, values in expected.items():
            deposits = self.deposits(resource)
            self.assertEqual(dict(zip(deposits['indexes'], deposits['values'])), values)

    def test_the_rare_deposits_add_up_all_the_rare_resources(self):
        seeds = ('1001000000010010', '1001000000055050', '1001000000060070')
        total = sum(richness for seed in seeds for resource, richness in quadrants.deposits_of_body(seed + '01', 'asteroid_belt', 'standard').items()
                    if resource in quadrants.RARE_RESOURCES)
        self.assertEqual(sum(self.deposits('__rare')['values']), total)

    def test_a_wrong_request_for_deposits_gives_nothing(self):
        empty = {'indexes': [], 'values': []}
        self.assertEqual(self.deposits('nothing'), empty)
        self.assertEqual(self.deposits('common_metal', sector='1001999999'), empty)
        self.assertEqual(self.deposits('common_metal', sector="1' OR 1=1"), empty)

    def test_the_deposits_need_a_session_and_a_get(self):
        self.assertEqual(self.client.post('/api_sector_deposits/').status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.get('/api_sector_deposits/').status_code, 401)

    def test_the_number_of_queries_doesnt_depend_on_the_number_of_systems(self):
        def queries():
            cache.clear()
            with CaptureQueriesContext(connection) as context:
                quadrants.sector_map('S', '1001000000', self.commandant.id, 'fr')
            return len(context)

        before = queries()
        with server_schema('S'):
            for x in range(20, 40):
                seed = f'1001000000020{x:03}'
                System.objects.create(seed=seed, system_type='standard', sector_id=seed[:10], pos_y=seed[10:13], pos_x=seed[13:16])
                Coordinate.objects.create(seed=seed + '00', type='star', subtype='G', sector_id=seed[:10], system_id=seed, sys_y=20, sys_x=x, sys_coordinate=0, name='N')
        self.assertEqual(queries(), before)

    def test_a_player_name_cant_break_out_of_the_page(self):
        with server_schema('S'):
            Commandant.objects.filter(id=self.rival.id).update(civilisation_name='</script><script>alert(1)</script>')
        self.assertNotContains(self.sector_of(), '<script>alert(1)')


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
        self.assertContains(response, 'value="well"')
        self.assertNotContains(response, 'value="too_new"')

    def test_resources_page_shows_the_forecast(self):
        self.build(self.central, 'well')
        response = self.client.get('/resources/')
        row = next(resource for resource in response.context['resources'] if resource['name'] == 'water')
        self.assertEqual((row['stock'], row['produced'], row['consumed'], row['balance'], row['self_sustainability']), (3, 4, 2, 2, 200))
        self.assertContains(response, '200 %')


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
