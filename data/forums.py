"""
Forums of a game server : its assembly open to all, its HRP forum on the servers without mandatory roleplay,
the taverns ('player' forums) and the assemblies of coalition managed by the players.
The rights are checked here, not in the views : a function refuses what the commandant it receives isn't allowed to do.
"""

from datetime import datetime, timedelta

from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Max, OuterRef, Q, Subquery
from django.utils import timezone
from django.utils.translation import gettext as _

from backend.models import Server
from data.errors import GameError
from database.schemas import on_server
from game.models import Commandant, ConversationMessage, Forum, ForumMember, MessageFlag, Post, Topic, TopicRead, to_id

TOPICS_PER_PAGE = 20
POSTS_PER_PAGE = 20

NAME_MAX_LENGTH = 60
AMBIANCE_MAX_LENGTH = 5000
TITLE_MAX_LENGTH = 150
BODY_MAX_LENGTH = 20000
REASON_MAX_LENGTH = 1000

MAX_OWNED_TAVERNS = 5
EDIT_DELAY = timedelta(minutes=15)


########################################################################################################################
# SHARED WITH THE PRIVATE MESSAGES


def clean_text(text, max_length, error_message, optional=False):
    text = text.replace('\x00', '').strip()  # PostgreSQL refuses the null character
    if len(text) > max_length or not (text or optional):
        raise GameError(error_message)
    return text


def clean_title(title):
    return clean_text(title, TITLE_MAX_LENGTH, _("Le titre doit faire entre 1 et 150 caractères"))


def clean_body(body):
    return clean_text(body, BODY_MAX_LENGTH, _("Le message doit faire entre 1 et 20 000 caractères"))


def author_name(author):
    return author.commandant_name if author else _("Commandant disparu")


def page_of_posts(posts, page, viewer_id, message_kind):
    # page : a number, or 'last' to reach the most recent messages

    paginator = Paginator(posts.select_related('author').order_by('id'), POSTS_PER_PAGE)
    page = paginator.get_page(paginator.num_pages if page == 'last' else page)

    page_posts = list(page.object_list)
    flagged = set(MessageFlag.objects.filter(reporter_id=viewer_id, message_kind=message_kind,
                                             message_id__in=[post.id for post in page_posts])
                  .values_list('message_id', flat=True))
    now = timezone.now()

    page.object_list = [{
        'id': post.id, 'author_id': post.author_id, 'author_name': author_name(post.author),
        'author_portrait': post.author.portrait if post.author else None,
        'body': post.body, 'datetime': post.datetime,
        'previous_versions': [{'body': version['body'], 'replaced_at': datetime.fromisoformat(version['replaced_at'])}
                              for version in post.previous_versions],
        'can_edit': post.author_id == viewer_id and now - post.datetime <= EDIT_DELAY,
        'can_flag': post.author_id not in (None, viewer_id) and post.id not in flagged,
        'is_flagged': post.id in flagged,
    } for post in page_posts]
    return page


def edit_message(message, commandant_id, body):
    # Works on a Post or a ConversationMessage, locked by the caller. The delay counts from the sending, an edit doesn't
    # give more time. Everybody can read the replaced versions : they tell a typo from a change of meaning.

    if message.author_id != commandant_id or timezone.now() - message.datetime > EDIT_DELAY:
        raise GameError(_("Ce message ne peut plus être modifié"))

    body = clean_body(body)
    if body != message.body:
        message.previous_versions.append({'body': message.body, 'replaced_at': timezone.now().isoformat()})
        message.body = body
        message.save(update_fields=['body', 'previous_versions'])


def flag_message(message_kind, message, reporter_id, reason, location):
    if message.author_id == reporter_id:
        raise GameError(_("Vous ne pouvez pas signaler votre propre message"))

    reason = clean_text(reason, REASON_MAX_LENGTH, _("Le motif doit faire au plus 1 000 caractères"), optional=True)
    MessageFlag.objects.get_or_create(
        message_kind=message_kind, message_id=message.id, reporter_id=reporter_id,
        defaults={'reason': reason, 'datetime': timezone.now(), 'author_name': author_name(message.author),
                  'location': location[:300], 'body': message.body, 'previous_versions': message.previous_versions})


