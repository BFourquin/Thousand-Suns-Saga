
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q

from game.models import Report, to_id
from database.schemas import on_server
from data.report_generator import generate_report
from data.commandant import update_commandant

REPORTS_PER_PAGE = 5




@on_server
@transaction.atomic
def create_report(server, owner_id, report_type, args={}, sender=None, sender_image=None):

    Report.objects.create(**generate_report(server, owner_id, report_type, args, sender, sender_image))

    # Recount unread reports
    update_nb_unread_reports(server, owner_id)


@on_server
def get_report(server, id, owner_id):
    report = Report.objects.filter(id=to_id(id), owner=owner_id).first()
    return report.as_dict() if report else None


@on_server
def get_commandant_reports(server, commandant_id, page=1, filter_status=None, filter_category=None, search_text=None):
    # The asked page of the reports, the most recent first, and the unread ones by category

    reports = Report.objects.filter(owner=commandant_id)

    if filter_category and filter_category != 'all':
        reports = reports.filter(category=filter_category)

    if filter_status == 'not_archived':
        reports = reports.exclude(status='archived')
    elif filter_status and filter_status != 'all':
        reports = reports.filter(status=filter_status)

    if search_text:
        reports = reports.filter(Q(title__icontains=search_text) | Q(message__icontains=search_text) | Q(sender__icontains=search_text))

    page = Paginator(reports.order_by('-id'), REPORTS_PER_PAGE).get_page(page)  # TODO report per page in user settings
    page.object_list = [report.as_dict() for report in page.object_list]
    return page, unread_reports_counting(server, commandant_id)



@on_server
def change_report_status(server, report_id, owner_id, status):
    Report.objects.filter(id=to_id(report_id), owner=owner_id).update(status=status)


@on_server
def delete_report(server, report_id, owner_id):
    Report.objects.filter(id=to_id(report_id), owner=owner_id).delete()


########################################################################################################################
#

@on_server
def mark_all_reports_as_read(server, commandant_id, category=None):
    reports = Report.objects.filter(owner=commandant_id, status='unread')
    if category and category != 'all':
        reports = reports.filter(category=category)
    reports.update(status='read')


@on_server
def unread_reports_counting(server, commandant_id):
    # nb_unread_reports = {'all': 5, 'space_combat': 2, ...}
    unread = Report.objects.filter(owner=commandant_id, status='unread').order_by()
    by_category = dict(unread.values_list('category').annotate(Count('id')))
    return by_category | {'all': sum(by_category.values())}


@on_server
def update_nb_unread_reports(server, commandant_id):
    nb_unread_reports = Report.objects.filter(owner=commandant_id, status='unread').count()
    update_commandant(server, commandant_id, 'nb_unread_reports', nb_unread_reports)
