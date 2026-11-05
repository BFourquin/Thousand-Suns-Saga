
import pylightxl as xl
from backend.models import Technology


def load_technologies(excel_tech_path, sheet_tech_name, server_name, delete_actual_techs):

    if delete_actual_techs:
        Technology.objects.filter(server=server_name).delete()

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
                Technology.objects.create(server_id=server_name, internal_name=tech['internal_name'], data=tech)
