from io import BytesIO

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

from services.excel_service import COLUMNAS


SPREADSHEET_ID = "1keQ5XgJu-dHpIyhcHqmNXUc6GRiw3wp8XEeh2nWddfQ"
DEFAULT_WORKSHEET_NAME = ""
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
ERROR_CONEXION = (
    "No se pudo conectar con Google Sheets. "
    "Verifica las credenciales o permisos del archivo."
)


class GoogleSheetsConnectionError(Exception):
    """Error controlado para fallos de conexión o permisos de Google Sheets."""


def _get_service_account_info():
    """Obtiene credenciales desde Streamlit secrets sin guardarlas en código."""
    try:
        if "gcp_service_account" in st.secrets:
            return dict(st.secrets["gcp_service_account"])
        if "google_service_account" in st.secrets:
            return dict(st.secrets["google_service_account"])
    except Exception as error:
        raise GoogleSheetsConnectionError(ERROR_CONEXION) from error

    raise GoogleSheetsConnectionError(ERROR_CONEXION)


def _get_spreadsheet_id():
    try:
        return st.secrets.get("google_sheets", {}).get("spreadsheet_id", SPREADSHEET_ID)
    except Exception:
        return SPREADSHEET_ID


def _get_worksheet_name():
    try:
        return st.secrets.get("google_sheets", {}).get(
            "worksheet_name", DEFAULT_WORKSHEET_NAME
        ).strip()
    except Exception:
        return DEFAULT_WORKSHEET_NAME


def _get_client():
    try:
        credentials_info = _get_service_account_info()
        credentials = Credentials.from_service_account_info(
            credentials_info,
            scopes=SCOPES,
        )
        return gspread.authorize(credentials)
    except GoogleSheetsConnectionError:
        raise
    except Exception as error:
        raise GoogleSheetsConnectionError(ERROR_CONEXION) from error


def _get_worksheet():
    try:
        client = _get_client()
        spreadsheet = client.open_by_key(_get_spreadsheet_id())
        worksheet_name = _get_worksheet_name()

        if worksheet_name:
            try:
                worksheet = spreadsheet.worksheet(worksheet_name)
            except gspread.WorksheetNotFound:
                worksheet = spreadsheet.add_worksheet(
                    title=worksheet_name,
                    rows=1000,
                    cols=len(COLUMNAS),
                )
        else:
            worksheet = spreadsheet.sheet1

        _ensure_headers(worksheet)
        return worksheet
    except GoogleSheetsConnectionError:
        raise
    except Exception as error:
        raise GoogleSheetsConnectionError(ERROR_CONEXION) from error


def _ensure_headers(worksheet):
    values = worksheet.get_all_values()

    if not values:
        worksheet.update(values=[COLUMNAS], range_name="A1")
        return

    headers = values[0]
    if headers[: len(COLUMNAS)] != COLUMNAS:
        worksheet.update(values=[COLUMNAS], range_name="A1")


def _article_to_row(article_data):
    return [article_data.get(columna, "") for columna in COLUMNAS]


def _rows_to_dataframe(rows):
    registros = []
    for row in rows:
        row = (row + [""] * len(COLUMNAS))[: len(COLUMNAS)]
        registros.append(dict(zip(COLUMNAS, row)))

    df = pd.DataFrame(registros, columns=COLUMNAS)
    return df.fillna("")


def get_all_articles():
    """Devuelve todos los artículos como lista de diccionarios."""
    worksheet = _get_worksheet()
    values = worksheet.get_all_values()

    if len(values) <= 1:
        return []

    return _rows_to_dataframe(values[1:]).to_dict("records")


def sheet_to_dataframe():
    """Convierte Google Sheets en un DataFrame de pandas."""
    return pd.DataFrame(get_all_articles(), columns=COLUMNAS).fillna("")


def add_article(article_data):
    """Agrega un nuevo artículo a Google Sheets."""
    worksheet = _get_worksheet()
    worksheet.append_row(_article_to_row(article_data), value_input_option="USER_ENTERED")
    return True


def add_articles(articles_data):
    """Agrega varios artículos a Google Sheets en una sola operación."""
    worksheet = _get_worksheet()
    rows = [_article_to_row(article) for article in articles_data]

    if not rows:
        return True

    worksheet.append_rows(rows, value_input_option="USER_ENTERED")
    return True


def update_article(row_index, article_data):
    """Actualiza una fila por número real de fila en Google Sheets."""
    worksheet = _get_worksheet()
    row_index = int(row_index)

    if row_index < 2:
        raise ValueError("row_index debe ser 2 o mayor porque la fila 1 contiene encabezados.")

    end_column = chr(ord("A") + len(COLUMNAS) - 1)
    worksheet.update(
        values=[_article_to_row(article_data)],
        range_name=f"A{row_index}:{end_column}{row_index}",
        value_input_option="USER_ENTERED",
    )
    return True


def delete_article(row_index):
    """Elimina una fila por número real de fila en Google Sheets."""
    worksheet = _get_worksheet()
    row_index = int(row_index)

    if row_index < 2:
        raise ValueError("row_index debe ser 2 o mayor porque la fila 1 contiene encabezados.")

    worksheet.delete_rows(row_index)
    return True


def dataframe_to_csv(df=None):
    """Devuelve un CSV en bytes desde Google Sheets o desde el DataFrame recibido."""
    if df is None:
        df = sheet_to_dataframe()

    return df.to_csv(index=False).encode("utf-8-sig")


def dataframe_to_excel(df=None):
    """Devuelve un archivo Excel en memoria desde Google Sheets o desde un DataFrame."""
    if df is None:
        df = sheet_to_dataframe()

    buffer = BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    return buffer
