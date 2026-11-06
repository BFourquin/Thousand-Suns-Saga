"""
Private messages between the commandants of a server. Only the members of a conversation can reach it.
"""

from django.core.paginator import Paginator
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from data.errors import GameError
from data.forums import clean_body, clean_title, find_commandant, page_of_posts
from database.schemas import on_server
from game.models import Conversation, ConversationMember, ConversationMessage, to_id

CONVERSATIONS_PER_PAGE = 20


@on_server
def count_unread_conversations(server, commandant_id):
    return ConversationMember.objects.filter(commandant_id=commandant_id, has_unread=True).count()


def _send(conversation, commandant_id, body):
    now = timezone.now()
    conversation.messages.create(author_id=commandant_id, body=clean_body(body), datetime=now)
    conversation.last_message_date = now
    conversation.save(update_fields=['last_message_date'])
    conversation.members.update(hidden=False)
    conversation.members.exclude(commandant_id=commandant_id).update(has_unread=True)


@on_server
@transaction.atomic
def start_conversation(server, commandant_id, recipient_name, subject, body):
    # shortcut: one recipient only, the tables already allow more if group conversations are wanted

    recipient = find_commandant(recipient_name)
    if recipient.id == commandant_id:
        raise GameError(_("Vous ne pouvez pas vous écrire à vous-même"))

    conversation = Conversation.objects.create(subject=clean_title(subject), last_message_date=timezone.now())
    for member_id in (commandant_id, recipient.id):
        ConversationMember.objects.create(conversation=conversation, commandant_id=member_id)
    _send(conversation, commandant_id, body)
    return conversation.id


@on_server
@transaction.atomic
def send_message(server, conversation_id, commandant_id, body):
    conversation = Conversation.objects.filter(id=to_id(conversation_id), members__commandant_id=commandant_id).first()
    if conversation is None:
        raise GameError(_("Cette conversation n'existe plus"))
    _send(conversation, commandant_id, body)


@on_server
def get_conversations(server, commandant_id, page):
    memberships = (ConversationMember.objects.filter(commandant_id=commandant_id, hidden=False)
                   .select_related('conversation').prefetch_related('conversation__members__commandant')
                   .order_by('-conversation__last_message_date', '-id'))
    page = Paginator(memberships, CONVERSATIONS_PER_PAGE).get_page(page)
    page.object_list = [_conversation_dict(membership, commandant_id) for membership in page.object_list]
    return page


def _conversation_dict(membership, commandant_id):
    conversation = membership.conversation
    return {'id': conversation.id, 'subject': conversation.subject, 'has_unread': membership.has_unread,
            'last_message_date': conversation.last_message_date,
            'correspondents': ', '.join(member.commandant.commandant_name for member in conversation.members.all()
                                        if member.commandant_id != commandant_id)}


@on_server
def get_conversation(server, conversation_id, commandant_id):
    # None if this commandant is not one of its members
    membership = (ConversationMember.objects.filter(conversation_id=to_id(conversation_id), commandant_id=commandant_id)
                  .select_related('conversation').prefetch_related('conversation__members__commandant').first())
    return _conversation_dict(membership, commandant_id) if membership else None


@on_server
def get_messages(server, conversation_id, page):
    return page_of_posts(ConversationMessage.objects.filter(conversation_id=to_id(conversation_id)), page)


@on_server
def mark_conversation_as_read(server, conversation_id, commandant_id):
    ConversationMember.objects.filter(conversation_id=to_id(conversation_id), commandant_id=commandant_id).update(has_unread=False)


@on_server
@transaction.atomic
def hide_conversations(server, conversation_ids, commandant_id):
    # Only from the list of this commandant : the conversation is deleted once no member keeps it

    conversation_ids = [to_id(conversation_id) for conversation_id in conversation_ids]
    ConversationMember.objects.filter(conversation_id__in=conversation_ids, commandant_id=commandant_id) \
        .update(hidden=True, has_unread=False)
    Conversation.objects.filter(id__in=conversation_ids, members__commandant_id=commandant_id) \
        .exclude(members__hidden=False).delete()
