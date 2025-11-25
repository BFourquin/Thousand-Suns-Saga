
import ast
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

                districts_cat = {}
                for i in range(len(titles)):

                    # Boolean entries
                    if '_based' in titles[i] or '_district' in titles[i]:
                        districts_cat[titles[i]] = True if row[i] in ('True', 'true') else False
                    # Integer entries
                    elif '_slots' in titles[i]:
                        districts_cat[titles[i]] = row[i] if row[i] else 0
                    # Dictionary entries
                    elif titles[i] in ('build_cost', 'maintenance'):
                        try :
                            districts_cat[titles[i]] = ast.literal_eval(row[i]) if row[i] else {}
                        except ValueError:
                            raise ValueError(titles[i] + ' is not a valid python dictionary : ' + str(row[i]) + ' | origin : ' + str(districts_cat))
                        if not isinstance(districts_cat[titles[i]], dict):
                            raise ValueError(titles[i] + ' is not a valid python dictionary : ' + str(row[i]) + ' | origin : ' + str(districts_cat))

                    # Normal entry
                    else:
                        districts_cat[titles[i]] = row[i] if row[i] != '' else None

                districts_cat.pop('', None)  # Remove empty rows

                print(districts_cat)
                db.insert_one(districts_cat)



if __name__ == '__main__':
    load_buildings(excel_tech_path='../TSS_boardgame.xlsx',
                   sheet_resources_name='Buildings',
                   server_name='Alpha_Boardgame',
                   delete_actual_buildings=True)
