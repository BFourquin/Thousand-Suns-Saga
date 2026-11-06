"""
Forums of a game server : its assembly, open to all, and the forums managed by the players.
The rights are checked here, not in the views : a function refuses what the commandant it receives isn't allowed to do.
"""

from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Max, Q
from django.utils import timezone
from django.utils.translation import gettext as _

from data.errors import GameError
from database.schemas import on_server
from game.models import Commandant, Forum, ForumMember, Post, Topic, to_id

TOPICS_PER_PAGE = 20
POSTS_PER_PAGE = 20

NAME_MAX_LENGTH = 60
DESCRIPTION_MAX_LENGTH = 2000
TITLE_MAX_LENGTH = 150
BODY_MAX_LENGTH = 20000


########################################################################################################################
# SHARED WITH THE PRIVATE MESSAGES AND THE HRP FORUM


def clean_text(text, max_length, error_message):
    text = text.replace('\x00', '').strip()  # PostgreSQL refuses the null character
    if not 1 <= len(text) <= max_length:
        raise GameError(error_message)
    return text


def clean_title(title):
    return clean_text(title, TITLE_MAX_LENGTH, _("Le titre doit faire entre 1 et 150 caractères"))


def clean_body(body):
    return clean_text(body, BODY_MAX_LENGTH, _("Le message doit faire entre 1 et 20 000 caractères"))


def author_name(author):
    # A commandant on the forums of a server, an account on the HRP forum, nothing once deleted
    if author is None:
        return _("Compte supprimé")
    return author.commandant_name if hasattr(author, 'commandant_name') else author.username


def page_of_topics(topics, page):
    topics = topics.select_related('author', 'last_author').annotate(nb_posts=Count('posts')).order_by('-last_post_date', '-id')
    page = Paginator(topics, TOPICS_PER_PAGE).get_page(page)
    page.object_list = [{'id': topic.id, 'title': topic.title, 'author_name': author_name(topic.author),
                         'nb_replies': topic.nb_posts - 1, 'last_post_date': topic.last_post_date,
                         'last_author_name': author_name(topic.last_author)}
                        for topic in page.object_list]
    return page


def page_of_posts(posts, page):
    # page : a number, or 'last' to reach the most recent messages
    paginator = Paginator(posts.select_related('author').order_by('id'), POSTS_PER_PAGE)
    page = paginator.get_page(paginator.num_pages if page == 'last' else page)
    page.object_list = [{'id': post.id, 'author_id': post.author_id, 'author_name': author_name(post.author),
                         'author_portrait': getattr(post.author, 'portrait', None),
                         'body': post.body, 'datetime': post.datetime}
                        for post in page.object_list]
    return page


def add_post(topic, author_id, body):
    now = timezone.now()
    topic.posts.create(author_id=author_id, body=clean_body(body), datetime=now)
    topic.last_post_date, topic.last_author_id = now, author_id
    topic.save(update_fields=['last_post_date', 'last_author'])


def remove_post(post):
    # Return False when it was the last post of its topic, which is removed too
    topic = post.topic
    post.delete()
    last_post = topic.posts.order_by('-id').first()
    if last_post is None:
        topic.delete()
        return False
    topic.last_post_date, topic.last_author_id = last_post.datetime, last_post.author_id
    topic.save(update_fields=['last_post_date', 'last_author'])
    return True


def find_commandant(name):
    # Must be called on a server. Not the data.commandant one : a player can't be asked to respect the case of a name.
    commandant = Commandant.objects.filter(commandant_name__iexact=name.strip()).first()
    if commandant is None:
        raise GameError(_("Aucun commandant ne porte ce nom sur ce serveur"))
    return commandant


########################################################################################################################
# FORUMS


@on_server
def get_assembly_id(server):
    return Forum.objects.get(kind='assembly').id


@on_server
def get_forum(server, forum_id, commandant_id):
    # None if it doesn't exist or if it is a private forum this commandant is not a member of

    forum = Forum.objects.select_related('owner').filter(id=to_id(forum_id)).first()
    if forum is None:
        return None

    membership = ForumMember.objects.filter(forum=forum, commandant_id=commandant_id).values_list('status', flat=True).first()
    if forum.is_private and membership != 'member':
        return None

    return forum.as_dict() | {
        'name': _("Assemblée Sectorielle") if forum.kind == 'assembly' else forum.name,
        'owner_name': forum.owner.commandant_name if forum.owner else None,
        'membership': membership,
        'can_post': forum.kind == 'assembly' or membership == 'member',
        'is_owner': forum.owner_id == commandant_id,
    }


