from pathlib import Path
import shutil
from datetime import datetime
from io import BytesIO

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
BACKUP_DIR = DATA_DIR / "backups"
EXCEL_PATH = DATA_DIR / "articulos.xlsx"
CSV_EXPORT_PATH = DATA_DIR / "articulos.csv"

COLUMNAS = [
    "Categoria",
    "Nombre del Articulo",
    "Autor(es)",
    "Pais",
    "Año publicacion",
    "Cantidad de citas",
    "Tipo documento",
    "DOI",
    "Revista/Conferencia",
    "Volumen",
    "Numero",
    "Paginas",
    "URL",
    "Editorial",
    "Palabras Indexadas",
    "Resumen 3 lineas",
    "Justificación categoría",
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


def normalizar_dataframe(df):
    """Asegura columnas, orden y valores vacíos consistentes para almacenamiento local."""
    df = df.copy()

    for columna in COLUMNAS:
        if columna not in df.columns:
            df[columna] = ""

    return df[COLUMNAS].fillna("")


def cargar_articulos():
    """Carga los artículos desde Excel como DataFrame."""
    try:
        crear_excel_si_no_existe()
        df = pd.read_excel(EXCEL_PATH, engine="openpyxl")

        return normalizar_dataframe(df)
    except Exception:
        return pd.DataFrame(columns=COLUMNAS)


def crear_backup_excel():
    """Crea una copia de seguridad del Excel antes de sobrescribirlo."""
    try:
        if not EXCEL_PATH.exists():
            return None

        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"articulos_backup_{fecha}.xlsx"
        shutil.copy2(EXCEL_PATH, backup_path)
        return backup_path
    except Exception:
        return None


def guardar_articulos(df, crear_backup=True):
    """Guarda el DataFrame completo en el Excel local."""
    try:
        crear_excel_si_no_existe()
        if crear_backup:
            crear_backup_excel()

        df = normalizar_dataframe(df)
        df.to_excel(EXCEL_PATH, index=False, engine="openpyxl")
        df.to_csv(CSV_EXPORT_PATH, index=False, encoding="utf-8-sig")
        return True
    except PermissionError:
        return False
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


def agregar_articulos(nuevos_articulos):
    """Agrega varios artículos al Excel de respaldo en una sola operación."""
    try:
        df = cargar_articulos()
        nuevos_df = pd.DataFrame(nuevos_articulos, columns=COLUMNAS)
        df = pd.concat([df, nuevos_df], ignore_index=True)
        return guardar_articulos(df)
    except Exception:
        return False


def dataframe_to_csv(df):
    """Convierte un DataFrame filtrado en CSV descargable."""
    return normalizar_dataframe(df).to_csv(index=False).encode("utf-8-sig")


def dataframe_to_excel(df):
    """Convierte un DataFrame filtrado en Excel descargable."""
    buffer = BytesIO()
    normalizar_dataframe(df).to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    return buffer
