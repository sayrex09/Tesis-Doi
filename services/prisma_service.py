import json
import re
import unicodedata
from collections import Counter

import pandas as pd

from services.doi_service import doi_es_valido, limpiar_doi


NO_DISPONIBLE = "No disponible"
TIPOS_ACADEMICOS = {
    "articulo",
    "artículo",
    "conference",
    "conferencia",
    "journal article",
    "proceedings",
    "revision",
    "review",
    "tesis",
    "thesis",
    "libro",
    "book",
}
PALABRAS_VACIAS = {
    "about",
    "como",
    "con",
    "del",
    "desde",
    "ella",
    "ellos",
    "entre",
    "esta",
    "este",
    "para",
    "por",
    "que",
    "the",
    "and",
    "with",
    "from",
    "into",
    "una",
    "uno",
    "las",
    "los",
    "sobre",
}


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


def _extraer_anio(valor):
    coincidencia = re.search(r"\b(19|20)\d{2}\b", _limpiar_texto(valor))
    return int(coincidencia.group(0)) if coincidencia else None


def _terminos_busqueda(*textos):
    terminos = []
    for texto in textos:
        normalizado = _normalizar(texto)
        for palabra in normalizado.split():
            if len(palabra) >= 4 and palabra not in PALABRAS_VACIAS:
                terminos.append(palabra)
    return list(dict.fromkeys(terminos))


def _relacion_con_tema(fila, terminos):
    titulo = _valor(fila, "Nombre del Articulo")
    resumen = _valor(fila, "Resumen 3 lineas")
    keywords = _valor(fila, "Palabras Indexadas")
    texto = _normalizar(" ".join([titulo, resumen, keywords]))

    if not terminos:
        return "Baja", 0

    coincidencias = sum(1 for termino in terminos if re.search(rf"\b{re.escape(termino)}\b", texto))
    if coincidencias >= 5:
        return "Alta", coincidencias
    if coincidencias >= 2:
        return "Media", coincidencias
    return "Baja", coincidencias


def _tipo_academico(tipo_documento, fuente, doi):
    tipo = _normalizar(tipo_documento)
    if any(tipo_academico in tipo for tipo_academico in TIPOS_ACADEMICOS):
        return True
    return bool(fuente or doi)


def _estado_acceso_texto_completo(fila):
    for columna in ["Acceso texto completo", "Texto completo", "Full text", "full_text"]:
        valor = _valor(fila, columna)
        if valor:
            normalizado = _normalizar(valor)
            if normalizado in {"si", "sí", "yes", "true", "disponible", "available"}:
                return True
            if normalizado in {"no", "false", "no disponible", "unavailable"}:
                return False
    return None


def _clave_duplicado(fila):
    doi = limpiar_doi(_valor(fila, "DOI")).lower()
    if doi:
        return f"doi:{doi}"
    titulo = _normalizar(_valor(fila, "Nombre del Articulo"))
    return f"titulo:{titulo}" if titulo else ""


def _es_duplicado(fila, vistos):
    clave = _clave_duplicado(fila)
    if not clave:
        return False
    if clave in vistos:
        return True
    vistos.add(clave)
    return False


def _observacion_doi(doi):
    doi_limpio = limpiar_doi(doi)
    if not doi_limpio:
        return "DOI no disponible"
    if doi_es_valido(doi_limpio):
        return "DOI completo"
    return "DOI requiere verificacion"