def find_commandant(name):
    # Must be called on a server. Not the data.commandant one : a player can't be asked to respect the case of a name.
    commandant = Commandant.objects.filter(commandant_name__iexact=name.strip()).first()
    if commandant is None:
        raise GameError(_("Aucun commandant ne porte ce nom sur ce serveur"))
    return commandant


########################################################################################################################
# FORUMS


def default_ambiance(kind):
    return {
        'assembly': _("Sous la grande coupole de la station qui sert de capitale au secteur, chaque civilisation dispose "
                      "d'une tribune. Les discours y sont publics, les accords rarement, et chaque mot prononcé ici "
                      "finit tôt ou tard dans les archives du secteur."),
        'hrp': _("Ici, on pose les uniformes : ce forum est hors du jeu. Questions, bugs, idées ou simples discussions "
                 "entre joueurs, ce qui s'y dit n'engage pas vos commandants."),
        'coalition': _("Les portes de cette salle du conseil sont closes et gardées. Seuls les membres de la coalition y "
                       "entrent, et ce qui s'y décide ne regarde qu'eux, jusqu'au jour où le secteur en découvre les "
                       "conséquences."),
        'player': _("La fumée flotte sous les néons, les verres s'entrechoquent et les conversations baissent d'un ton à "
                    "chaque nouvel arrivant. Dans ce genre d'endroit, personne ne pose de questions, ou alors à voix "
                    "basse."),
    }[kind]


@on_server
def get_forum_id(server, kind):
    # For the forums existing once per server
    return Forum.objects.get(kind=kind).id


@on_server
def get_forum(server, forum_id, commandant_id):
    # None if it doesn't exist, if it is private and this commandant is not a member of it,
    # or if it is the HRP forum of a server where the roleplay is mandatory

    forum = Forum.objects.select_related('owner').filter(id=to_id(forum_id)).first()
    if forum is None or (forum.kind == 'hrp' and Server.objects.filter(pk=server, roleplay='RP').exists()):
        return None

    membership = ForumMember.objects.filter(forum=forum, commandant_id=commandant_id).values_list('status', flat=True).first()
    if forum.is_private and membership != 'member':
        return None

    return forum.as_dict() | {
        'name': {'assembly': _("Assemblée Sectorielle"), 'hrp': _("Forum HRP")}.get(forum.kind, forum.name),
        'ambiance': forum.description or default_ambiance(forum.kind),
        'owner_name': forum.owner.commandant_name if forum.owner else None,
        'membership': membership,
        'can_post': forum.kind in ('assembly', 'hrp') or membership == 'member',
        'is_owner': forum.owner_id == commandant_id,
    }


def can_moderate(forum, is_staff):
    return bool(forum) and (is_staff or forum['is_owner'])


@on_server
def update_forum_ambiance(server, forum_id, is_staff, ambiance):
    # The forums without owner are the business of the team. Empty : back to the default text.
    if not is_staff:
        raise GameError(_("Vous ne pouvez pas modifier ce texte"))
    Forum.objects.filter(id=to_id(forum_id), kind__in=('assembly', 'hrp')).update(description=_clean_ambiance(ambiance))


def _read_date(commandant_id):
    return Subquery(TopicRead.objects.filter(topic=OuterRef('pk'), commandant_id=commandant_id).values('last_read_date')[:1])


@on_server
def get_topics(server, forum_id, page, commandant_id):
    topics = (Topic.objects.filter(forum_id=to_id(forum_id)).select_related('author', 'last_author')
              .annotate(nb_posts=Count('posts'), read_date=_read_date(commandant_id))
              .order_by('-last_post_date', '-id'))
    page = Paginator(topics, TOPICS_PER_PAGE).get_page(page)
    page.object_list = [{'id': topic.id, 'title': topic.title, 'author_name': author_name(topic.author),
                         'nb_replies': topic.nb_posts - 1, 'last_post_date': topic.last_post_date,
                         'last_author_name': author_name(topic.last_author),
                         'is_unread': topic.read_date is None or topic.last_post_date > topic.read_date}
                        for topic in page.object_list]
    return page


@on_server
def get_topic(server, topic_id, commandant_id):
    # None if this commandant can't read its forum
    topic = Topic.objects.filter(id=to_id(topic_id)).first()
    forum = get_forum(server, topic.forum_id, commandant_id) if topic else None
    return {'id': topic.id, 'title': topic.title, 'forum': forum} if forum else None


