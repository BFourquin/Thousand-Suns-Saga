
from django.db import transaction

from backend.models import Report, to_id
from data.report_generator import generate_report
from data.commandant import update_commandant




@transaction.atomic
def create_report(server, owner_id, report_type, args={}, sender=None, sender_image=None):

    Report.objects.create(**generate_report(server, owner_id, report_type, args, sender, sender_image))

    # Recount unread reports
    update_nb_unread_reports(server, owner_id)


def get_report(server, id, owner_id):
    report = Report.objects.filter(id=to_id(id), owner=owner_id).first()
    return report.as_dict() if report else None


def get_commandant_reports(server, commandant_id, filter_status=None, filter_category=None, search_text=None):

    reports_list = [report.as_dict() for report in Report.objects.filter(owner=commandant_id).order_by('id')]
    unread_reports_count = unread_reports_counting(server, commandant_id, reports_list)

    # Filters and search

    if filter_category and filter_category != 'all':
        reports_list_unsorted, reports_list = reports_list, []

        for report in reports_list_unsorted:
            if report['category'] == filter_category:
                reports_list.append(report)

    if filter_status and filter_status != 'all':
        reports_list_unsorted, reports_list = reports_list, []

        for report in reports_list_unsorted:
            if filter_status == 'not_archived' and report['status'] != 'archived':
                reports_list.append(report)
            elif report['status'] == filter_status:
                reports_list.append(report)

    if search_text:
        reports_list_unsorted, reports_list = reports_list, []
        for report in reports_list_unsorted:
            for val in report.values():
                if isinstance(val, str) and search_text in val:
                    reports_list.append(report)
                    break

    return reports_list, unread_reports_count



def change_report_status(server, report_id, owner_id, status):
    Report.objects.filter(id=to_id(report_id), owner=owner_id).update(status=status)


def delete_report(server, report_id, owner_id):
    Report.objects.filter(id=to_id(report_id), owner=owner_id).delete()


########################################################################################################################
#

def mark_all_reports_as_read(server, commandant_id, category=None):

    reports = get_commandant_reports(server, commandant_id, filter_status='unread', filter_category=category)[0]
    for report in reports:
        change_report_status(server, report['id'], commandant_id, 'read')


def unread_reports_counting(server, commandant_id, reports_list=None):
    # Return a dict of the number of unread reports by category
    # nb_unread_reports = {'all': 5, 'space_combat: 2, ...}

    # Get reports_list from parameter if possible, preventing duplicate big db query
    if reports_list is None:
        reports_list = get_commandant_reports(server, commandant_id)

    nb_unread_reports = {'all': 0}
    for report in reports_list:
        if report['status'] == 'unread':

            # All categories
            nb_unread_reports['all'] += 1

            # Specific category
            category = report['category']
            if category in nb_unread_reports:
                nb_unread_reports[category] += 1
            else:
                nb_unread_reports[category] = 1

    return nb_unread_reports


def update_nb_unread_reports(server, commandant_id):
    nb_unread_reports = Report.objects.filter(owner=commandant_id, status='unread').count()
    update_commandant(server, commandant_id, 'nb_unread_reports', nb_unread_reports)
