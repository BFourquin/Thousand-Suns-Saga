
import pylightxl as xl
from database.schemas import on_server
from game.models import Resource, ResourceCategory, ResourceSubcategory


@on_server
def load_resources(server_name, excel_tech_path, sheet_resources_name, delete_actual_resources):

    if delete_actual_resources:
        Resource.objects.all().delete()
        ResourceCategory.objects.all().delete()
        ResourceSubcategory.objects.all().delete()

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
                resources.pop('', None)  # Remove empty rows

                print(row)
                Resource.objects.create(internal_name=resources['internal_name'], data=resources)


        # CATEGORY AND SUB-CATEGORY DECLARATION

        model = ResourceCategory

        for row in xldb.ws(ws=sheet_resources_name+'_categories').rows:

            if row[0] and not row[0][0] == '#':

                # Manual end of file
                if row[0] == 'END_OF_FILE':
                    break

                # Header line
                if row[0] == 'internal_name':
                    titles = row
                    continue

                # Change table for sub-categories section
                if row[0] == '> SUB CATEGORY':
                    model = ResourceSubcategory
                    continue

                resources_cat = {}
                for i in range(len(titles)):
                    resources_cat[titles[i]] = row[i] if row[i] != '' else None
                resources_cat.pop('', None)  # Remove empty rows

                print(row)
                model.objects.create(internal_name=resources_cat['internal_name'], data=resources_cat)
