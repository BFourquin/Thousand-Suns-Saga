
import pylightxl as xl
from database.db_connect import databases


def load_buildings(excel_tech_path, sheet_resources_name, server_name, delete_actual_buildings):

    client = databases['TSS_' + server_name]

    if delete_actual_buildings:
        client['buildings_types'].delete_many({})
        client['districts_types'].delete_many({})

    with open(excel_tech_path, 'rb') as f:
        xldb = xl.readxl(f)


        # DISTRICTS DECLARATION
        db = client['districts_types']

        for row in xldb.ws(ws=sheet_resources_name).rows:

            if row[0] and not row[0][0] == '#':

                # Manual end of file
                if row[0] == 'END_OF_FILE':
                    break

                # Header line
                if row[0] == 'internal_name':
                    titles = row
                    continue

                # DISTRICTS DECLARATION

                # Change DB for sub-categories section
                if row[0] == '> BUILDINGS':
                    db = client['buildings_types']
                    continue

                resources_cat = {}
                for i in range(len(titles)):

                    # Boolean entries
                    if '_based' in titles[i] or '_district' in titles[i]:
                        resources_cat[titles[i]] = True if row[i] in ('True', 'true') else False
                    # Integer entries
                    if '_slots' in titles[i]:
                        resources_cat[titles[i]] = row[i] if row[i] else 0

                    # Normal entry
                    else:
                        resources_cat[titles[i]] = row[i] if row[i] != '' else None

                resources_cat.pop('', None)  # Remove empty rows

                print(resources_cat)
                db.insert_one(resources_cat)



if __name__ == '__main__':
    load_buildings(excel_tech_path='../TSS.xlsx',
                   sheet_resources_name='Buildings',
                   server_name='Alpha_test',
                   delete_actual_buildings=True)
