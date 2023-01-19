from database.load_technologies import load_technologies

load_technologies(excel_tech_path='..\\TSS.xlsx',
                  sheet_tech_name='Techs',

                  server_name='Alpha',
                  delete_actual_techs=True)