@on_server
def get_posts(server, topic_id, page, commandant_id):
    return page_of_posts(Post.objects.filter(topic_id=to_id(topic_id)), page, commandant_id, 'post')


def _forum_open_to_posts(server, forum_id, commandant_id):
    forum = get_forum(server, forum_id, commandant_id)
    if not forum or not forum['can_post']:
        raise GameError(_("Vous ne pouvez pas écrire dans ce forum"))


def _add_post(topic, author_id, body):
    now = timezone.now()
    topic.posts.create(author_id=author_id, body=clean_body(body), datetime=now)
    topic.last_post_date, topic.last_author_id = now, author_id
    topic.save(update_fields=['last_post_date', 'last_author'])


@on_server
@transaction.atomic
def create_topic(server, forum_id, commandant_id, title, body):
    _forum_open_to_posts(server, forum_id, commandant_id)
    topic = Topic.objects.create(forum_id=to_id(forum_id), title=clean_title(title), author_id=commandant_id,
                                 last_author_id=commandant_id, last_post_date=timezone.now())
    _add_post(topic, commandant_id, body)
    return topic.id


@on_server
@transaction.atomic
def reply_to_topic(server, topic_id, commandant_id, body):
    topic = Topic.objects.filter(id=to_id(topic_id)).first()
    if topic is None:
        raise GameError(_("Ce sujet n'existe plus"))
    _forum_open_to_posts(server, topic.forum_id, commandant_id)
    _add_post(topic, commandant_id, body)


@on_server
@transaction.atomic
def edit_post(server, post_id, commandant_id, body):
    post = Post.objects.select_for_update().filter(id=to_id(post_id)).first()
    if post is None:
        raise GameError(_("Ce message n'existe plus"))
    _forum_open_to_posts(server, post.topic.forum_id, commandant_id)  # A banned member keeps out of his old messages
    edit_message(post, commandant_id, body)


@on_server
def flag_post(server, post_id, commandant_id, reason):
    post = Post.objects.select_related('topic', 'topic__forum', 'author').filter(id=to_id(post_id)).first()
    forum = get_forum(server, post.topic.forum_id, commandant_id) if post else None
    if not forum:
        raise GameError(_("Ce message n'existe plus"))
    flag_message('post', post, commandant_id, reason, f"{forum['name']} > {post.topic.title}")


def _remove_post(post):
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


@on_server
@transaction.atomic
def delete_post(server, post_id, commandant_id, is_staff):
    # Return False if the topic is gone with its last post
    post = Post.objects.select_related('topic').filter(id=to_id(post_id)).first()
    if post is None or not can_moderate(get_forum(server, post.topic.forum_id, commandant_id), is_staff):
        raise GameError(_("Vous ne pouvez pas supprimer ce message"))
    return _remove_post(post)


@on_server
def delete_topic(server, topic_id, commandant_id, is_staff):
    topic = Topic.objects.filter(id=to_id(topic_id)).first()
    if topic is None or not can_moderate(get_forum(server, topic.forum_id, commandant_id), is_staff):
        raise GameError(_("Vous ne pouvez pas supprimer ce sujet"))
    topic.delete()


########################################################################################################################
# UNREAD TOPICS


@on_server
def mark_topic_as_read(server, topic_id, commandant_id, read_until):
    # Up to the last post displayed, and never backwards : coming back to the first page changes nothing
    read = TopicRead.objects.get_or_create(topic_id=to_id(topic_id), commandant_id=commandant_id,
                                           defaults={'last_read_date': read_until})[0]
    TopicRead.objects.filter(id=read.id, last_read_date__lt=read_until).update(last_read_date=read_until)


@on_server
def mark_forum_as_read(server, forum_id, commandant_id):
    if get_forum(server, forum_id, commandant_id):
        TopicRead.objects.bulk_create(
            [TopicRead(topic_id=topic_id, commandant_id=commandant_id, last_read_date=last_post_date) for topic_id, last_post_date
             in Topic.objects.filter(forum_id=to_id(forum_id)).values_list('id', 'last_post_date')],
            update_conflicts=True, unique_fields=['topic', 'commandant'], update_fields=['last_read_date'])


