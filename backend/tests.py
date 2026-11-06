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
from data import conversations, forums, hrp_forum
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


class ForumsTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('player', 'p@example.com', 'x')
        cls.other_user = User.objects.create_user('other_player', 'o@example.com', 'x')
        cls.staff = User.objects.create_user('staff', 's@example.com', 'x', is_staff=True)
        make_server('S')
        make_server('Other')
        with server_schema('S'):
            cls.owner, cls.visitor = [
                Commandant.objects.create(user=user, commandant_name=name, civilisation_name=name, creation_date=timezone.now()).id
                for user, name in ((cls.user, 'Paullus'), (cls.other_user, 'Varro'))]
        cycles.create_cycle_entry('S')

    def play(self, user, commandant_id):
        UserExtended.objects.update_or_create(user=user, defaults={'playing_on_server_id': 'S', 'playing_on_commandant': commandant_id,
                                                                   'language': 'fr'})
        self.client.force_login(user)

    def private_forum(self):
        return forums.create_player_forum('S', self.owner, 'Le Repaire', '', True)

    # Forums of the server

    def test_each_server_has_its_assembly(self):
        self.assertNotEqual(forums.get_assembly_id('S'), None)
        self.assertEqual(forums.get_forum('S', forums.get_assembly_id('S'), self.owner)['can_post'], True)
        forums.create_topic('S', forums.get_assembly_id('S'), self.owner, 'Discours', 'Citoyens...')
        self.assertEqual(forums.get_topics('Other', forums.get_assembly_id('Other'), 1).paginator.count, 0)

    def test_private_forum_stays_closed_to_the_others(self):
        forum_id = self.private_forum()
        topic_id = forums.create_topic('S', forum_id, self.owner, 'Secret', 'Le plan')
        self.assertIsNone(forums.get_forum('S', forum_id, self.visitor))
        self.assertIsNone(forums.get_topic('S', topic_id, self.visitor))
        self.assertEqual(forums.get_player_forums('S', self.visitor)['others'], [])
        for refused in (lambda: forums.create_topic('S', forum_id, self.visitor, 'Hop', 'Hop'),
                        lambda: forums.reply_to_topic('S', topic_id, self.visitor, 'Hop'),
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
        self.assertEqual(forums.count_invitations('S', self.visitor), 1)
        self.assertIsNone(forums.get_forum('S', forum_id, self.visitor))  # Not before accepting

        forums.answer_invitation('S', forum_id, self.visitor, True)
        self.assertEqual(forums.count_invitations('S', self.visitor), 0)
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
        with self.assertRaises(GameError):
            forums.create_player_forum('S', self.visitor, 'LA CANTINE', '', False)
        other_id = forums.create_player_forum('S', self.visitor, 'Le Port', '', False)
        with self.assertRaises(GameError):
            forums.update_player_forum('S', other_id, self.visitor, 'la cantine', '', False)
        self.assertEqual(forums.get_forum('S', forum_id, self.owner)['name'], 'La Cantine')

    def test_deleting_the_last_post_removes_the_topic(self):
        assembly_id = forums.get_assembly_id('S')
        topic_id = forums.create_topic('S', assembly_id, self.owner, 'Discours', 'Un')
        forums.reply_to_topic('S', topic_id, self.visitor, 'Deux')
        first, second = forums.get_posts('S', topic_id, 1)
        with self.assertRaises(GameError):
            forums.delete_post('S', second['id'], self.visitor, False)  # Nobody moderates the assembly but the staff

        self.assertTrue(forums.delete_post('S', second['id'], self.visitor, True))
        topic_row = forums.get_topics('S', assembly_id, 1)[0]
        self.assertEqual((topic_row['nb_replies'], topic_row['last_author_name']), (0, 'Paullus'))
        self.assertFalse(forums.delete_post('S', first['id'], self.visitor, True))
        self.assertIsNone(forums.get_topic('S', topic_id, self.owner))

    def test_invalid_texts_are_refused(self):
        assembly_id = forums.get_assembly_id('S')
        for title, body in (('', 'Texte'), ('Titre', '   '), ('x' * 151, 'Texte'), ('Titre', 'x' * 20001), ('\x00', 'Texte')):
            with self.assertRaises(GameError), transaction.atomic():
                forums.create_topic('S', assembly_id, self.owner, title, body)
        self.assertEqual(forums.get_topics('S', assembly_id, 1).paginator.count, 0)

    # Private messages

    def test_conversation_is_reserved_to_its_members(self):
        conversation_id = conversations.start_conversation('S', self.owner, 'varro', 'Pacte', 'Alliance ?')
        self.assertEqual(conversations.count_unread_conversations('S', self.visitor), 1)
        self.assertEqual(conversations.count_unread_conversations('S', self.owner), 0)
        self.assertEqual(conversations.get_conversation('S', conversation_id, self.visitor)['correspondents'], 'Paullus')

        with server_schema('S'):
            third = Commandant.objects.create(user=self.user, commandant_name='Tiers', civilisation_name='Tiers', creation_date=timezone.now()).id
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
        self.assertEqual(conversations.get_messages('S', conversation_id, 1).paginator.count, 0)

    # HRP forum

    def test_only_the_staff_opens_announcements(self):
        with self.assertRaises(GameError):
            hrp_forum.create_topic('announcements', self.user.id, False, 'Mise à jour', 'Texte')
        with self.assertRaises(GameError):
            hrp_forum.create_topic('unknown', self.user.id, True, 'Mise à jour', 'Texte')
        topic_id = hrp_forum.create_topic('announcements', self.staff.id, True, 'Mise à jour', 'Texte')
        hrp_forum.reply_to_topic(topic_id, self.user.id, 'Merci !')
        self.assertEqual(hrp_forum.get_posts(topic_id, 1)[1]['author_name'], 'player')

    def test_only_the_staff_moderates_hrp(self):
        topic_id = hrp_forum.create_topic('misc', self.user.id, False, 'Salut', 'Texte')
        post_id = hrp_forum.get_posts(topic_id, 1)[0]['id']
        with self.assertRaises(GameError):
            hrp_forum.delete_post(post_id, False)
        with self.assertRaises(GameError):
            hrp_forum.delete_topic(topic_id, False)
        self.assertFalse(hrp_forum.delete_post(post_id, True))
        self.assertIsNone(hrp_forum.get_topic(topic_id))

    def test_hrp_thread_outlives_a_deleted_account(self):
        gone = User.objects.create_user('gone', 'g@example.com', 'x')
        topic_id = hrp_forum.create_topic('misc', gone.id, False, 'Salut', 'Texte')
        gone.delete()
        self.assertEqual(hrp_forum.get_posts(topic_id, 1)[0]['author_name'], 'Compte supprimé')

    # Pages

    def test_every_page_answers(self):
        self.play(self.user, self.owner)
        assembly_id = forums.get_assembly_id('S')
        topic_id = forums.create_topic('S', assembly_id, self.owner, 'Discours', 'Texte')
        forum_id = self.private_forum()
        conversation_id = conversations.start_conversation('S', self.owner, 'Varro', 'Pacte', 'Texte')
        hrp_topic_id = hrp_forum.create_topic('misc', self.user.id, False, 'Salut', 'Texte')

        for url in (f'/forum/?forum_id={assembly_id}', f'/forum/?forum_id={forum_id}', f'/topic/?topic_id={topic_id}',
                    '/player_forums/', f'/player_forum_manage/?forum_id={forum_id}', '/conversations/',
                    f'/conversation/?conversation_id={conversation_id}', '/hrp/', '/hrp_section/?section=misc',
                    f'/hrp_topic/?topic_id={hrp_topic_id}'):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertRedirects(self.client.get('/assembly/'), f'/forum/?forum_id={assembly_id}')

    def test_hrp_needs_an_account_but_no_commandant(self):
        self.assertEqual(self.client.get('/hrp/').status_code, 302)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get('/hrp/').status_code, 200)
        self.assertEqual(self.client.get('/hrp_section/?section=announcements').status_code, 200)
        self.assertRedirects(self.client.get('/assembly/'), '/user_account/', fetch_redirect_response=False)

    def test_forbidden_or_unknown_ids_send_back_to_a_list(self):
        forum_id = self.private_forum()
        self.play(self.other_user, self.visitor)
        for url, destination in ((f'/forum/?forum_id={forum_id}', '/player_forums/'),
                                 (f'/player_forum_manage/?forum_id={forum_id}', '/player_forums/'),
                                 (f'/player_forum_manage/?forum_id={forums.get_assembly_id("S")}', '/player_forums/'),
                                 ('/forum/?forum_id=abc', '/player_forums/'), ('/topic/?topic_id=abc', '/assembly/'),
                                 ('/conversation/?conversation_id=abc', '/conversations/'),
                                 ('/hrp_section/?section=abc', '/hrp/'), ('/hrp_topic/?topic_id=abc', '/hrp/')):
            self.assertRedirects(self.client.get(url), destination, fetch_redirect_response=False)

    def test_owner_manages_his_forum_from_its_page(self):
        forum_id = forums.create_player_forum('S', self.owner, 'La Cantine', '', False)
        url = f'/player_forum_manage/?forum_id={forum_id}'
        self.play(self.user, self.owner)

        self.client.post(url, {'action': 'save', 'name': 'Le Repaire', 'description': 'Texte', 'is_private': 'on'})
        forum = forums.get_forum('S', forum_id, self.owner)
        self.assertEqual((forum['name'], forum['description'], forum['is_private']), ('Le Repaire', 'Texte', True))

        self.client.post(url, {'action': 'invite', 'invited_name': 'Varro'})
        self.assertEqual(forums.count_invitations('S', self.visitor), 1)
        self.assertContains(self.client.post(url, {'action': 'invite', 'invited_name': 'Inconnu'}), 'Aucun commandant')

        self.client.post(url, {'action': 'remove', 'commandant_id': self.visitor})
        self.assertEqual(forums.count_invitations('S', self.visitor), 0)

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
        post_id = forums.get_posts('S', topic_id, 1)[1]['id']
        self.assertContains(self.client.post(url, {'delete_post': post_id}), 'Vous ne pouvez pas supprimer')

        self.play(self.user, self.owner)
        self.assertContains(self.client.get(url), 'name="delete_post"')
        self.assertRedirects(self.client.post(url, {'delete_post': post_id}), url)
        self.assertEqual(forums.get_posts('S', topic_id, 1).paginator.count, 1)
        self.assertRedirects(self.client.post(url, {'delete_topic': '1'}), f'/forum/?forum_id={forum_id}')
        self.assertIsNone(forums.get_topic('S', topic_id, self.owner))

    def test_refused_message_keeps_what_was_typed(self):
        self.play(self.user, self.owner)
        response = self.client.post('/conversations/', {'action': 'new', 'recipient': 'Inconnu', 'subject': 'Pacte', 'body': 'Long texte'})
        self.assertContains(response, 'Aucun commandant')
        self.assertContains(response, 'Long texte')

    def test_messages_are_escaped_and_their_links_clickable(self):
        self.play(self.user, self.owner)
        assembly_id = forums.get_assembly_id('S')
        self.client.post(f'/forum/?forum_id={assembly_id}', {'action': 'new_topic', 'title': '<b>Titre</b>',
                                                             'body': '<script>alert(1)</script>\nhttps://example.com'})
        response = self.client.get(f'/forum/?forum_id={assembly_id}')
        self.assertContains(response, '&lt;b&gt;Titre&lt;/b&gt;')
        topic_id = forums.get_topics('S', assembly_id, 1)[0]['id']
        response = self.client.get(f'/topic/?topic_id={topic_id}')
        self.assertNotContains(response, '<script>alert(1)')
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;<br>')
        self.assertContains(response, 'href="https://example.com"')

    def test_get_changes_nothing(self):
        forum_id = forums.create_player_forum('S', self.owner, 'La Cantine', '', False)
        self.play(self.other_user, self.visitor)
        self.client.get(f'/forum/?forum_id={forum_id}&action=join')
        self.assertIsNone(forums.get_forum('S', forum_id, self.visitor)['membership'])

    def test_post_needs_a_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        for url in ('/forum/', '/topic/', '/player_forums/', '/player_forum_manage/', '/conversations/', '/conversation/',
                    '/hrp_section/', '/hrp_topic/'):
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