def _evaluar_articulo(
    fila,
    articulo_id,
    terminos,
    anio_inicio,
    anio_fin,
    requerir_texto_completo,
    vistos,
):
    doi = limpiar_doi(_valor(fila, "DOI"))
    titulo = _valor(fila, "Nombre del Articulo")
    autores = _valor(fila, "Autor(es)")
    anio = _extraer_anio(_valor(fila, "Año publicacion"))
    fuente = _valor(fila, "Revista/Conferencia")
    resumen = _valor(fila, "Resumen 3 lineas")
    keywords = _valor(fila, "Palabras Indexadas")
    tipo_documento = _valor(fila, "Tipo documento")
    acceso_texto_completo = _estado_acceso_texto_completo(fila)
    relevancia, coincidencias = _relacion_con_tema(fila, terminos)
    razon_exclusion = ""
    estado_prisma = "Cribado"
    decision = "Dudoso"

    if _es_duplicado(fila, vistos):
        estado_prisma = "Duplicado"
        decision = "Excluir"
        razon_exclusion = "Artículo duplicado"
    elif not titulo and not doi:
        estado_prisma = "Excluido"
        decision = "Excluir"
        razon_exclusion = "Información bibliográfica insuficiente"
    elif anio is not None and (anio < anio_inicio or anio > anio_fin):
        estado_prisma = "Excluido"
        decision = "Excluir"
        razon_exclusion = "Fuera del rango temporal"
    elif not _tipo_academico(tipo_documento, fuente, doi):
        estado_prisma = "Excluido"
        decision = "Excluir"
        razon_exclusion = "Fuente no académica o tipo no permitido"
    elif not doi and not fuente:
        estado_prisma = "Excluido"
        decision = "Excluir"
        razon_exclusion = "Sin DOI o fuente académica verificable"
    elif relevancia == "Baja":
        estado_prisma = "Excluido"
        decision = "Excluir"
        razon_exclusion = "No relacionado directamente con el tema"
    elif requerir_texto_completo and acceso_texto_completo is False:
        estado_prisma = "Excluido"
        decision = "Excluir"
        razon_exclusion = "Sin acceso a texto completo"
    elif not resumen and not keywords:
        estado_prisma = "Elegible"
        decision = "Dudoso"
        razon_exclusion = "Pertinencia no verificable sin resumen o palabras clave"
    else:
        estado_prisma = "Incluido"
        decision = "Incluir"

    observaciones = [
        _observacion_doi(doi),
        f"Relevancia {relevancia.lower()} ({coincidencias} coincidencias temáticas)",
    ]
    if decision == "Dudoso":
        observaciones.append("requiere revisión manual del resumen o texto completo")
    if acceso_texto_completo is None:
        observaciones.append("acceso a texto completo no disponible")

    return {
        "id": articulo_id,
        "doi": _valor_o_no_disponible(doi),
        "titulo": _valor_o_no_disponible(titulo),
        "autores": _valor_o_no_disponible(autores),
        "anio": str(anio) if anio else NO_DISPONIBLE,
        "fuente": _valor_o_no_disponible(fuente),
        "estado_prisma": estado_prisma,
        "decision": decision,
        "razon_exclusion": razon_exclusion,
        "relevancia": relevancia,
        "observacion": "; ".join(observaciones),
    }


def _contar_resumen(articulos, registros_otros_metodos):
    total_articulos = len(articulos)
    duplicados = sum(1 for articulo in articulos if articulo["estado_prisma"] == "Duplicado")
    eliminados_antes = sum(
        1
        for articulo in articulos
        if articulo["razon_exclusion"] == "Información bibliográfica insuficiente"
    )
    registros_cribados = max(total_articulos - duplicados - eliminados_antes, 0)
    excluidos_cribado = sum(
        1
        for articulo in articulos
        if articulo["estado_prisma"] == "Excluido"
        and articulo["razon_exclusion"]
        not in {
            "Artículo duplicado",
            "Información bibliográfica insuficiente",
            "Sin acceso a texto completo",
        }
    )
    no_recuperadas = sum(
        1 for articulo in articulos if articulo["razon_exclusion"] == "Sin acceso a texto completo"
    )
    dudosos = sum(1 for articulo in articulos if articulo["decision"] == "Dudoso")
    incluidos = sum(1 for articulo in articulos if articulo["decision"] == "Incluir")
    solicitadas = max(registros_cribados - excluidos_cribado, 0)
    evaluadas = max(solicitadas - no_recuperadas, 0)

    return {
        "registros_identificados_bases_datos": total_articulos,
        "registros_identificados_otros_metodos": int(registros_otros_metodos or 0),
        "total_registros_identificados": total_articulos + int(registros_otros_metodos or 0),
        "duplicados_eliminados": duplicados,
        "registros_eliminados_antes_cribado": eliminados_antes,
        "registros_cribados": registros_cribados,
        "registros_excluidos": excluidos_cribado,
        "publicaciones_solicitadas_recuperacion": solicitadas,
        "publicaciones_no_recuperadas": no_recuperadas,
        "publicaciones_evaluadas_elegibilidad": evaluadas,
        "publicaciones_excluidas_texto_completo": dudosos,
        "estudios_incluidos_revision": incluidos,
    }


def _contar_razones_exclusion(articulos):
    contador = Counter(
        articulo["razon_exclusion"]
        for articulo in articulos
        if articulo["razon_exclusion"]
    )
    razones_base = [
        "No relacionado directamente con el tema",
        "Sin acceso a texto completo",
        "Fuera del rango temporal",
    ]
    razones = [{"razon": razon, "cantidad": contador.get(razon, 0)} for razon in razones_base]

    for razon, cantidad in contador.most_common():
        if razon not in razones_base:
            razones.append({"razon": razon, "cantidad": cantidad})

    return razones


