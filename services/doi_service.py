import re
from html import unescape
from urllib.parse import quote, unquote

import requests


DOI_REGEX = re.compile(r"10\.\d{4,9}/\S+", re.IGNORECASE)
HEADERS = {
    "User-Agent": "GestorArticulosDOI/1.0 (mailto:sin-correo-configurado@example.com)"
}
TIMEOUT_SEGUNDOS = 12


def limpiar_doi(doi):
    """Normaliza un DOI ingresado como texto o URL."""
    if not doi:
        return ""

    doi_limpio = unquote(str(doi)).strip()
    doi_limpio = doi_limpio.replace("\u200b", "")
    doi_limpio = re.sub(r"\s+", "", doi_limpio)
    doi_limpio = doi_limpio.strip("<>()[]{}\"'")
    doi_comparacion = doi_limpio.lower()
    prefijos = [
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi.org/",
        "dx.doi.org/",
        "urn:doi:",
        "doi:",
    ]

    for prefijo in prefijos:
        if doi_comparacion.startswith(prefijo):
            doi_limpio = doi_limpio[len(prefijo) :]
            break

    coincidencia = DOI_REGEX.search(doi_limpio)
    if coincidencia:
        doi_limpio = coincidencia.group(0)

    doi_limpio = doi_limpio.split("?")[0].split("#")[0]
    return doi_limpio.strip().strip(".,;:)]}>\"'")


def doi_es_valido(doi):
    """Valida si el texto tiene forma de DOI."""
    doi_limpio = limpiar_doi(doi)
    return bool(DOI_REGEX.fullmatch(doi_limpio))


def _formatear_autores(autores):
    nombres = []
    for autor in autores or []:
        nombre = autor.get("given", "")
        apellido = autor.get("family", "")
        nombre_completo = f"{nombre} {apellido}".strip()
        if nombre_completo:
            nombres.append(nombre_completo)
    return ", ".join(nombres)


