"""
Out-of-character forum, common to all the servers : in the main schema, written by accounts and not by commandants.
"""

from django.db import transaction
from django.db.models import Count, Max
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_lazy

from backend.models import HrpPost, HrpTopic, to_id
from data.errors import GameError
from data.forums import add_post, clean_title, page_of_posts, page_of_topics, remove_post

SECTIONS = {
    'announcements': {'name': gettext_lazy("Annonces"), 'icon': 'fa-bullhorn', 'staff_only': True,
                      'description': gettext_lazy("Les nouvelles du jeu. Seule l'équipe y ouvre des sujets, tout le monde peut y réagir.")},
    'help': {'name': gettext_lazy("Aide et questions"), 'icon': 'fa-circle-question', 'staff_only': False,
             'description': gettext_lazy("Comprendre le fonctionnement du jeu.")},
    'bugs': {'name': gettext_lazy("Bugs"), 'icon': 'fa-bug', 'staff_only': False,
             'description': gettext_lazy("Signaler ce qui ne fonctionne pas.")},
    'ideas': {'name': gettext_lazy("Suggestions"), 'icon': 'fa-lightbulb', 'staff_only': False,
              'description': gettext_lazy("Proposer des améliorations.")},
    'misc': {'name': gettext_lazy("Discussions libres"), 'icon': 'fa-mug-hot', 'staff_only': False,
             'description': gettext_lazy("Tout le reste, hors du jeu.")},
}


def get_sections():
    stats = {row['section']: row for row in
             HrpTopic.objects.values('section').annotate(nb_topics=Count('id', distinct=True), nb_posts=Count('posts'),
                                                         last_post_date=Max('last_post_date'))}
    return [{'id': section_id, **section, **stats.get(section_id, {})} for section_id, section in SECTIONS.items()]


def get_topics(section, page):
    return page_of_topics(HrpTopic.objects.filter(section=section), page)


def get_topic(topic_id):
    topic = HrpTopic.objects.filter(id=to_id(topic_id)).first()
    return {'id': topic.id, 'title': topic.title, 'section': topic.section} if topic else None


def get_posts(topic_id, page):
    return page_of_posts(HrpPost.objects.filter(topic_id=to_id(topic_id)), page)


@transaction.atomic
def create_topic(section, user_id, is_staff, title, body):
    if section not in SECTIONS or (SECTIONS[section]['staff_only'] and not is_staff):
        raise GameError(_("Vous ne pouvez pas ouvrir de sujet ici"))
    topic = HrpTopic.objects.create(section=section, title=clean_title(title), author_id=user_id,
                                    last_author_id=user_id, last_post_date=timezone.now())
    add_post(topic, user_id, body)
    return topic.id


@transaction.atomic
def reply_to_topic(topic_id, user_id, body):
    topic = HrpTopic.objects.filter(id=to_id(topic_id)).first()
    if topic is None:
        raise GameError(_("Ce sujet n'existe plus"))
    add_post(topic, user_id, body)


@transaction.atomic
def delete_post(post_id, is_staff):
    # Return False if the topic is gone with its last post
    post = HrpPost.objects.select_related('topic').filter(id=to_id(post_id)).first()
    if post is None or not is_staff:
        raise GameError(_("Vous ne pouvez pas supprimer ce message"))
    return remove_post(post)


def delete_topic(topic_id, is_staff):
    if not is_staff:
        raise GameError(_("Vous ne pouvez pas supprimer ce sujet"))
    HrpTopic.objects.filter(id=to_id(topic_id)).delete()
