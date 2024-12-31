
import pylightxl as xl
from database.db_connect import databases


def load_resources(excel_tech_path, sheet_resources_name, server_name, delete_actual_resources):

    client = databases['TSS_' + server_name]


    db = client['resources']
    if delete_actual_resources:
        db.delete_many({})
        client['resources_categories'].delete_many({})
        client['resources_subcategories'].delete_many({})

    with open(excel_tech_path, 'rb') as f:
        xldb = xl.readxl(f)


        # INDIVIDUAL RESOURCES DECLARATION

        for row in xldb.ws(ws=sheet_resources_name).rows:

            if row[0] and not row[0][0] == '#':

                # Manual end of file
                if row[0] == 'END_OF_FILE':
                    break

                # Header line
                if row[0] == 'internal_name':
                    titles = row
                    continue

                resources = {}
                for i in range(len(titles)):
                    resources[titles[i]] = row[i] if row[i] != '' else None

                print(row)
                db.insert_one(resources)


        # CATEGORY AND SUB-CATEGORY DECLARATION

        db = client['resources_categories']

        for row in xldb.ws(ws=sheet_resources_name+'_categories').rows:

            if row[0] and not row[0][0] == '#':

                # Manual end of file
                if row[0] == 'END_OF_FILE':
                    break

                # Header line
                if row[0] == 'internal_name':
                    titles = row
                    continue

                # Change DB for sub-categories section
                if row[0] == '> SUB CATEGORY':
                    db = client['resources_subcategories']
                    continue

                resources_cat = {}
                for i in range(len(titles)):
                    resources_cat[titles[i]] = row[i] if row[i] != '' else None

                print(row)
                db.insert_one(resources_cat)



if __name__ == '__main__':
    load_resources(excel_tech_path='../TSS.xlsx',
                   sheet_resources_name='Resources',

                   server_name='Alpha_test',
                   delete_actual_resources=True)