def _limpiar_html(texto):
    if not texto:
        return ""
    texto = re.sub(r"<[^>]+>", " ", str(texto))
    texto = unescape(texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def _resumen_corto(texto, max_caracteres=700):
    texto_limpio = _limpiar_html(texto)
    if not texto_limpio:
        return ""

    oraciones = re.split(r"(?<=[.!?])\s+", texto_limpio)
    resumen = " ".join(oraciones[:3]).strip()

    if len(resumen) > max_caracteres:
        resumen = resumen[:max_caracteres].rsplit(" ", 1)[0].strip() + "..."

    return resumen


def _obtener_anio_crossref(mensaje):
    fechas_posibles = [
        mensaje.get("published-print"),
        mensaje.get("published-online"),
        mensaje.get("published"),
        mensaje.get("issued"),
    ]

    for fecha in fechas_posibles:
        partes = fecha.get("date-parts", []) if fecha else []
        if partes and partes[0]:
            return partes[0][0]

    return ""


def buscar_en_crossref(doi):
    """Consulta Crossref y devuelve datos bibliográficos básicos."""
    datos_vacios = {
        "Nombre del Articulo": "",
        "Autor(es)": "",
        "Año publicacion": "",
        "Tipo documento": "",
        "DOI": limpiar_doi(doi),
        "Resumen 3 lineas": "",
        "_encontrado": False,
        "_mensaje": "Crossref no devolvió datos.",
    }

    doi_limpio = limpiar_doi(doi)
    if not doi_limpio:
        datos_vacios["_mensaje"] = "Ingresa un DOI válido para consultar Crossref."
        return datos_vacios

    try:
        doi_codificado = quote(doi_limpio, safe="")
        url = f"https://api.crossref.org/works/{doi_codificado}"
        respuesta = requests.get(url, headers=HEADERS, timeout=TIMEOUT_SEGUNDOS)

        if respuesta.status_code == 404:
            return datos_vacios

        respuesta.raise_for_status()
        mensaje = respuesta.json().get("message", {})

        titulos = mensaje.get("title") or []
        return {
            "Nombre del Articulo": titulos[0] if titulos else "",
            "Autor(es)": _formatear_autores(mensaje.get("author", [])),
            "Año publicacion": _obtener_anio_crossref(mensaje),
            "Tipo documento": mensaje.get("type", ""),
            "DOI": limpiar_doi(mensaje.get("DOI", doi_limpio)),
            "Resumen 3 lineas": _resumen_corto(mensaje.get("abstract", "")),
            "_encontrado": True,
            "_mensaje": "Crossref encontró datos bibliográficos.",
        }
    except requests.Timeout:
        datos_vacios["_mensaje"] = "Crossref tardó demasiado en responder."
        return datos_vacios
    except requests.RequestException:
        datos_vacios["_mensaje"] = "No se pudo conectar con Crossref."
        return datos_vacios
    except Exception:
        datos_vacios["_mensaje"] = "Crossref respondió con un formato inesperado."
        return datos_vacios


def _extraer_metadatos_openalex(datos):
    keywords = []
    topics = []
    concepts = []

    for keyword in datos.get("keywords", [])[:5]:
        nombre = keyword.get("display_name") or keyword.get("keyword")
        if nombre:
            keywords.append(nombre)

    for topic in datos.get("topics", [])[:5]:
        nombre = topic.get("display_name")
        if nombre:
            topics.append(nombre)

    for concepto in datos.get("concepts", [])[:8]:
        nombre = concepto.get("display_name", "")
        if nombre:
            concepts.append(nombre)

    palabras_indexadas = keywords or topics or concepts

    return {
        "keywords": keywords,
        "topics": topics,
        "concepts": concepts,
        "palabras_indexadas": ", ".join(dict.fromkeys(palabras_indexadas)),
    }


def buscar_en_openalex(doi):
    """Consulta OpenAlex y devuelve citas y conceptos disponibles."""
    datos_vacios = {
        "Cantidad de citas": 0,
        "Palabras Indexadas": "",
        "_keywords": [],
        "_topics": [],
        "_concepts": [],
        "_encontrado": False,
        "_mensaje": "OpenAlex no devolvió datos.",
    }

    doi_limpio = limpiar_doi(doi)
    if not doi_limpio:
        datos_vacios["_mensaje"] = "Ingresa un DOI válido para consultar OpenAlex."
        return datos_vacios

    try:
        doi_externo = quote(f"https://doi.org/{doi_limpio}", safe="")
        url = f"https://api.openalex.org/works/{doi_externo}"
        respuesta = requests.get(url, headers=HEADERS, timeout=TIMEOUT_SEGUNDOS)

        if respuesta.status_code == 404:
            return datos_vacios

        respuesta.raise_for_status()
        datos = respuesta.json()
        metadatos = _extraer_metadatos_openalex(datos)

        return {
            "Cantidad de citas": int(datos.get("cited_by_count", 0) or 0),
            "Palabras Indexadas": metadatos["palabras_indexadas"],
            "_keywords": metadatos["keywords"],
            "_topics": metadatos["topics"],
            "_concepts": metadatos["concepts"],
            "_encontrado": True,
            "_mensaje": "OpenAlex encontró citas y palabras indexadas.",
        }
    except requests.Timeout:
        datos_vacios["_mensaje"] = "OpenAlex tardó demasiado en responder."
        return datos_vacios
    except requests.RequestException:
        datos_vacios["_mensaje"] = "No se pudo conectar con OpenAlex."
        return datos_vacios
    except Exception:
        datos_vacios["_mensaje"] = "OpenAlex respondió con un formato inesperado."
        return datos_vacios


def buscar_datos_por_doi(doi):
    """Consulta Crossref y OpenAlex, y combina los datos en un solo resultado."""
    datos_crossref = buscar_en_crossref(doi)
    datos_openalex = buscar_en_openalex(doi)

    datos = {
        "Nombre del Articulo": datos_crossref.get("Nombre del Articulo", ""),
        "Autor(es)": datos_crossref.get("Autor(es)", ""),
        "Año publicacion": datos_crossref.get("Año publicacion", ""),
        "Tipo documento": datos_crossref.get("Tipo documento", ""),
        "DOI": datos_crossref.get("DOI") or limpiar_doi(doi),
        "Cantidad de citas": datos_openalex.get("Cantidad de citas", 0),
        "Palabras Indexadas": datos_openalex.get("Palabras Indexadas", ""),
        "Resumen 3 lineas": datos_crossref.get("Resumen 3 lineas", ""),
        "_keywords": datos_openalex.get("_keywords", []),
        "_topics": datos_openalex.get("_topics", []),
        "_concepts": datos_openalex.get("_concepts", []),
    }

    return {
        "datos": datos,
        "crossref": datos_crossref,
        "openalex": datos_openalex,
        "encontrado": datos_crossref.get("_encontrado") or datos_openalex.get("_encontrado"),
        "mensajes": [
            datos_crossref.get("_mensaje", ""),
            datos_openalex.get("_mensaje", ""),
        ],
    }