def can_moderate(forum, is_staff):
    return bool(forum) and (is_staff or forum['is_owner'])


@on_server
def get_topics(server, forum_id, page):
    return page_of_topics(Topic.objects.filter(forum_id=to_id(forum_id)), page)


@on_server
def get_topic(server, topic_id, commandant_id):
    # None if this commandant can't read its forum
    topic = Topic.objects.filter(id=to_id(topic_id)).first()
    forum = get_forum(server, topic.forum_id, commandant_id) if topic else None
    return {'id': topic.id, 'title': topic.title, 'forum': forum} if forum else None


@on_server
def get_posts(server, topic_id, page):
    return page_of_posts(Post.objects.filter(topic_id=to_id(topic_id)), page)


def _forum_open_to_posts(server, forum_id, commandant_id):
    forum = get_forum(server, forum_id, commandant_id)
    if not forum or not forum['can_post']:
        raise GameError(_("Vous ne pouvez pas écrire dans ce forum"))


@on_server
@transaction.atomic
def create_topic(server, forum_id, commandant_id, title, body):
    _forum_open_to_posts(server, forum_id, commandant_id)
    topic = Topic.objects.create(forum_id=to_id(forum_id), title=clean_title(title), author_id=commandant_id,
                                 last_author_id=commandant_id, last_post_date=timezone.now())
    add_post(topic, commandant_id, body)
    return topic.id


@on_server
@transaction.atomic
def reply_to_topic(server, topic_id, commandant_id, body):
    topic = Topic.objects.filter(id=to_id(topic_id)).first()
    if topic is None:
        raise GameError(_("Ce sujet n'existe plus"))
    _forum_open_to_posts(server, topic.forum_id, commandant_id)
    add_post(topic, commandant_id, body)


@on_server
@transaction.atomic
def delete_post(server, post_id, commandant_id, is_staff):
    # Return False if the topic is gone with its last post
    post = Post.objects.select_related('topic').filter(id=to_id(post_id)).first()
    if post is None or not can_moderate(get_forum(server, post.topic.forum_id, commandant_id), is_staff):
        raise GameError(_("Vous ne pouvez pas supprimer ce message"))
    return remove_post(post)


@on_server
def delete_topic(server, topic_id, commandant_id, is_staff):
    topic = Topic.objects.filter(id=to_id(topic_id)).first()
    if topic is None or not can_moderate(get_forum(server, topic.forum_id, commandant_id), is_staff):
        raise GameError(_("Vous ne pouvez pas supprimer ce sujet"))
    topic.delete()


########################################################################################################################
# FORUMS MANAGED BY THE PLAYERS


def _clean_name(name):
    return clean_text(name, NAME_MAX_LENGTH, _("Le nom doit faire entre 1 et 60 caractères"))


def _clean_description(description):
    # Optional : not clean_text, which refuses an empty text
    description = description.replace('\x00', '').strip()
    if len(description) > DESCRIPTION_MAX_LENGTH:
        raise GameError(_("La description doit faire au plus 2 000 caractères"))
    return description


def _owned_forum(forum_id, commandant_id):
    forum = Forum.objects.filter(id=to_id(forum_id), kind='player', owner_id=commandant_id).first()
    if forum is None:
        raise GameError(_("Ce forum ne vous appartient pas"))
    return forum


@on_server
@transaction.atomic
def create_player_forum(server, commandant_id, name, description, is_private):
    try:
        with transaction.atomic():
            forum = Forum.objects.create(kind='player', name=_clean_name(name), description=_clean_description(description),
                                         is_private=is_private, owner_id=commandant_id)
    except IntegrityError:
        raise GameError(_("Ce nom est déjà pris"))
    ForumMember.objects.create(forum=forum, commandant_id=commandant_id, status='member')
    return forum.id