@on_server
def first_unread_page(server, topic_id, commandant_id):
    # Beyond the last page when all is read : the paginator then gives the last one
    read_date = TopicRead.objects.filter(topic_id=to_id(topic_id), commandant_id=commandant_id).values_list('last_read_date', flat=True).first()
    nb_read = Post.objects.filter(topic_id=to_id(topic_id), datetime__lte=read_date).count() if read_date else 0
    return nb_read // POSTS_PER_PAGE + 1


def _unread_topics(commandant_id):
    # Followed by a commandant : the forums of the whole server, and the ones he is a member of
    memberships = ForumMember.objects.filter(commandant_id=commandant_id, status='member').values('forum_id')
    return (Topic.objects.filter(Q(forum__kind__in=('assembly', 'hrp')) | Q(forum_id__in=memberships))
            .annotate(read_date=_read_date(commandant_id))
            .filter(Q(read_date__isnull=True) | Q(last_post_date__gt=F('read_date')))
            .values('forum_id', 'forum__kind').annotate(nb_unread=Count('id')).order_by())


@on_server
def get_forum_badges(server, commandant_id):
    # Numbers displayed by the menu of every page : what is new for this commandant, by kind of forum
    badges = {'assembly': 0, 'hrp': 0, 'coalition': 0, 'player': 0}
    for row in _unread_topics(commandant_id):
        badges[row['forum__kind']] += row['nb_unread']
    for kind in ForumMember.objects.filter(commandant_id=commandant_id, status='invited').values_list('forum__kind', flat=True):
        badges[kind] += 1
    return badges


########################################################################################################################
# TAVERNS AND COALITIONS, MANAGED BY THE PLAYERS


def _clean_name(name):
    return clean_text(name, NAME_MAX_LENGTH, _("Le nom doit faire entre 1 et 60 caractères"))


def _clean_ambiance(ambiance):
    return clean_text(ambiance, AMBIANCE_MAX_LENGTH, _("Le texte d'ambiance doit faire au plus 5 000 caractères"), optional=True)


def _owned_forum(forum_id, commandant_id):
    forum = Forum.objects.filter(id=to_id(forum_id), kind__in=('player', 'coalition'), owner_id=commandant_id).first()
    if forum is None:
        raise GameError(_("Ce forum ne vous appartient pas"))
    return forum


def _create_managed_forum(kind, commandant_id, name, ambiance, is_private):
    try:
        with transaction.atomic():
            forum = Forum.objects.create(kind=kind, name=_clean_name(name), description=_clean_ambiance(ambiance),
                                         is_private=is_private, owner_id=commandant_id)
    except IntegrityError:
        raise GameError(_("Ce nom est déjà pris"))
    ForumMember.objects.create(forum=forum, commandant_id=commandant_id, status='member')
    return forum.id


def _lock_commandant(commandant_id):
    # Until the end of the transaction : two simultaneous requests of a player can't get around a limit
    Commandant.objects.select_for_update().get(id=commandant_id)


@on_server
@transaction.atomic
def create_player_forum(server, commandant_id, name, ambiance, is_private):
    _lock_commandant(commandant_id)
    if Forum.objects.filter(kind='player', owner_id=commandant_id).count() >= MAX_OWNED_TAVERNS:
        raise GameError(_("Vous possédez déjà le maximum de 5 tavernes"))
    return _create_managed_forum('player', commandant_id, name, ambiance, is_private)


@on_server
def update_player_forum(server, forum_id, commandant_id, name, ambiance, is_private):
    forum = _owned_forum(forum_id, commandant_id)
    forum.name, forum.description = _clean_name(name), _clean_ambiance(ambiance)
    forum.is_private = forum.kind == 'coalition' or is_private
    try:
        with transaction.atomic():
            forum.save(update_fields=['name', 'description', 'is_private'])
    except IntegrityError:
        raise GameError(_("Ce nom est déjà pris"))


@on_server
def destroy_player_forum(server, forum_id, commandant_id):
    _owned_forum(forum_id, commandant_id).delete()


