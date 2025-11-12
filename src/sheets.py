import gspread
from google.oauth2.service_account import Credentials
from typing import Optional, List
from .utils import col_to_index

SCOPE = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

class SheetClient:
    def __init__(self, service_account_json: str, spreadsheet_name: Optional[str], spreadsheet_id: Optional[str]):
        creds = Credentials.from_service_account_file(service_account_json, scopes=SCOPE)
        self.gc = gspread.authorize(creds)

        if spreadsheet_id:
            self.sh = self.gc.open_by_key(spreadsheet_id)
        elif spreadsheet_name:
            self.sh = self.gc.open(spreadsheet_name)
        else:
            raise ValueError("Provide spreadsheet_name or spreadsheet_id")

    def list_worksheets(self) -> List[str]:
        return [ws.title for ws in self.sh.worksheets()]

    def worksheet(self, title: Optional[str] = None):
        if title:
            return self.sh.worksheet(title)
        return self.sh.get_worksheet(0)

    def read_rows(self, ws, start_row: int, ch_col, en_col, sv_col, header_rows: int, limit: int = 0):
        ch_i = col_to_index(ch_col)
        en_i = col_to_index(en_col)
        sv_i = col_to_index(sv_col)

        all_values = ws.get_all_values()
        rows = []
        start = max(start_row, header_rows + 1)
        end = len(all_values)
        count = 0
        for r in range(start, end + 1):
            row = all_values[r-1]
            def cell(i):
                return row[i-1] if i-1 < len(row) else ""
            ch = cell(ch_i).strip()
            en = cell(en_i).strip()
            sv = cell(sv_i).strip()
            rows.append((r, ch, en, sv))
            count += 1
            if limit and count >= limit:
                break
        return rows

    def write_cell(self, ws, row: int, col, value: str):
        i = col_to_index(col)
        ws.update_cell(row, i, value)

    def write_col_range(self, ws, col_letter: str, start_row: int, values: list[str], *, user_entered: bool = True):
        """
        Write a vertical slice using the worksheet-scoped range.
        Example: E6:E10 (NO sheet name here).
        """
        end_row = start_row + len(values) - 1
        rng = f"{col_letter}{start_row}:{col_letter}{end_row}"  # <— no ws.title here
        payload = [[v] for v in values]  # column vector
        value_input = "USER_ENTERED" if user_entered else "RAW"
        ws.update(rng, payload, value_input_option=value_input)