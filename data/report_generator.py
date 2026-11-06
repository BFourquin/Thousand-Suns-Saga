
from django.utils import timezone

from data.commandant import get_commandant
from data.user import get_user_by_id


ENTENTE_REPORTS = {
    'entente_application_accepted': {
        'fr': ("Candidature acceptée", "L'entente {entente} vous compte désormais parmi ses membres."),
        'en': ("Application accepted", "The entente {entente} now counts you among its members."),
    },
    'entente_application_refused': {
        'fr': ("Candidature refusée", "L'entente {entente} a refusé votre candidature."),
        'en': ("Application refused", "The entente {entente} refused your application."),
    },
    'entente_member_excluded': {
        'fr': ("Exclusion d'une entente", "Vous ne faites plus partie de l'entente {entente}."),
        'en': ("Excluded from an entente", "You are no longer part of the entente {entente}."),
    },
    'entente_dissolved': {
        'fr': ("Entente dissoute", "Le propriétaire de l'entente {entente} l'a dissoute."),
        'en': ("Entente dissolved", "The owner of the entente {entente} dissolved it."),
    },
    'entente_invitation': {
        'fr': ("Invitation dans une entente", "L'entente {entente} vous invite à la rejoindre : répondez depuis la page Diplomatie."),
        'en': ("Invitation to an entente", "The entente {entente} invites you to join it: answer from the Diplomacy page."),
    },
    'entente_ownership_received': {
        'fr': ("Propriété d'une entente", "La propriété de l'entente {entente} vous a été cédée."),
        'en': ("Ownership of an entente", "The ownership of the entente {entente} was given to you."),
    },
}


def generate_report(server, owner_id, report_type, args={}, sender=None, sender_image=None):

    commandant = get_commandant(server, owner_id)
    user = get_user_by_id(commandant['user'])
    lang = user['language']

    # Default values for report
    report = {
        'status': 'unread',  # 'unread' | 'read' | 'archived'
        'owner_id': owner_id,
        'category': 'other',
        'category_icon': 'fa-file-alt',
        'datetime': timezone.now(),
        'tss_calendar': timezone.now(),  # Turned into the date of the game when displayed : see the rp_date filter
        'illustration': None,
        'title': '',
        'message': '',
        'sender': sender,
        'sender_image': sender_image,
    }

    # Report template
    """
    elif report_type == 'report_type':
        report['title'] = {
            'fr': "",
            'en': "",
        }[lang]
        report['message'] = {
            'fr': "",
            'en': "",
        }[lang]
        report['category'] = 'other'
        report['category_icon'] = 'fa-file-alt'
        report['illustration'] = "images/report/command_center.png"
    """


    if report_type == 'welcome_on_TSS':
        report['title'] = {
            'fr': "Bienvenue sur Thousand Suns Saga",
            'en': "Welcome on Thousand Suns Saga",
        }[lang]
        report['message'] = {
            'fr': "TSS est encore en Alpha, de nombreuses choses sont encore à venir, merci de signaler tout problème !",
            'en': "TSS is still in Alpha, many things are still to come, please report any issues!",
        }[lang]
        report['category'] = 'other'
        report['category_icon'] = 'fa-file-alt'
        report['illustration'] = "images/report/command_center.png"

    elif report_type in ENTENTE_REPORTS:
        report['title'], message = ENTENTE_REPORTS[report_type][lang]
        report['message'] = message.format(entente=args['entente'])
        report['category'] = 'diplomacy'
        report['category_icon'] = 'fa-handshake'
        report['illustration'] = "images/report/command_center.png"


    return report