@on_server
def update_player_forum(server, forum_id, commandant_id, name, description, is_private):
    forum = _owned_forum(forum_id, commandant_id)
    forum.name, forum.description, forum.is_private = _clean_name(name), _clean_description(description), is_private
    try:
        with transaction.atomic():
            forum.save(update_fields=['name', 'description', 'is_private'])
    except IntegrityError:
        raise GameError(_("Ce nom est déjà pris"))


@on_server
def destroy_player_forum(server, forum_id, commandant_id):
    _owned_forum(forum_id, commandant_id).delete()


@on_server
def get_player_forums(server, commandant_id):
    # Sorted by what this commandant can do with them. The private forums of the others stay unknown to him.
    # shortcut: loads all the forums of the server, paginate if a server ever has hundreds of them

    statuses = dict(ForumMember.objects.filter(commandant_id=commandant_id).values_list('forum_id', 'status'))
    forums = (Forum.objects.filter(kind='player').select_related('owner')
              .annotate(last_post_date=Max('topics__last_post_date'),
                        nb_members=Count('members', filter=Q(members__status='member'), distinct=True))
              .order_by(F('last_post_date').desc(nulls_last=True), 'name'))

    player_forums = {'member': [], 'invited': [], 'others': []}
    for forum in forums:
        status = statuses.get(forum.id)
        if status in ('member', 'invited') or not forum.is_private:
            player_forums[status if status in ('member', 'invited') else 'others'].append(
                {'id': forum.id, 'name': forum.name, 'description': forum.description, 'is_private': forum.is_private,
                 'owner_name': forum.owner.commandant_name, 'is_owner': forum.owner_id == commandant_id,
                 'last_post_date': forum.last_post_date, 'nb_members': forum.nb_members})
    return player_forums


@on_server
def count_invitations(server, commandant_id):
    return ForumMember.objects.filter(commandant_id=commandant_id, status='invited').count()


@on_server
def get_forum_members(server, forum_id):
    return [{'id': member.commandant_id, 'name': member.commandant.commandant_name,
             'portrait': member.commandant.portrait, 'status': member.status}
            for member in ForumMember.objects.filter(forum_id=to_id(forum_id)).select_related('commandant')
            .order_by('status', 'commandant__commandant_name')]


@on_server
def invite_to_forum(server, forum_id, commandant_id, invited_name):
    # An invitation also gives a new chance to a banned commandant
    forum = _owned_forum(forum_id, commandant_id)
    invited = find_commandant(invited_name)
    if ForumMember.objects.filter(forum=forum, commandant=invited, status='member').exists():
        raise GameError(_("Ce commandant est déjà membre"))
    ForumMember.objects.update_or_create(forum=forum, commandant=invited, defaults={'status': 'invited'})


@on_server
def remove_from_forum(server, forum_id, commandant_id, removed_id):
    # A removed member is banned, or he could come back alone in a public forum. Removing the others forgets them.
    forum = _owned_forum(forum_id, commandant_id)
    member = ForumMember.objects.filter(forum=forum, commandant_id=to_id(removed_id)).exclude(commandant_id=commandant_id).first()
    if member is None:
        return
    if member.status == 'member':
        member.status = 'banned'
        member.save(update_fields=['status'])
    else:
        member.delete()


@on_server
def answer_invitation(server, forum_id, commandant_id, accepted):
    invitations = ForumMember.objects.filter(forum_id=to_id(forum_id), commandant_id=commandant_id, status='invited')
    if accepted:
        invitations.update(status='member')
    else:
        invitations.delete()


@on_server
def join_forum(server, forum_id, commandant_id):
    forum = get_forum(server, forum_id, commandant_id)
    if not forum or forum['kind'] != 'player' or forum['membership'] == 'banned':
        raise GameError(_("Vous ne pouvez pas rejoindre ce forum"))
    ForumMember.objects.update_or_create(forum_id=forum['id'], commandant_id=commandant_id, defaults={'status': 'member'})


@on_server
def leave_forum(server, forum_id, commandant_id):
    # The owner has to destroy his forum to leave it
    ForumMember.objects.filter(forum_id=to_id(forum_id), commandant_id=commandant_id, status='member') \
        .exclude(forum__owner_id=commandant_id).delete()
