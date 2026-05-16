import re
import string
import unicodedata

from rapidfuzz import fuzz


def normalizar_texto(texto):
    """Normaliza texto para comparar títulos de forma consistente."""
    if not texto:
        return ""

    texto = str(texto).lower().strip()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(caracter for caracter in texto if not unicodedata.combining(caracter))
    texto = texto.translate(str.maketrans("", "", string.punctuation))
    texto = "".join(caracter for caracter in texto if not unicodedata.category(caracter).startswith("P"))
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def _normalizar_doi(doi):
    doi_normalizado = str(doi or "").strip().lower()
    prefijos = [
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi:",
    ]

    for prefijo in prefijos:
        if doi_normalizado.startswith(prefijo):
            doi_normalizado = doi_normalizado.replace(prefijo, "", 1)

    return doi_normalizado.strip()


def calcular_similitud(texto1, texto2):
    """Devuelve una similitud entre 0 y 1 usando RapidFuzz."""
    texto1_normalizado = normalizar_texto(texto1)
    texto2_normalizado = normalizar_texto(texto2)

    if not texto1_normalizado or not texto2_normalizado:
        return 0.0

    return fuzz.token_sort_ratio(texto1_normalizado, texto2_normalizado) / 100


def existe_doi(df, doi):
    """Valida si un DOI ya existe en el DataFrame."""
    if df.empty or "DOI" not in df.columns:
        return False

    doi_normalizado = _normalizar_doi(doi)
    if not doi_normalizado:
        return False

    dois = df.get("DOI", "").astype(str).apply(_normalizar_doi)
    return doi_normalizado in set(dois)


def buscar_titulo_similar(df, nuevo_titulo, umbral=0.90):
    """Busca un título con similitud igual o superior al umbral indicado."""
    if df.empty or not nuevo_titulo:
        return None

    for _, fila in df.iterrows():
        titulo_existente = fila.get("Nombre del Articulo", "")
        similitud = calcular_similitud(nuevo_titulo, titulo_existente)

        if similitud >= umbral:
            return {
                "titulo": titulo_existente,
                "similitud": similitud,
            }

    return None