def _forums_of_kind_list(kind, commandant_id):
    # (forum as a row of a list, status of this commandant in it)
    statuses = dict(ForumMember.objects.filter(commandant_id=commandant_id).values_list('forum_id', 'status'))
    unread = {row['forum_id']: row['nb_unread'] for row in _unread_topics(commandant_id)}
    forums = (Forum.objects.filter(kind=kind).select_related('owner')
              .annotate(last_post_date=Max('topics__last_post_date'),
                        nb_members=Count('members', filter=Q(members__status='member'), distinct=True))
              .order_by(F('last_post_date').desc(nulls_last=True), 'name'))
    for forum in forums:
        yield ({'id': forum.id, 'name': forum.name, 'is_private': forum.is_private,
                'owner_name': forum.owner.commandant_name, 'is_owner': forum.owner_id == commandant_id,
                'last_post_date': forum.last_post_date, 'nb_members': forum.nb_members,
                'nb_unread': unread.get(forum.id, 0)}, statuses.get(forum.id))


@on_server
def get_player_forums(server, commandant_id):
    # Sorted by what this commandant can do with them. The private forums of the others stay unknown to him.
    # shortcut: loads all the taverns of the server, paginate if a server ever has hundreds of them

    player_forums = {'member': [], 'invited': [], 'others': [],
                     'nb_owned': Forum.objects.filter(kind='player', owner_id=commandant_id).count()}
    for forum, status in _forums_of_kind_list('player', commandant_id):
        if status in ('member', 'invited'):
            player_forums[status].append(forum)
        elif not forum['is_private']:
            player_forums['others'].append(forum)
    return player_forums


@on_server
def get_coalition_id(server, commandant_id):
    return ForumMember.objects.filter(commandant_id=commandant_id, status='member', forum__kind='coalition') \
        .values_list('forum_id', flat=True).first()


@on_server
def get_coalition_invitations(server, commandant_id):
    return [forum for forum, status in _forums_of_kind_list('coalition', commandant_id) if status == 'invited']


@on_server
@transaction.atomic
def create_coalition(server, commandant_id, name):
    _lock_commandant(commandant_id)
    if get_coalition_id(server, commandant_id):
        raise GameError(_("Vous faites déjà partie d'une coalition"))
    return _create_managed_forum('coalition', commandant_id, name, '', True)


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
@transaction.atomic
def answer_invitation(server, forum_id, commandant_id, accepted):
    invitations = ForumMember.objects.filter(forum_id=to_id(forum_id), commandant_id=commandant_id, status='invited')
    if not accepted:
        invitations.delete()
        return

    _lock_commandant(commandant_id)
    if invitations.filter(forum__kind='coalition').exists() and get_coalition_id(server, commandant_id):
        raise GameError(_("Vous faites déjà partie d'une coalition"))
    invitations.update(status='member')


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


########################################################################################################################
# REPORTS TO THE TEAM : no check here, reserved to the views of the administration


@on_server
def count_open_flags(server):
    return MessageFlag.objects.filter(status='open').count()


@on_server
def get_flags(server):
    # shortcut: the closed flags are limited to the last 50, paginate if the team wants the whole history
    def as_rows(flags):
        return [flag.as_dict() | {'datetime': flag.datetime, 'reporter_name': author_name(flag.reporter)} for flag in flags]

    flags = MessageFlag.objects.select_related('reporter').order_by('-datetime')
    return {'open': as_rows(flags.filter(status='open')), 'closed': as_rows(flags.filter(status='closed')[:50])}


@on_server
def close_flag(server, flag_id, staff_name):
    MessageFlag.objects.filter(id=to_id(flag_id)).update(status='closed', handled_by=staff_name)


@on_server
@transaction.atomic
def delete_flagged_message(server, flag_id, staff_name):
    # All the flags of this message are settled by its deletion
    flag = MessageFlag.objects.filter(id=to_id(flag_id)).first()
    if flag is None:
        return

    if flag.message_kind == 'post':
        post = Post.objects.select_related('topic').filter(id=flag.message_id).first()
        if post:
            _remove_post(post)
    else:
        message = ConversationMessage.objects.select_related('conversation').filter(id=flag.message_id).first()
        if message:
            message.delete()
            if not message.conversation.messages.exists():
                message.conversation.delete()

    MessageFlag.objects.filter(message_kind=flag.message_kind, message_id=flag.message_id) \
        .update(status='closed', handled_by=staff_name)
