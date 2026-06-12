"""
Storage layer.

Two interchangeable backends behind one interface:

  * GoogleSheetStore  - a Google Sheet accessed via a service account (gspread).
                        Default backend; works on Streamlit Community Cloud.
  * LocalExcelStore   - a plain .xlsx on disk (openpyxl). Works out of the box;
                        ideal for development and single-machine use.

Both expose the same methods, so app.py never needs to know which is active.
"""
from __future__ import annotations

import datetime as dt
import uuid
from abc import ABC, abstractmethod

import pandas as pd

import config as C


def now_iso() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def new_eval_id() -> str:
    return uuid.uuid4().hex[:12]


def blank_record() -> dict:
    return {col: None for col in C.EVAL_COLUMNS}


# --------------------------------------------------------------------------- #
# Interface
# --------------------------------------------------------------------------- #
class EvalStore(ABC):
    backend_name = "abstract"

    @abstractmethod
    def read_all(self) -> pd.DataFrame:
        """Return all evaluations as a DataFrame with columns == C.EVAL_COLUMNS."""

    @abstractmethod
    def add(self, record: dict) -> None:
        """Append one evaluation row."""

    @abstractmethod
    def update(self, eval_id: str, changes: dict) -> None:
        """Update fields of the row with the given eval_id."""

    # convenience -----------------------------------------------------------
    def get(self, eval_id: str) -> dict | None:
        df = self.read_all()
        m = df[df["eval_id"] == eval_id]
        return None if m.empty else m.iloc[0].to_dict()


# --------------------------------------------------------------------------- #
# Local Excel
# --------------------------------------------------------------------------- #
class LocalExcelStore(EvalStore):
    backend_name = "local Excel"

    def __init__(self, path: str):
        self.path = path
        self._ensure()

    def _ensure(self):
        import os
        from openpyxl import Workbook

        if not os.path.exists(self.path):
            wb = Workbook()
            ws = wb.active
            ws.title = C.EVAL_SHEET
            ws.append(C.EVAL_COLUMNS)
            wb.save(self.path)

    def read_all(self) -> pd.DataFrame:
        try:
            df = pd.read_excel(self.path, sheet_name=C.EVAL_SHEET, dtype=object)
        except Exception:
            df = pd.DataFrame(columns=C.EVAL_COLUMNS)
        for col in C.EVAL_COLUMNS:
            if col not in df.columns:
                df[col] = None
        return df[C.EVAL_COLUMNS]

    def _write_all(self, df: pd.DataFrame):
        with pd.ExcelWriter(self.path, engine="openpyxl", mode="w") as xw:
            df[C.EVAL_COLUMNS].to_excel(xw, sheet_name=C.EVAL_SHEET, index=False)

    def add(self, record: dict) -> None:
        df = self.read_all()
        row = blank_record()
        row.update({k: v for k, v in record.items() if k in row})
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        self._write_all(df)

    def update(self, eval_id: str, changes: dict) -> None:
        df = self.read_all()
        idx = df.index[df["eval_id"] == eval_id]
        if len(idx) == 0:
            raise KeyError(f"eval_id {eval_id} not found")
        for k, v in changes.items():
            if k in df.columns:
                df.loc[idx, k] = v
        self._write_all(df)


