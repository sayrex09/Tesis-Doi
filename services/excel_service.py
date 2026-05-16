from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
EXCEL_PATH = DATA_DIR / "articulos.xlsx"

COLUMNAS = [
    "Categoria",
    "Nombre del Articulo",
    "Autor(es)",
    "Pais",
    "Año publicacion",
    "Cantidad de citas",
    "Tipo documento",
    "DOI",
    "Palabras Indexadas",
    "Resumen 3 lineas",
]


def obtener_columnas():
    """Devuelve las columnas oficiales del archivo Excel."""
    return COLUMNAS.copy()


def crear_excel_si_no_existe():
    """Crea el archivo Excel con sus columnas si todavía no existe."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        if not EXCEL_PATH.exists():
            df = pd.DataFrame(columns=COLUMNAS)
            df.to_excel(EXCEL_PATH, index=False, engine="openpyxl")
            return

        df = pd.read_excel(EXCEL_PATH, engine="openpyxl")
        columnas_faltantes = [col for col in COLUMNAS if col not in df.columns]

        if df.empty and list(df.columns) != COLUMNAS:
            df = pd.DataFrame(columns=COLUMNAS)
            df.to_excel(EXCEL_PATH, index=False, engine="openpyxl")
            return

        if columnas_faltantes:
            for columna in columnas_faltantes:
                df[columna] = ""
            df = df[COLUMNAS]
            df.to_excel(EXCEL_PATH, index=False, engine="openpyxl")
    except Exception as error:
        raise RuntimeError(f"No se pudo crear o preparar el Excel: {error}") from error


def cargar_articulos():
    """Carga los artículos desde Excel como DataFrame."""
    try:
        crear_excel_si_no_existe()
        df = pd.read_excel(EXCEL_PATH, engine="openpyxl")

        for columna in COLUMNAS:
            if columna not in df.columns:
                df[columna] = ""

        return df[COLUMNAS].fillna("")
    except Exception:
        return pd.DataFrame(columns=COLUMNAS)


def guardar_articulos(df):
    """Guarda el DataFrame completo en el Excel local."""
    try:
        crear_excel_si_no_existe()
        df = df.copy()

        for columna in COLUMNAS:
            if columna not in df.columns:
                df[columna] = ""

        df = df[COLUMNAS]
        df.to_excel(EXCEL_PATH, index=False, engine="openpyxl")
        return True
    except Exception:
        return False


def agregar_articulo(nuevo_articulo):
    """Agrega un artículo al Excel y devuelve True si se guardó."""
    try:
        df = cargar_articulos()
        nuevo_df = pd.DataFrame([nuevo_articulo], columns=COLUMNAS)
        df = pd.concat([df, nuevo_df], ignore_index=True)
        return guardar_articulos(df)
    except Exception:
        return False
