from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _

from backend.decorators import add_cycle_info, commandant_required, log_player_action
from data import conversations, forums, hrp_forum
from data.commandant import get_commandant_names
from data.errors import GameError


# Texts come from request.POST and not from request_params : a repeated parameter would give a list instead of a text


########################################################################################################################
# FORUMS OF THE SERVER


@login_required(login_url='/player_login/')
@add_cycle_info
@log_player_action
@commandant_required
def assembly(request, server, commandant):
    return redirect(f'/forum/?forum_id={forums.get_assembly_id(server)}')


@login_required(login_url='/player_login/')
@add_cycle_info
@log_player_action
@commandant_required
def forum(request, server, commandant):

    forum = forums.get_forum(server, request.GET.get('forum_id'), commandant['id'])
    if not forum:
        return redirect('/player_forums/')

    error = None
    if request.method == 'POST':
        try:
            action = request.POST.get('action')
            if action == 'new_topic':
                topic_id = forums.create_topic(server, forum['id'], commandant['id'],
                                               request.POST.get('title', ''), request.POST.get('body', ''))
                return redirect(f'/topic/?topic_id={topic_id}')
            if action == 'join':
                forums.join_forum(server, forum['id'], commandant['id'])
            elif action == 'leave':
                forums.leave_forum(server, forum['id'], commandant['id'])
            return redirect(request.get_full_path())
        except GameError as game_error:
            error = str(game_error)

    return TemplateResponse(request, 'game/forum.html', {
        'forum': forum, 'forum_title': forum['name'], 'forum_description': forum['description'],
        'topics': forums.get_topics(server, forum['id'], request.GET.get('page', 1)),
        'can_create_topic': forum['can_post'], 'topic_url': '/topic/',
        'back_url': '/player_forums/' if forum['kind'] == 'player' else None, 'back_label': _("Tavernes"),
        'error': error})


@login_required(login_url='/player_login/')
@add_cycle_info
@log_player_action
@commandant_required
def topic(request, server, commandant):

    topic = forums.get_topic(server, request.GET.get('topic_id'), commandant['id'])
    if not topic:
        return redirect('/assembly/')
    forum = topic['forum']
    forum_url = f"/forum/?forum_id={forum['id']}"

    error = None
    if request.method == 'POST':
        try:
            if 'delete_topic' in request.POST:
                forums.delete_topic(server, topic['id'], commandant['id'], request.user.is_staff)
                return redirect(forum_url)
            if 'delete_post' in request.POST:
                topic_remains = forums.delete_post(server, request.POST['delete_post'], commandant['id'], request.user.is_staff)
                return redirect(request.get_full_path() if topic_remains else forum_url)
            forums.reply_to_topic(server, topic['id'], commandant['id'], request.POST.get('body', ''))
            return redirect(f"/topic/?topic_id={topic['id']}&page=last")
        except GameError as game_error:
            error = str(game_error)

    return TemplateResponse(request, 'game/forum_thread.html', {
        'forum': forum, 'thread_title': topic['title'], 'back_url': forum_url, 'back_label': forum['name'],
        'posts': forums.get_posts(server, topic['id'], request.GET.get('page', 1)),
        'can_post': forum['can_post'], 'can_moderate': forums.can_moderate(forum, request.user.is_staff),
        'error': error})


########################################################################################################################
# FORUMS MANAGED BY THE PLAYERS


@login_required(login_url='/player_login/')
@add_cycle_info
@log_player_action
@commandant_required
def player_forums(request, server, commandant):

    error = None
    if request.method == 'POST':
        try:
            action = request.POST.get('action')
            if action == 'create':
                forum_id = forums.create_player_forum(server, commandant['id'], request.POST.get('name', ''),
                                                      request.POST.get('description', ''), 'is_private' in request.POST)
                return redirect(f'/player_forum_manage/?forum_id={forum_id}')
            if action in ('accept', 'decline'):
                forums.answer_invitation(server, request.POST.get('forum_id'), commandant['id'], action == 'accept')
            return redirect('/player_forums/')
        except GameError as game_error:
            error = str(game_error)

    return TemplateResponse(request, 'game/player_forums.html', {
        'player_forums': forums.get_player_forums(server, commandant['id']), 'error': error})


@login_required(login_url='/player_login/')
@add_cycle_info
@log_player_action
@commandant_required
def player_forum_manage(request, server, commandant):

    forum = forums.get_forum(server, request.GET.get('forum_id'), commandant['id'])
    if not forum or not forum['is_owner']:
        return redirect('/player_forums/')

    error = None
    if request.method == 'POST':
        try:
            action = request.POST.get('action')
            if action == 'save':
                forums.update_player_forum(server, forum['id'], commandant['id'], request.POST.get('name', ''),
                                           request.POST.get('description', ''), 'is_private' in request.POST)
            elif action == 'invite':
                forums.invite_to_forum(server, forum['id'], commandant['id'], request.POST.get('invited_name', ''))
            elif action == 'remove':
                forums.remove_from_forum(server, forum['id'], commandant['id'], request.POST.get('commandant_id'))
            elif action == 'destroy':
                forums.destroy_player_forum(server, forum['id'], commandant['id'])
                return redirect('/player_forums/')
            return redirect(request.get_full_path())
        except GameError as game_error:
            error = str(game_error)

    return TemplateResponse(request, 'game/player_forum_manage.html', {
        'forum': forum, 'members': forums.get_forum_members(server, forum['id']),
        'commandant_names': get_commandant_names(server), 'error': error})


