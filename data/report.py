

import datetime
from random import randint
from bson.objectid import ObjectId

from database.db_connect import databases
from data.report_generator import generate_report
from data.commandant import get_commandant_by_object_id, push_param_commandant, pull_param_commandant




def create_report(server, owner_id, report_type, args={}, sender=None, sender_image=None):

    try:
        client = databases['TSS_' + server]
        db = client['report']

        report = generate_report(server, owner_id, report_type, args, sender, sender_image)

        result = db.insert_one(report)
        id = result.inserted_id
        db.update_one({"_id": id}, {"$set": {'id': id}})  # Add id field (django template can't read '_id')

        # Add to commandant reports list
        push_param_commandant(server, owner_id, 'reports', id)



    except Exception as e:
        # TODO logs wrong reports
        raise e
    #    return e


def get_report_by_object_id(server, _id):
    client = databases['TSS_' + server]
    db = client['report']
    return db.find_one({'_id': ObjectId(_id)})


def get_commandant_reports(server, commandant_id, filter_status=None, filter_category=None, search_text=None):

    client = databases['TSS_' + server]
    db = client['report']

    reports_id_list = get_commandant_by_object_id(server, commandant_id)['reports']
    reports_list = list(db.find({'_id': {'$in': reports_id_list}}))
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



def change_report_status(server, report_id, status):
    client = databases['TSS_' + server]
    db = client['report']
    db.update_one({"_id": ObjectId(report_id)}, {"$set": {'status': status}})


def delete_report(server, report_id):

    client = databases['TSS_' + server]
    db = client['report']

    report = get_report_by_object_id(server, report_id)

    # Remove reference from the owning commandant's reports list
    commandant_id = report['owner']
    pull_param_commandant(server, commandant_id, 'reports', report_id)

    db.delete_one({"_id": ObjectId(report_id)})


########################################################################################################################
#

def unread_reports_counting(server, owner_id, reports_list=None):
    # Return a dict of the number of unread reports by category
    # nb_unread_reports = {'all': 5, 'space_combat: 2, ...}

    # Get reports_list from parameter if possible, preventing duplicate big db query
    if reports_list is None:
        reports_list = get_commandant_reports(server, owner_id)

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


