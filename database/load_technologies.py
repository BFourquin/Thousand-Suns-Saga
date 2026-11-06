
import ast
import pylightxl as xl
from database.schemas import on_server
from game.models import Technology


@on_server
def load_technologies(server_name, excel_tech_path, sheet_tech_name, delete_actual_techs):

    if delete_actual_techs:
        Technology.objects.all().delete()

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

                tech['price'] = ast.literal_eval(tech['price']) if tech.get('price') else {}
                if not isinstance(tech['price'], dict):
                    raise ValueError('price is not a valid python dictionary : ' + str(tech['price']) + ' | origin : ' + str(tech))

                print(row)
                Technology.objects.create(internal_name=tech['internal_name'], data=tech)
