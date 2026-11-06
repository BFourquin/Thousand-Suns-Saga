"""
Ententes of a game server : the native ones gather automatically the commandants born in a sector,
the others are founded by a commandant to make an alliance, and joined by applying to their founder.
A commandant can belong to any number of them.
The rights are checked here, not in the views : a function refuses what the commandant it receives isn't allowed to do.
"""

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.translation import gettext as _

from data.errors import GameError
from data.forums import clean_text
from database.schemas import on_server
from game.models import Commandant, Entente, EntenteMember, to_id

NATIVE = 'native'

NAME_MAX_LENGTH = 60
DESCRIPTION_MAX_LENGTH = 5000
APPLICATION_MAX_LENGTH = 1000

MAX_FOUNDED_ENTENTES = 5


def founded_categories():
    return {'economic': _("Économique"), 'military': _("Militaire"), 'political': _("Politique"),
            'scientific': _("Scientifique"), 'religious': _("Religieuse"), 'other': _("Autre")}


def _category_label(category):
    return _("Native") if category == NATIVE else founded_categories().get(category, category)


def _entente_name(entente):
    if entente.category != NATIVE:
        return entente.name
    # Seed of a sector : 4 digits of the server, 3 of its Y position, 3 of its X position
    sector = entente.native_sector
    return _("Natifs du secteur %(sector)s") % {'sector': f'{int(sector[4:7])}-{int(sector[7:10])}'}


def _clean_description(description):
    return clean_text(description, DESCRIPTION_MAX_LENGTH, _("La description doit faire au plus 5 000 caractères"), optional=True)


def _create_report(server, commandant_id, report_type, entente):
    from data.report import create_report  # Placed here to prevent circular import
    create_report(server, commandant_id, report_type, {'entente': entente.name})


########################################################################################################################
# NATIVE ENTENTES


@on_server
def join_native_entente(server, commandant):
    # Created with the first commandant born in its sector. A locked StartingValues keeps the creations of commandants in line.
    now = timezone.now()
    entente = Entente.objects.get_or_create(native_sector=commandant.native_sector,
                                            defaults={'category': NATIVE, 'creation_date': now})[0]
    EntenteMember.objects.create(entente=entente, commandant=commandant, status='member', datetime=now)
    commandant.native_entente = entente
    commandant.save(update_fields=['native_entente'])


########################################################################################################################
# READING


@on_server
def get_ententes(server, commandant_id):
    # The private applications of the others only count for their founder.
    # shortcut: loads all the ententes of the server, paginate if a server ever has hundreds of them

    statuses = dict(EntenteMember.objects.filter(commandant_id=commandant_id).values_list('entente_id', 'status'))
    ententes = {'mine': [], 'others': []}

    for entente in (Entente.objects.select_related('founder')
                    .annotate(nb_members=Count('members', filter=Q(members__status='member')),
                              nb_applications=Count('members', filter=Q(members__status='applicant')))
                    .order_by('-nb_members', 'name')):
        status = statuses.get(entente.id)
        ententes['mine' if status == 'member' else 'others'].append({
            'id': entente.id, 'name': _entente_name(entente), 'category': entente.category,
            'category_label': _category_label(entente.category),
            'founder_name': entente.founder.commandant_name if entente.founder else None,
            'nb_members': entente.nb_members, 'status': status,
            'nb_applications': entente.nb_applications if entente.founder_id == commandant_id else 0})
    return ententes


@on_server
def get_entente(server, entente_id, commandant_id):
    # None if it doesn't exist. The members are public, the applications are not.

    entente = Entente.objects.select_related('founder').filter(id=to_id(entente_id)).first()
    if entente is None:
        return None

    rows = list(EntenteMember.objects.filter(entente=entente).select_related('commandant')
                .order_by('datetime', 'commandant__commandant_name'))
    mine = next((row for row in rows if row.commandant_id == commandant_id), None)
    is_founder = entente.founder_id == commandant_id
    is_native = entente.category == NATIVE

    def person(row):
        return {'id': row.commandant_id, 'name': row.commandant.commandant_name, 'portrait': row.commandant.portrait,
                'civilisation_name': row.commandant.civilisation_name, 'datetime': row.datetime,
                'is_founder': row.commandant_id == entente.founder_id}

    return {
        'id': entente.id, 'name': _entente_name(entente), 'is_native': is_native,
        'category_label': _category_label(entente.category), 'description': entente.description,
        'founder_name': entente.founder.commandant_name if entente.founder else None, 'creation_date': entente.creation_date,
        'status': mine.status if mine else None, 'my_application': mine.application if mine else '',
        'is_founder': is_founder, 'can_apply': not is_native and mine is None,
        'members': [person(row) for row in rows if row.status == 'member'],
        'applications': [person(row) | {'application': row.application} for row in rows if row.status == 'applicant'] if is_founder else [],
    }


