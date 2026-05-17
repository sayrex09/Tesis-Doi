import re
import unicodedata

import pandas as pd
from rapidfuzz import fuzz

from services.doi_service import limpiar_doi


NO_DISPONIBLE = "No disponible"


def _limpiar_texto(valor):
    if valor is None:
        return ""
    try:
        if pd.isna(valor):
            return ""
    except (TypeError, ValueError):
        pass
    texto = str(valor).replace("\ufeff", " ")
    texto = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", texto)
    texto = re.sub(r"\s+", " ", texto)
    if texto.strip().lower() in {"", "nan", "none", "null", "n/a", "na", "0", "0.0"}:
        return ""
    return texto.strip()


def _normalizar(texto):
    texto = _limpiar_texto(texto).lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(caracter for caracter in texto if not unicodedata.combining(caracter))
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _valor(fila, columna):
    if isinstance(fila, dict):
        return _limpiar_texto(fila.get(columna, ""))
    return _limpiar_texto(fila[columna]) if columna in fila else ""


def _valor_o_no_disponible(valor):
    valor = _limpiar_texto(valor)
    return valor if valor else NO_DISPONIBLE


def _clave_duplicado(fila):
    doi = limpiar_doi(_valor(fila, "DOI")).lower()
    if doi:
        return f"doi:{doi}"
    titulo = _normalizar(_valor(fila, "Nombre del Articulo"))
    return f"titulo:{titulo}" if titulo else ""


def _estado_duplicado(fila, vistos):
    clave = _clave_duplicado(fila)
    if not clave:
        return False
    if clave in vistos:
        return True
    vistos.add(clave)
    return False


def _texto_tesis(analisis_tesis):
    if not analisis_tesis:
        return ""
    texto = analisis_tesis.get("texto_extraido", "")
    if texto:
        return texto
    secciones = analisis_tesis.get("secciones", {})
    return " ".join(datos.get("extracto", "") for datos in secciones.values())


def _coincidencia_citacion(fila, texto_tesis_normalizado):
    doi = limpiar_doi(_valor(fila, "DOI"))
    titulo = _valor(fila, "Nombre del Articulo")
    autores = _valor(fila, "Autor(es)")

    if doi and _normalizar(doi) in texto_tesis_normalizado:
        return "Citado", 100, "El DOI aparece en el texto de la tesis."

    titulo_normalizado = _normalizar(titulo)
    if titulo_normalizado and titulo_normalizado in texto_tesis_normalizado:
        return "Citado", 95, "El título aparece en el texto de la tesis."

    if titulo_normalizado and texto_tesis_normalizado:
        similitud_titulo = fuzz.partial_ratio(titulo_normalizado, texto_tesis_normalizado)
        if similitud_titulo >= 92:
            return "Citado", int(similitud_titulo), "El título tiene una coincidencia alta con la tesis."

    primer_autor = _normalizar(autores.split(";")[0] if autores else "")
    anio = _valor(fila, "Año publicacion")
    if primer_autor and anio and primer_autor.split()[-1] in texto_tesis_normalizado and anio in texto_tesis_normalizado:
        return "Citado", 80, "Coinciden autor y año en el texto de la tesis."

    return "No citado", 0, "No se encontró DOI, título ni patrón autor-año en la tesis."


def _relevancia_tematica(fila, analisis_tesis):
    texto_articulo = _normalizar(
        " ".join(
            [
                _valor(fila, "Nombre del Articulo"),
                _valor(fila, "Resumen 3 lineas"),
                _valor(fila, "Palabras Indexadas"),
            ]
        )
    )
    texto_tesis = _normalizar(
        " ".join(
            [
                analisis_tesis.get("titulo", "") if analisis_tesis else "",
                _texto_tesis(analisis_tesis),
            ]
        )
    )

    if not texto_articulo or not texto_tesis:
        return "Pendiente", 0

    palabras_articulo = {
        palabra for palabra in texto_articulo.split() if len(palabra) >= 4
    }
    palabras_tesis = {
        palabra for palabra in texto_tesis.split() if len(palabra) >= 4
    }
    if not palabras_articulo or not palabras_tesis:
        return "Baja", 0

    coincidencias = palabras_articulo & palabras_tesis
    porcentaje = int((len(coincidencias) / max(len(palabras_articulo), 1)) * 100)

    if porcentaje >= 18 or len(coincidencias) >= 10:
        return "Alta", min(porcentaje, 100)
    if porcentaje >= 8 or len(coincidencias) >= 4:
        return "Media", min(porcentaje, 100)
    return "Baja", min(porcentaje, 100)


def generar_tabla_comparacion_tesis_articulos(articulos, analisis_tesis=None):
    """Compara artículos contra el texto extraído de la tesis y marca estados útiles."""
    if isinstance(articulos, pd.DataFrame):
        registros = articulos.fillna("").to_dict("records")
    else:
        registros = list(articulos or [])

    texto_tesis_normalizado = _normalizar(_texto_tesis(analisis_tesis))
    vistos = set()
    filas = []

    for indice, fila in enumerate(registros, start=1):
        duplicado = _estado_duplicado(fila, vistos)
        estado_citacion, coincidencia_citacion, evidencia = _coincidencia_citacion(
            fila,
            texto_tesis_normalizado,
        )
        relevancia, coincidencia_tematica = _relevancia_tematica(fila, analisis_tesis)

        if duplicado:
            estado = "Duplicado"
            accion = "Revisar y conservar solo un registro."
            motivo = "DOI o título repetido."
        elif not analisis_tesis:
            estado = "Pendiente"
            accion = "Subir la tesis para comparar."
            motivo = "No hay tesis analizada."
        elif relevancia in {"Alta", "Media"} and estado_citacion == "No citado":
            estado = "Falta integrar"
            accion = "Evaluar cita en estado del arte o marco teórico."
            motivo = evidencia
        elif relevancia in {"Alta", "Media"} and estado_citacion == "Citado":
            estado = "Citado"
            accion = "Mantener y verificar formato de referencia."
            motivo = evidencia
        elif relevancia == "Pendiente":
            estado = "Pendiente"
            accion = "Completar resumen o palabras clave."
            motivo = "No hay datos suficientes para calcular relevancia."
        else:
            estado = "Baja relación"
            accion = "Revisar antes de incluir."
            motivo = "Coincidencia temática baja con la tesis."

        filas.append(
            {
                "ID": indice,
                "Título": _valor_o_no_disponible(_valor(fila, "Nombre del Articulo")),
                "Autores": _valor_o_no_disponible(_valor(fila, "Autor(es)")),
                "Año": _valor_o_no_disponible(_valor(fila, "Año publicacion")),
                "DOI": _valor_o_no_disponible(limpiar_doi(_valor(fila, "DOI"))),
                "Fuente": _valor_o_no_disponible(_valor(fila, "Revista/Conferencia")),
                "Estado": estado,
                "Coincidencia con la tesis": max(coincidencia_citacion, coincidencia_tematica),
                "Relevancia": relevancia,
                "Motivo": motivo,
                "Acción recomendada": accion,
            }
        )

    return pd.DataFrame(filas)
