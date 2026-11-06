"""
Ententes of a game server : the native ones gather automatically the commandants born in a sector,
the others are created by a commandant to make an alliance, and joined by applying or by invitation.
A commandant can belong to any number of them.

In an alliance, the owner has every right and is unique : Entente.owner, so there can't be a second one. The other
members hold a role with its options, customizable. A role or a member with an option that a commandant doesn't hold stays
out of reach of this commandant, and only the options held can be given : nobody can raise their own rights.

The rights are checked here, not in the views : a function refuses what the commandant it receives isn't allowed to do.
"""

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.translation import gettext as _

from data.errors import GameError
from data.forums import clean_text, find_commandant
from database.schemas import on_server
from game.models import Commandant, Entente, EntenteMember, EntenteRole, to_id

NATIVE = 'native'

NAME_MAX_LENGTH = 60
ROLE_NAME_MAX_LENGTH = 40
DESCRIPTION_MAX_LENGTH = 5000
APPLICATION_MAX_LENGTH = 1000

MAX_OWNED_ENTENTES = 5

MANAGE_ROLES, INVITE_MEMBER, EXCLUDE_MEMBER = 'manage_roles', 'invite_member', 'exclude_member'
# Stored on the roles, but the mechanic they will open doesn't exist yet
UPCOMING_OPTIONS = ('moderate_assembly', 'shared_radar', 'shared_fleets', 'manage_finances')
# A custom role can't pass for a default one, in any language
RESERVED_ROLE_NAMES = ('propriétaire', 'owner', 'membre', 'member')


def founded_categories():
    return {'economic': _("Économique"), 'military': _("Militaire"), 'political': _("Politique"),
            'scientific': _("Scientifique"), 'religious': _("Religieuse"), 'other': _("Autre")}


def role_options():
    return {'moderate_assembly': _("Modérer l'Assemblée d'entente"), 'shared_radar': _("Vision radar partagée"),
            'shared_fleets': _("Contrôle des flottes partagées"), 'manage_finances': _("Gérer les finances"),
            MANAGE_ROLES: _("Modifier les rôles"), INVITE_MEMBER: _("Inviter un membre"), EXCLUDE_MEMBER: _("Exclure un membre")}


def _category_label(category):
    return _("Native") if category == NATIVE else founded_categories().get(category, category)


def _entente_name(entente):
    if entente.category != NATIVE:
        return entente.name
    # Seed of a sector : 4 digits of the server, 3 of its Y position, 3 of its X position
    sector = entente.native_sector
    return _("Natifs du secteur %(sector)s") % {'sector': f'{int(sector[4:7])}-{int(sector[7:10])}'}


def _role_name(role):
    return _("Membre") if role is None or role.is_default else role.name


def _clean_description(description):
    return clean_text(description, DESCRIPTION_MAX_LENGTH, _("La description doit faire au plus 5 000 caractères"), optional=True)


def _create_report(server, commandant_id, report_type, entente):
    from data.report import create_report  # Placed here to prevent circular import
    create_report(server, commandant_id, report_type, {'entente': entente.name})


########################################################################################################################
# RIGHTS


def _rights_of_row(entente, commandant_id, row):
    if entente.owner_id == commandant_id:
        return set(role_options())
    return set(row.role.options) if row and row.status == 'member' and row.role else set()


def _covers(rights, role):
    return role is None or set(role.options) <= rights


def _entente_with_right(entente_id, commandant_id, option):
    # The entente and all the rights of this commandant in it
    entente = Entente.objects.filter(id=to_id(entente_id)).exclude(category=NATIVE).first()
    if entente:
        row = EntenteMember.objects.filter(entente=entente, commandant_id=commandant_id).select_related('role').first()
        rights = _rights_of_row(entente, commandant_id, row)
        if option in rights:
            return entente, rights
    raise GameError(_("Vous n'avez pas ce droit dans cette entente"))


def _owned_entente(entente_id, owner_id):
    entente = Entente.objects.filter(id=to_id(entente_id), owner_id=owner_id).first()
    if entente is None:
        raise GameError(_("Vous n'êtes pas le propriétaire de cette entente"))
    return entente


def _ententes_answering_applications(commandant_id):
    return Entente.objects.filter(Q(owner_id=commandant_id) | Q(members__commandant_id=commandant_id, members__status='member',
                                                                members__role__options__contains=[INVITE_MEMBER]))


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
def memberships_of_commandants(server, commandant_ids):
    # {commandant id: [{'id': ..., 'name': ...}]} for the ententes they are really members of. Public, see get_entente.
    memberships = {}
    for row in EntenteMember.objects.filter(commandant_id__in=commandant_ids, status='member').select_related('entente').order_by('entente_id'):
        memberships.setdefault(row.commandant_id, []).append({'id': row.entente_id, 'name': _entente_name(row.entente)})
    return memberships