def _diagrama_mermaid(resumen, razones):
    razones_diagrama = razones[:3]
    while len(razones_diagrama) < 3:
        razones_diagrama.append({"razon": f"Razón {len(razones_diagrama) + 1}", "cantidad": 0})

    return "\n".join(
        [
            "flowchart TD",
            f'    A["Registros identificados desde bases de datos<br>n = {resumen["registros_identificados_bases_datos"]}"] --> B["Registros antes del cribado"]',
            f'    C["Registros eliminados antes del cribado<br>Duplicados: n = {resumen["duplicados_eliminados"]}<br>Eliminados por otras razones: n = {resumen["registros_eliminados_antes_cribado"]}"] --> B',
            f'    B --> D["Registros cribados<br>n = {resumen["registros_cribados"]}"]',
            f'    D --> E["Registros excluidos<br>n = {resumen["registros_excluidos"]}"]',
            f'    D --> F["Publicaciones solicitadas para recuperación<br>n = {resumen["publicaciones_solicitadas_recuperacion"]}"]',
            f'    F --> G["Publicaciones no recuperadas<br>n = {resumen["publicaciones_no_recuperadas"]}"]',
            f'    F --> H["Publicaciones evaluadas para elegibilidad<br>n = {resumen["publicaciones_evaluadas_elegibilidad"]}"]',
            (
                '    H --> I["Publicaciones excluidas<br>'
                f'{razones_diagrama[0]["razon"]}: n = {razones_diagrama[0]["cantidad"]}<br>'
                f'{razones_diagrama[1]["razon"]}: n = {razones_diagrama[1]["cantidad"]}<br>'
                f'{razones_diagrama[2]["razon"]}: n = {razones_diagrama[2]["cantidad"]}"]'
            ),
            f'    H --> J["Estudios incluidos en la revisión<br>n = {resumen["estudios_incluidos_revision"]}"]',
        ]
    )


def _interpretacion_academica(resumen):
    return (
        "Para la revisión sistemática se aplicó la metodología PRISMA 2020, "
        "con el propósito de garantizar transparencia, trazabilidad y rigor académico "
        "en el proceso de selección de estudios. Inicialmente se identificaron "
        f'{resumen["registros_identificados_bases_datos"]} registros en bases de datos '
        f'académicas y {resumen["registros_identificados_otros_metodos"]} registros '
        "mediante otros métodos. Posteriormente, se eliminaron "
        f'{resumen["duplicados_eliminados"]} registros duplicados y se evaluaron '
        f'{resumen["registros_cribados"]} estudios mediante título, resumen y metadatos '
        "bibliográficos disponibles. Tras aplicar los criterios de inclusión y exclusión, "
        f'se seleccionaron {resumen["estudios_incluidos_revision"]} estudios para la '
        "revisión final."
    )


def generar_reporte_prisma(
    articulos,
    tema_investigacion,
    objetivo_revision,
    anio_inicio,
    anio_fin,
    variables=None,
    registros_otros_metodos=0,
    requerir_texto_completo=False,
):
    """Clasifica artículos y genera un reporte PRISMA 2020 en JSON serializable."""
    if isinstance(articulos, pd.DataFrame):
        registros = articulos.fillna("").to_dict("records")
    else:
        registros = list(articulos or [])

    variables = variables or []
    terminos = _terminos_busqueda(tema_investigacion, objetivo_revision, " ".join(variables))
    vistos = set()
    articulos_evaluados = [
        _evaluar_articulo(
            fila=fila,
            articulo_id=indice,
            terminos=terminos,
            anio_inicio=int(anio_inicio),
            anio_fin=int(anio_fin),
            requerir_texto_completo=bool(requerir_texto_completo),
            vistos=vistos,
        )
        for indice, fila in enumerate(registros, start=1)
    ]

    resumen = _contar_resumen(articulos_evaluados, registros_otros_metodos)
    razones = _contar_razones_exclusion(articulos_evaluados)

    return {
        "resumen_prisma": resumen,
        "razones_exclusion": razones,
        "articulos": articulos_evaluados,
        "diagrama_mermaid": _diagrama_mermaid(resumen, razones),
        "interpretacion_academica": _interpretacion_academica(resumen),
    }


def reporte_prisma_to_json(reporte):
    """Convierte el reporte PRISMA a JSON UTF-8 legible para descarga."""
    return json.dumps(reporte, ensure_ascii=False, indent=2).encode("utf-8")
