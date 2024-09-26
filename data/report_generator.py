
from datetime import datetime

from data.commandant import get_commandant_by_object_id
from data.user import get_user_by_object_id


def generate_report(server, owner_id, report_type, args={}, sender=None, sender_image=None):

    commandant = get_commandant_by_object_id(server, owner_id)
    user = get_user_by_object_id(commandant['user_id'])
    lang = user['language']

    # Default values for report
    report = {
        'id': None,
        'status': 'unread',  # 'unread' | 'read' | 'archive'
        'owner': owner_id,
        'category': 'other',
        'category_icon': 'fa-file-alt',
        'datetime': datetime.now(),
        'tss_calendar': datetime.now(),#.strftime(),  # TODO tss_calendar
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