@on_server
def get_ententes(server, commandant_id):
    # The applications only count for who can answer them.
    # shortcut: loads all the ententes of the server, paginate if a server ever has hundreds of them

    statuses = dict(EntenteMember.objects.filter(commandant_id=commandant_id).values_list('entente_id', 'status'))
    answering = set(_ententes_answering_applications(commandant_id).values_list('id', flat=True))
    ententes = {'mine': [], 'invited': [], 'others': []}

    for entente in (Entente.objects.select_related('owner')
                    .annotate(nb_members=Count('members', filter=Q(members__status='member')),
                              nb_applications=Count('members', filter=Q(members__status='applicant')))
                    .order_by('-nb_members', 'name')):
        status = statuses.get(entente.id)
        ententes[{'member': 'mine', 'invited': 'invited'}.get(status, 'others')].append({
            'id': entente.id, 'name': _entente_name(entente), 'category': entente.category,
            'category_label': _category_label(entente.category),
            'owner_name': entente.owner.commandant_name if entente.owner else None,
            'nb_members': entente.nb_members, 'status': status,
            'nb_applications': entente.nb_applications if entente.id in answering else 0})
    return ententes


def _options_form(rights, checked=()):
    # The lines of the checkboxes of a role
    return [{'key': key, 'label': label, 'is_upcoming': key in UPCOMING_OPTIONS, 'is_checked': key in checked,
             'can_change': key in rights} for key, label in role_options().items()]


@on_server
def get_entente(server, entente_id, commandant_id):
    # None if it doesn't exist. The members and their role are public, the options of the roles are for the members.

    entente = Entente.objects.select_related('owner').filter(id=to_id(entente_id)).first()
    if entente is None:
        return None

    rows = list(EntenteMember.objects.filter(entente=entente).select_related('commandant', 'role')
                .order_by('datetime', 'commandant__commandant_name'))
    rows.sort(key=lambda row: row.commandant_id != entente.owner_id)
    mine = next((row for row in rows if row.commandant_id == commandant_id), None)
    rights = _rights_of_row(entente, commandant_id, mine)
    is_owner = entente.owner_id == commandant_id
    is_member = is_owner or (mine is not None and mine.status == 'member')
    is_native = entente.category == NATIVE
    can_manage_roles = MANAGE_ROLES in rights

    def person(row):
        is_row_owner = row.commandant_id == entente.owner_id
        return {'id': row.commandant_id, 'name': row.commandant.commandant_name, 'portrait': row.commandant.portrait,
                'civilisation_name': row.commandant.civilisation_name, 'datetime': row.datetime,
                'is_owner': is_row_owner, 'role_id': row.role_id,
                'role_name': _("Propriétaire") if is_row_owner else _role_name(row.role),
                'can_change_role': can_manage_roles and not is_row_owner and _covers(rights, row.role),
                'can_exclude': EXCLUDE_MEMBER in rights and not is_row_owner and row.commandant_id != commandant_id
                               and _covers(rights, row.role)}

    roles = []
    if is_member and not is_native:
        members_of_role = Count('members', filter=Q(members__status='member'))
        for role in entente.roles.annotate(nb_members=members_of_role).order_by('-is_default', 'name'):
            roles.append({
                'id': role.id, 'name': _role_name(role), 'is_default': role.is_default, 'raw_name': role.name,
                'nb_members': role.nb_members, 'can_edit': can_manage_roles and _covers(rights, role),
                'options': [label for key, label in role_options().items() if key in role.options],
                'options_form': _options_form(rights, role.options)})

    return {
        'id': entente.id, 'name': _entente_name(entente), 'is_native': is_native,
        'category_label': _category_label(entente.category), 'description': entente.description,
        'owner_name': entente.owner.commandant_name if entente.owner else None, 'creation_date': entente.creation_date,
        'status': 'member' if is_member else mine.status if mine else None, 'my_application': mine.application if mine else '',
        'is_owner': is_owner, 'is_member': is_member, 'can_apply': not is_native and mine is None and not is_owner,
        'can_invite': INVITE_MEMBER in rights, 'can_manage_roles': can_manage_roles,
        'members': [person(row) for row in rows if row.status == 'member'],
        'applications': [person(row) | {'application': row.application} for row in rows if row.status == 'applicant']
        if INVITE_MEMBER in rights else [],
        'roles': roles, 'owner_options': list(role_options().values()), 'new_role_form': _options_form(rights),
    }