########################################################################################################################
# PRIVATE MESSAGES


@login_required(login_url='/player_login/')
@add_cycle_info
@log_player_action
@commandant_required
def conversations_list(request, server, commandant):

    error = None
    if request.method == 'POST':
        try:
            if request.POST.get('action') == 'new':
                conversation_id = conversations.start_conversation(
                    server, commandant['id'], request.POST.get('recipient', ''),
                    request.POST.get('subject', ''), request.POST.get('body', ''))
                return redirect(f'/conversation/?conversation_id={conversation_id}')
            conversations.hide_conversations(server, request.POST.getlist('conversations[]'), commandant['id'])
            return redirect('/conversations/')
        except GameError as game_error:
            error = str(game_error)

    return TemplateResponse(request, 'game/conversations.html', {
        'conversations': conversations.get_conversations(server, commandant['id'], request.GET.get('page', 1)),
        'commandant_names': get_commandant_names(server), 'recipient': request.POST.get('recipient', request.GET.get('to', '')),
        'error': error})


@login_required(login_url='/player_login/')
@add_cycle_info
@log_player_action
@commandant_required
def conversation(request, server, commandant):

    conversation = conversations.get_conversation(server, request.GET.get('conversation_id'), commandant['id'])
    if not conversation:
        return redirect('/conversations/')

    error = None
    if request.method == 'POST':
        try:
            conversations.send_message(server, conversation['id'], commandant['id'], request.POST.get('body', ''))
            return redirect(f"/conversation/?conversation_id={conversation['id']}")
        except GameError as game_error:
            error = str(game_error)

    conversations.mark_conversation_as_read(server, conversation['id'], commandant['id'])

    return TemplateResponse(request, 'game/forum_thread.html', {
        'thread_title': conversation['subject'], 'thread_subtitle': conversation['correspondents'],
        'back_url': '/conversations/', 'back_label': _("Messages privés"),
        'posts': conversations.get_messages(server, conversation['id'], request.GET.get('page', 'last')),
        'can_post': True, 'can_moderate': False, 'error': error})


########################################################################################################################
# HRP FORUM : no commandant needed, it is common to all the servers


@login_required(login_url='/player_login/')
@add_cycle_info
@log_player_action
def hrp(request):
    return TemplateResponse(request, 'game/hrp.html', {'sections': hrp_forum.get_sections()})


@login_required(login_url='/player_login/')
@add_cycle_info
@log_player_action
def hrp_section(request):

    section_id = request.GET.get('section')
    section = hrp_forum.SECTIONS.get(section_id)
    if not section:
        return redirect('/hrp/')

    error = None
    if request.method == 'POST':
        try:
            topic_id = hrp_forum.create_topic(section_id, request.user.id, request.user.is_staff,
                                              request.POST.get('title', ''), request.POST.get('body', ''))
            return redirect(f'/hrp_topic/?topic_id={topic_id}')
        except GameError as game_error:
            error = str(game_error)

    return TemplateResponse(request, 'game/forum.html', {
        'forum_title': section['name'], 'forum_description': section['description'],
        'topics': hrp_forum.get_topics(section_id, request.GET.get('page', 1)),
        'can_create_topic': not section['staff_only'] or request.user.is_staff, 'topic_url': '/hrp_topic/',
        'back_url': '/hrp/', 'back_label': _("Forum HRP"), 'error': error})


@login_required(login_url='/player_login/')
@add_cycle_info
@log_player_action
def hrp_topic(request):

    topic = hrp_forum.get_topic(request.GET.get('topic_id'))
    if not topic:
        return redirect('/hrp/')
    section_url = f"/hrp_section/?section={topic['section']}"

    error = None
    if request.method == 'POST':
        try:
            if 'delete_topic' in request.POST:
                hrp_forum.delete_topic(topic['id'], request.user.is_staff)
                return redirect(section_url)
            if 'delete_post' in request.POST:
                topic_remains = hrp_forum.delete_post(request.POST['delete_post'], request.user.is_staff)
                return redirect(request.get_full_path() if topic_remains else section_url)
            hrp_forum.reply_to_topic(topic['id'], request.user.id, request.POST.get('body', ''))
            return redirect(f"/hrp_topic/?topic_id={topic['id']}&page=last")
        except GameError as game_error:
            error = str(game_error)

    return TemplateResponse(request, 'game/forum_thread.html', {
        'thread_title': topic['title'], 'back_url': section_url, 'back_label': hrp_forum.SECTIONS[topic['section']]['name'],
        'posts': hrp_forum.get_posts(topic['id'], request.GET.get('page', 1)),
        'can_post': True, 'can_moderate': request.user.is_staff, 'error': error})
