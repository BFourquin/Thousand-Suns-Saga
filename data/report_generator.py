
from django.utils import timezone

from data.commandant import get_commandant
from data.user import get_user_by_id


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
        'tss_calendar': timezone.now(),#.strftime(),  # TODO tss_calendar
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



    return report