@on_server
def count_pending_answers(server, commandant_id):
    # Number displayed by the menu of every page : applications to examine, invitations received
    return EntenteMember.objects.filter(Q(entente__in=_ententes_answering_applications(commandant_id), status='applicant')
                                        | Q(commandant_id=commandant_id, status='invited')).count()


@on_server
def can_create_entente(server, commandant_id):
    return Entente.objects.filter(owner_id=commandant_id).count() < MAX_OWNED_ENTENTES


########################################################################################################################
# ORDERS OF ANY COMMANDANT


@on_server
@transaction.atomic
def found_entente(server, commandant_id, name, category, description):
    # The commandant is locked until the end of the transaction : two simultaneous requests can't get around the limit
    Commandant.objects.select_for_update().get(id=commandant_id)
    if not can_create_entente(server, commandant_id):
        raise GameError(_("Vous possédez déjà le maximum de 5 ententes"))
    if category not in founded_categories():
        raise GameError(_("Ce type d'entente n'existe pas"))

    now = timezone.now()
    name = clean_text(name, NAME_MAX_LENGTH, _("Le nom doit faire entre 1 et 60 caractères"))
    try:
        with transaction.atomic():
            entente = Entente.objects.create(category=category, name=name, description=_clean_description(description),
                                             owner_id=commandant_id, creation_date=now)
    except IntegrityError:
        raise GameError(_("Ce nom est déjà pris"))
    EntenteRole.objects.create(entente=entente, is_default=True)
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
    # Also takes back an application. Nobody leaves a native entente, and an owner has to dissolve it or give it away.
    EntenteMember.objects.filter(entente_id=to_id(entente_id), commandant_id=commandant_id) \
        .exclude(entente__category=NATIVE).exclude(entente__owner_id=commandant_id).delete()


def _admit(entente, rows):
    return rows.update(status='member', role=entente.roles.get(is_default=True), datetime=timezone.now())


@on_server
@transaction.atomic
def answer_invitation(server, entente_id, commandant_id, accepted):
    invitations = EntenteMember.objects.filter(entente_id=to_id(entente_id), commandant_id=commandant_id, status='invited')
    if not invitations.exists():
        raise GameError(_("Cette invitation n'existe plus"))
    if accepted:
        _admit(Entente.objects.get(id=to_id(entente_id)), invitations)
    else:
        invitations.delete()


########################################################################################################################
# ORDERS DEPENDING ON THE OPTIONS OF A ROLE


@on_server
@transaction.atomic
def answer_application(server, entente_id, commandant_id, applicant_id, accepted):
    # Answering twice changes nothing and sends no second report
    entente = _entente_with_right(entente_id, commandant_id, INVITE_MEMBER)[0]
    applications = EntenteMember.objects.filter(entente=entente, commandant_id=to_id(applicant_id), status='applicant')
    if accepted and _admit(entente, applications):
        _create_report(server, to_id(applicant_id), 'entente_application_accepted', entente)
    elif not accepted and applications.delete()[0]:
        _create_report(server, to_id(applicant_id), 'entente_application_refused', entente)


@on_server
@transaction.atomic
def invite_to_entente(server, entente_id, commandant_id, invited_name):
    entente = _entente_with_right(entente_id, commandant_id, INVITE_MEMBER)[0]
    invited = find_commandant(invited_name)
    rows = EntenteMember.objects.filter(entente=entente, commandant=invited)
    status = rows.values_list('status', flat=True).first()

    if status == 'member':
        raise GameError(_("Ce commandant est déjà membre"))
    if status == 'applicant':  # Both sides agree
        _admit(entente, rows)
        _create_report(server, invited.id, 'entente_application_accepted', entente)
    elif status is None:
        EntenteMember.objects.create(entente=entente, commandant=invited, status='invited', datetime=timezone.now())
        _create_report(server, invited.id, 'entente_invitation', entente)


@on_server
@transaction.atomic
def exclude_member(server, entente_id, commandant_id, member_id):
    entente, rights = _entente_with_right(entente_id, commandant_id, EXCLUDE_MEMBER)
    row = EntenteMember.objects.filter(entente=entente, commandant_id=to_id(member_id), status='member').select_related('role') \
        .exclude(commandant_id__in=(commandant_id, entente.owner_id)).first()
    if row is None:
        return
    if not _covers(rights, row.role):
        raise GameError(_("Ce membre a des options que vous n'avez pas"))
    row.delete()
    _create_report(server, to_id(member_id), 'entente_member_excluded', entente)


