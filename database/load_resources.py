
import pylightxl as xl
from database.db_connect import databases


def load_resources(excel_tech_path, sheet_tech_name, server_name, delete_actual_techs):

    client = databases['TSS_' + server_name]
    db = client['resources']
    if delete_actual_techs:
        db.delete_many({})

    with open(excel_tech_path, 'rb') as f:
        xldb = xl.readxl(f, ws=sheet_tech_name)

        for row in xldb.ws(ws=sheet_tech_name).rows:

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


if __name__ == '__main__':
    load_resources(excel_tech_path='../TSS.xlsx',
                      sheet_tech_name='Resources',

                      server_name='Alpha_test',
                      delete_actual_techs=True)
