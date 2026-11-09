import gspread
from oauth2client.service_account import ServiceAccountCredentials

class GoogleSheetManager:
    def __init__(self, credentials_path):
        self.credentials_path = credentials_path
        self.client = None  # El cliente se inicializará al autenticar

    def autenticar(self):
        try:
            scope = ['https://spreadsheets.google.com/feeds', 
                     'https://www.googleapis.com/auth/drive']
            creds = ServiceAccountCredentials.from_json_keyfile_name(self.credentials_path, scope)
            self.client = gspread.authorize(creds)
            return True
        except Exception as e:
            print(f"Ocurrió un error al autenticar: {e}")
            return False

    def abrir_sheet(self, sheetId, sheet_name):
        if not self.client:
            print("El cliente no está autenticado. Debes autenticar primero.")
            return None

        try:
            sheet = self.client.open_by_key(sheetId).worksheet(sheet_name)
            return sheet
        except Exception as e:
            print(f"Ocurrió un error al abrir la hoja: {e}")
            return None