def _clean_role_name(name):
    name = clean_text(name, ROLE_NAME_MAX_LENGTH, _("Le nom du rôle doit faire entre 1 et 40 caractères"))
    if name.lower() in RESERVED_ROLE_NAMES:
        raise GameError(_("Ce nom est réservé à un rôle par défaut"))
    return name


def _granted_options(options, rights):
    # Only the options held can be given. In a fixed order, whatever the request contains.
    return [key for key in role_options() if key in options and key in rights]


def _save_role(role):
    try:
        with transaction.atomic():
            role.save()
    except IntegrityError:
        raise GameError(_("Ce rôle existe déjà dans cette entente"))


@on_server
def create_role(server, entente_id, commandant_id, name, options):
    entente, rights = _entente_with_right(entente_id, commandant_id, MANAGE_ROLES)
    _save_role(EntenteRole(entente=entente, name=_clean_role_name(name), options=_granted_options(options, rights)))


def _role_within_reach(entente, role_id, rights):
    role = entente.roles.filter(id=to_id(role_id)).first()
    if role is None or not _covers(rights, role):
        raise GameError(_("Ce rôle a des options que vous n'avez pas"))
    return role


@on_server
def update_role(server, entente_id, commandant_id, role_id, name, options):
    entente, rights = _entente_with_right(entente_id, commandant_id, MANAGE_ROLES)
    role = _role_within_reach(entente, role_id, rights)
    if not role.is_default:  # The default role keeps its name
        role.name = _clean_role_name(name)
    role.options = _granted_options(options, rights)
    _save_role(role)


@on_server
@transaction.atomic
def delete_role(server, entente_id, commandant_id, role_id):
    # Its members go back to the default role
    entente, rights = _entente_with_right(entente_id, commandant_id, MANAGE_ROLES)
    role = _role_within_reach(entente, role_id, rights)
    if role.is_default:
        raise GameError(_("Le rôle par défaut ne peut pas être supprimé"))
    role.members.update(role=entente.roles.get(is_default=True))
    role.delete()


@on_server
def set_member_role(server, entente_id, commandant_id, member_id, role_id):
    entente, rights = _entente_with_right(entente_id, commandant_id, MANAGE_ROLES)
    role = _role_within_reach(entente, role_id, rights)
    row = EntenteMember.objects.filter(entente=entente, commandant_id=to_id(member_id), status='member').select_related('role') \
        .exclude(commandant_id=entente.owner_id).first()  # The role of owner only changes hands with transfer_ownership
    if row is None:
        raise GameError(_("Ce commandant n'est pas un membre de cette entente"))
    if not _covers(rights, row.role):
        raise GameError(_("Ce membre a des options que vous n'avez pas"))
    row.role = role
    row.save(update_fields=['role'])


########################################################################################################################
# ORDERS OF THE OWNER


@on_server
def update_entente_description(server, entente_id, owner_id, description):
    entente = _owned_entente(entente_id, owner_id)
    entente.description = _clean_description(description)
    entente.save(update_fields=['description'])


@on_server
@transaction.atomic
def transfer_ownership(server, entente_id, owner_id, new_owner_id):
    # Locked : two simultaneous transfers can't both be decided by the same owner
    entente = Entente.objects.select_for_update().filter(id=to_id(entente_id), owner_id=owner_id).first()
    if entente is None:
        raise GameError(_("Vous n'êtes pas le propriétaire de cette entente"))
    new_owner = EntenteMember.objects.filter(entente=entente, commandant_id=to_id(new_owner_id), status='member') \
        .exclude(commandant_id=owner_id).first()
    if new_owner is None:
        raise GameError(_("Ce commandant n'est pas un membre de cette entente"))

    entente.owner_id = new_owner.commandant_id
    entente.save(update_fields=['owner'])
    new_owner.role = None
    new_owner.save(update_fields=['role'])
    EntenteMember.objects.filter(entente=entente, commandant_id=owner_id).update(role=entente.roles.get(is_default=True))
    _create_report(server, new_owner.commandant_id, 'entente_ownership_received', entente)


@on_server
@transaction.atomic
def dissolve_entente(server, entente_id, owner_id):
    entente = _owned_entente(entente_id, owner_id)
    for commandant_id in EntenteMember.objects.filter(entente=entente).exclude(commandant_id=owner_id) \
            .values_list('commandant_id', flat=True):
        _create_report(server, commandant_id, 'entente_dissolved', entente)
    entente.delete()