@on_server
def count_applications_to_answer(server, commandant_id):
    # Number displayed by the menu of every page
    return EntenteMember.objects.filter(entente__founder_id=commandant_id, status='applicant').count()


@on_server
def can_found_entente(server, commandant_id):
    return Entente.objects.filter(founder_id=commandant_id).count() < MAX_FOUNDED_ENTENTES


########################################################################################################################
# ORDERS OF A COMMANDANT


@on_server
@transaction.atomic
def found_entente(server, commandant_id, name, category, description):
    # The commandant is locked until the end of the transaction : two simultaneous requests can't get around the limit
    Commandant.objects.select_for_update().get(id=commandant_id)
    if not can_found_entente(server, commandant_id):
        raise GameError(_("Vous avez déjà fondé le maximum de 5 ententes"))
    if category not in founded_categories():
        raise GameError(_("Ce type d'entente n'existe pas"))

    now = timezone.now()
    name = clean_text(name, NAME_MAX_LENGTH, _("Le nom doit faire entre 1 et 60 caractères"))
    try:
        with transaction.atomic():
            entente = Entente.objects.create(category=category, name=name, description=_clean_description(description),
                                             founder_id=commandant_id, creation_date=now)
    except IntegrityError:
        raise GameError(_("Ce nom est déjà pris"))
    EntenteMember.objects.create(entente=entente, commandant_id=commandant_id, status='member', datetime=now)
    return entente.id


@on_server
def apply_to_entente(server, entente_id, commandant_id, application):
    entente = Entente.objects.filter(id=to_id(entente_id)).exclude(category=NATIVE).first()
    if entente is None:
        raise GameError(_("Vous ne pouvez pas postuler à cette entente"))
    application = clean_text(application, APPLICATION_MAX_LENGTH, _("La candidature doit faire au plus 1 000 caractères"), optional=True)
    # Changes nothing for a member, or for an application already sent
    EntenteMember.objects.get_or_create(entente=entente, commandant_id=commandant_id,
                                        defaults={'status': 'applicant', 'application': application, 'datetime': timezone.now()})


@on_server
def leave_entente(server, entente_id, commandant_id):
    # Also takes back an application. Nobody leaves a native entente, and a founder has to dissolve the entente instead.
    EntenteMember.objects.filter(entente_id=to_id(entente_id), commandant_id=commandant_id) \
        .exclude(entente__category=NATIVE).exclude(entente__founder_id=commandant_id).delete()


########################################################################################################################
# ORDERS OF A FOUNDER


def _founded_entente(entente_id, founder_id):
    entente = Entente.objects.filter(id=to_id(entente_id), founder_id=founder_id).first()
    if entente is None:
        raise GameError(_("Vous n'avez pas fondé cette entente"))
    return entente


@on_server
def update_entente_description(server, entente_id, founder_id, description):
    entente = _founded_entente(entente_id, founder_id)
    entente.description = _clean_description(description)
    entente.save(update_fields=['description'])


@on_server
@transaction.atomic
def answer_application(server, entente_id, founder_id, applicant_id, accepted):
    # Answering twice changes nothing and sends no second report
    entente = _founded_entente(entente_id, founder_id)
    applications = EntenteMember.objects.filter(entente=entente, commandant_id=to_id(applicant_id), status='applicant')
    if accepted and applications.update(status='member', datetime=timezone.now()):
        _create_report(server, to_id(applicant_id), 'entente_application_accepted', entente)
    elif not accepted and applications.delete()[0]:
        _create_report(server, to_id(applicant_id), 'entente_application_refused', entente)


@on_server
@transaction.atomic
def exclude_member(server, entente_id, founder_id, member_id):
    entente = _founded_entente(entente_id, founder_id)
    if EntenteMember.objects.filter(entente=entente, commandant_id=to_id(member_id), status='member') \
            .exclude(commandant_id=founder_id).delete()[0]:
        _create_report(server, to_id(member_id), 'entente_member_excluded', entente)


@on_server
@transaction.atomic
def dissolve_entente(server, entente_id, founder_id):
    entente = _founded_entente(entente_id, founder_id)
    for commandant_id in EntenteMember.objects.filter(entente=entente).exclude(commandant_id=founder_id) \
            .values_list('commandant_id', flat=True):
        _create_report(server, commandant_id, 'entente_dissolved', entente)
    entente.delete()
