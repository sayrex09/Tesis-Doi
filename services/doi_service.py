import requests


def limpiar_doi(doi):
    """Normaliza un DOI ingresado como texto o URL."""
    if not doi:
        return ""

    doi_limpio = str(doi).strip()
    doi_comparacion = doi_limpio.lower()
    prefijos = [
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi:",
    ]

    for prefijo in prefijos:
        if doi_comparacion.startswith(prefijo):
            doi_limpio = doi_limpio[len(prefijo) :]
            break

    return doi_limpio.strip()


def _formatear_autores(autores):
    nombres = []
    for autor in autores or []:
        nombre = autor.get("given", "")
        apellido = autor.get("family", "")
        nombre_completo = f"{nombre} {apellido}".strip()
        if nombre_completo:
            nombres.append(nombre_completo)
    return ", ".join(nombres)


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
    }

    doi_limpio = limpiar_doi(doi)
    if not doi_limpio:
        return datos_vacios

    try:
        url = f"https://api.crossref.org/works/{doi_limpio}"
        respuesta = requests.get(url, timeout=10)
        respuesta.raise_for_status()
        mensaje = respuesta.json().get("message", {})

        titulos = mensaje.get("title") or []
        return {
            "Nombre del Articulo": titulos[0] if titulos else "",
            "Autor(es)": _formatear_autores(mensaje.get("author", [])),
            "Año publicacion": _obtener_anio_crossref(mensaje),
            "Tipo documento": mensaje.get("type", ""),
            "DOI": limpiar_doi(mensaje.get("DOI", doi_limpio)),
        }
    except Exception:
        return datos_vacios


def buscar_en_openalex(doi):
    """Consulta OpenAlex y devuelve citas y conceptos disponibles."""
    datos_vacios = {
        "Cantidad de citas": 0,
        "Palabras Indexadas": "",
    }

    doi_limpio = limpiar_doi(doi)
    if not doi_limpio:
        return datos_vacios

    try:
        url = f"https://api.openalex.org/works/https://doi.org/{doi_limpio}"
        respuesta = requests.get(url, timeout=10)
        respuesta.raise_for_status()
        datos = respuesta.json()

        conceptos = []
        for concepto in datos.get("concepts", [])[:8]:
            nombre = concepto.get("display_name", "")
            if nombre:
                conceptos.append(nombre)

        return {
            "Cantidad de citas": int(datos.get("cited_by_count", 0) or 0),
            "Palabras Indexadas": ", ".join(conceptos),
        }
    except Exception:
        return datos_vacios
