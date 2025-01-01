
import pylightxl as xl
from database.db_connect import databases


def load_technologies(excel_tech_path, sheet_tech_name, server_name, delete_actual_techs):

    client = databases['TSS_' + server_name]
    db = client['technologies']
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

                tech = {}
                for i in range(len(titles)):
                    tech[titles[i]] = row[i] if row[i] != '' else None
                tech.pop('', None)  # Remove empty rows

                print(row)
                db.insert_one(tech)


if __name__ == '__main__':
    load_technologies(excel_tech_path='TSS.xlsx',
                      sheet_tech_name='Techs',

                      server_name='Alpha_test',
                      delete_actual_techs=True)