# --------------------------------------------------------------------------- #
# Google Sheets (via gspread + a service account)
# --------------------------------------------------------------------------- #
class GoogleSheetStore(EvalStore):
    """
    Stores evaluations in a Google Sheet, accessed with a Google Cloud service
    account. This is the lowest-friction shared backend and works directly from
    Streamlit Community Cloud: it is a remote store, so it is unaffected by the
    Cloud's ephemeral filesystem.

    Setup (see README):
      1. Create a service account, enable the Google Sheets API, download the
         JSON key.
      2. Create a Sheet and *share it* with the service account's client_email.
      3. Put the JSON fields under [gcp_service_account] and the sheet id under
         [gsheets] in secrets.

    The header row (and extra columns, since default sheets have only 26) is
    created automatically on first use.
    """

    backend_name = "Google Sheets"
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

    def __init__(self, sa_info: dict, spreadsheet_id: str = "",
                 spreadsheet_url: str = "", worksheet: str = "Evaluations",
                 _ws=None):
        self.worksheet_name = worksheet
        self.ws = _ws if _ws is not None else self._connect(
            sa_info, spreadsheet_id, spreadsheet_url, worksheet
        )
        self._ensure_header()

    # -- connection ---------------------------------------------------------
    def _connect(self, sa_info, spreadsheet_id, spreadsheet_url, worksheet):
        import gspread
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_info(dict(sa_info), scopes=self.SCOPES)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(spreadsheet_id) if spreadsheet_id else gc.open_by_url(spreadsheet_url)
        try:
            return sh.worksheet(worksheet)
        except gspread.WorksheetNotFound:
            return sh.add_worksheet(title=worksheet, rows=200, cols=len(C.EVAL_COLUMNS))

    # -- helpers ------------------------------------------------------------
    def _ncols(self) -> int:
        return len(C.EVAL_COLUMNS)

    def _row_range(self, row: int) -> str:
        from gspread.utils import rowcol_to_a1
        return f"{rowcol_to_a1(row, 1)}:{rowcol_to_a1(row, self._ncols())}"

    def _ensure_header(self):
        try:
            if self.ws.col_count < self._ncols():
                self.ws.resize(cols=self._ncols())
        except Exception:
            pass
        header = self.ws.row_values(1)
        if header[: self._ncols()] != C.EVAL_COLUMNS:
            cells = self.ws.range(self._row_range(1))
            for cell, val in zip(cells, C.EVAL_COLUMNS):
                cell.value = val
            self.ws.update_cells(cells, value_input_option="RAW")

    @staticmethod
    def _clean(v):
        if v is None:
            return ""
        try:
            if pd.isna(v):
                return ""
        except (TypeError, ValueError):
            pass
        return v

    # -- interface ----------------------------------------------------------
    def read_all(self) -> pd.DataFrame:
        values = self.ws.get_all_values()
        if not values:
            return pd.DataFrame(columns=C.EVAL_COLUMNS)
        header, rows = values[0], values[1:]
        n = len(header)
        rows = [r + [""] * (n - len(r)) for r in rows]
        df = pd.DataFrame(rows, columns=header)
        for col in C.EVAL_COLUMNS:
            if col not in df.columns:
                df[col] = ""
        return df[C.EVAL_COLUMNS]

    def add(self, record: dict) -> None:
        row = blank_record()
        row.update({k: v for k, v in record.items() if k in row})
        values = [self._clean(row[c]) for c in C.EVAL_COLUMNS]
        self.ws.append_row(values, value_input_option="RAW")

    def update(self, eval_id: str, changes: dict) -> None:
        ids = self.ws.col_values(1)            # column A incl. header
        try:
            pos = ids.index(eval_id)
        except ValueError:
            raise KeyError(f"eval_id {eval_id} not found")
        sheet_row = pos + 1                     # 1-indexed
        current = self.ws.row_values(sheet_row)
        current += [""] * (self._ncols() - len(current))
        merged = dict(zip(C.EVAL_COLUMNS, current))
        merged.update({k: v for k, v in changes.items() if k in merged})
        cells = self.ws.range(self._row_range(sheet_row))
        for cell, col in zip(cells, C.EVAL_COLUMNS):
            cell.value = self._clean(merged[col])
        self.ws.update_cells(cells, value_input_option="RAW")


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
def make_store_from_secrets(secrets) -> EvalStore:
    """
    Build a store from Streamlit secrets.
    backend = "google"  -> GoogleSheetStore (default)
    backend = "local"   -> LocalExcelStore (dev / offline)
    """
    backend = "google"
    try:
        backend = secrets.get("storage", {}).get("backend", "google")
    except Exception:
        backend = "google"

    if backend == "google":
        gs = secrets["gsheets"]
        return GoogleSheetStore(
            sa_info=secrets["gcp_service_account"],
            spreadsheet_id=gs.get("spreadsheet_id", ""),
            spreadsheet_url=gs.get("spreadsheet_url", ""),
            worksheet=gs.get("worksheet", "Evaluations"),
        )

    path = "evaluations.xlsx"
    try:
        path = secrets.get("storage", {}).get("local_path", path)
    except Exception:
        pass
    return LocalExcelStore(path)
