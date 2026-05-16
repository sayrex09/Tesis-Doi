import re
import unicodedata

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

from services.category_service import (
    PALABRAS_MACRO,
    PALABRAS_MESO,
    PALABRAS_MICRO,
    clasificar_categoria_articulo,
)
from services.doi_service import limpiar_doi
from services.duplicate_service import normalizar_texto
from services.excel_service import COLUMNAS


SCOPUS_COLUMN_ALIASES = {
    "authors": ["Authors", "Author(s)", "Author Names", "Author full names"],
    "title": ["Document title", "Title", "Article title", "Document Title"],
    "year": ["Year", "Publication Year", "PubYear"],
    "eid": ["EID", "Scopus EID"],
    "source_title": ["Source title", "Journal", "Publication Name"],
    "volume": ["Volume", "Vol"],
    "issue": ["Issue", "Issues", "Volume, issues, pages"],
    "pages": ["Page start", "Page end", "Pages", "Volume, issues, pages"],
    "citation_count": ["Citation count", "Cited by", "Citations"],
    "source_document_type": [
        "Source & document type",
        "Document Type",
        "Source Type",
        "Document type",
    ],
    "publication_stage": ["Publication stage", "Stage"],
    "doi": ["DOI", "Digital Object Identifier"],
    "affiliations": ["Affiliations", "Authors with affiliations"],
    "serial_identifiers": ["Serial identifiers (ISSN)", "ISSN", "ISBN"],
    "pubmed_id": ["PubMed ID", "PMID"],
    "publisher": ["Publisher"],
    "editors": ["Editor(s)", "Editors"],
    "language": ["Language of original document", "Language"],
    "abbreviated_source_title": ["Abbreviated source title", "Abbrev Source Title"],
    "abstract": ["Abstract", "Description"],
    "author_keywords": ["Author keywords", "Author Keywords", "Keywords"],
    "indexed_keywords": ["Indexed keywords", "Index Keywords", "Indexed Keywords"],
    "conference_information": ["Conference information", "Conference"],
    "references": ["References", "Cited References"],
}

TIPOS_DOCUMENTO = {
    "article": "Artículo",
    "journal article": "Artículo",
    "review": "Artículo",
    "conference paper": "Conferencia",
    "conference proceeding": "Conferencia",
    "proceedings paper": "Conferencia",
    "book": "Libro",
    "book chapter": "Libro",
    "chapter": "Libro",
    "thesis": "Tesis",
    "dissertation": "Tesis",
}

PAISES_FRECUENTES = [
    "Peru",
    "Brazil",
    "Chile",
    "Colombia",
    "Ecuador",
    "Argentina",
    "Mexico",
    "United States",
    "Canada",
    "Spain",
    "United Kingdom",
    "Germany",
    "France",
    "Italy",
    "China",
    "India",
    "Japan",
    "Australia",
]


def _normalizar_columna(nombre):
    texto = str(nombre or "").lower().strip()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(caracter for caracter in texto if not unicodedata.combining(caracter))
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _limpiar_celda(valor):
    """Convierte NaN/vacíos en texto limpio y reduce caracteres de control."""
    if valor is None or (isinstance(valor, float) and np.isnan(valor)):
        return ""

    texto = str(valor)
    if texto.strip().lower() in {"nan", "none", "null", "n/a", "na"}:
        return ""

    texto = texto.replace("\ufeff", "")
    texto = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def _leer_csv_robusto(archivo):
    """Lee CSV de Scopus tolerando separador automático y codificaciones comunes."""
    errores = []
    for encoding in ["utf-8-sig", "utf-8", "latin-1"]:
        try:
            if hasattr(archivo, "seek"):
                archivo.seek(0)
            return pd.read_csv(
                archivo,
                sep=None,
                engine="python",
                encoding=encoding,
                dtype=str,
                keep_default_na=False,
            )
        except Exception as error:
            errores.append(str(error))

    raise ValueError(f"No se pudo leer el CSV de Scopus. Detalle: {errores[-1]}")


def detectar_columnas_scopus(columnas):
    """Mapea columnas Scopus aunque cambien levemente de nombre."""
    columnas_originales = list(columnas)
    columnas_normalizadas = {
        columna: _normalizar_columna(columna) for columna in columnas_originales
    }
    opciones = list(columnas_normalizadas.values())
    mapping = {}

    for campo, aliases in SCOPUS_COLUMN_ALIASES.items():
        aliases_normalizados = [_normalizar_columna(alias) for alias in aliases]

        exacta = next(
            (
                columna
                for columna, normalizada in columnas_normalizadas.items()
                if normalizada in aliases_normalizados
            ),
            None,
        )
        if exacta:
            mapping[campo] = exacta
            continue

        mejor_alias = None
        mejor_score = 0
        for alias in aliases_normalizados:
            resultado = process.extractOne(alias, opciones, scorer=fuzz.token_sort_ratio)
            if resultado and resultado[1] > mejor_score:
                mejor_alias = resultado[0]
                mejor_score = resultado[1]

        if mejor_alias and mejor_score >= 86:
            columna_real = next(
                columna
                for columna, normalizada in columnas_normalizadas.items()
                if normalizada == mejor_alias
            )
            mapping[campo] = columna_real

    return mapping


def _serie_limpia(df, mapping, campo):
    columna = mapping.get(campo)
    if not columna or columna not in df.columns:
        return pd.Series([""] * len(df), index=df.index, dtype="object")
    return df[columna].map(_limpiar_celda)


def _normalizar_tipo_documento(valor):
    texto = _limpiar_celda(valor).lower()
    for patron, tipo in TIPOS_DOCUMENTO.items():
        if patron in texto:
            return tipo
    return "Otro" if texto else "Otro"


def _extraer_anio(valor):
    coincidencia = re.search(r"\b(19|20)\d{2}\b", _limpiar_celda(valor))
    return int(coincidencia.group(0)) if coincidencia else 0


def _extraer_citas(valor):
    numero = pd.to_numeric(_limpiar_celda(valor), errors="coerce")
    return int(numero) if pd.notna(numero) else 0


def _separar_keywords(texto):
    texto = _limpiar_celda(texto)
    if not texto:
        return []

    partes = re.split(r";|\||,", texto)
    keywords = []
    for parte in partes:
        limpia = _limpiar_celda(parte)
        if limpia and limpia.lower() not in {"none", "nan"}:
            keywords.append(limpia)
    return keywords


def _extraer_keywords_desde_abstract(abstract):
    """Extrae términos relevantes del abstract usando el vocabulario de clasificación."""
    texto_normalizado = normalizar_texto(abstract)
    if not texto_normalizado:
        return []

    vocabulario = PALABRAS_MACRO + PALABRAS_MESO + PALABRAS_MICRO
    encontrados = []
    for termino in vocabulario:
        termino_normalizado = normalizar_texto(termino)
        if termino_normalizado and re.search(rf"\b{re.escape(termino_normalizado)}\b", texto_normalizado):
            encontrados.append(termino)

    return list(dict.fromkeys(encontrados))


def _limpiar_keywords(*valores):
    keywords = []
    for valor in valores:
        if isinstance(valor, list):
            keywords.extend(valor)
        else:
            keywords.extend(_separar_keywords(valor))

    keywords_limpias = []
    vistos = set()
    for keyword in keywords:
        limpia = _limpiar_celda(keyword)
        clave = normalizar_texto(limpia)
        if limpia and clave and clave not in vistos:
            vistos.add(clave)
            keywords_limpias.append(limpia)

    return ", ".join(keywords_limpias[:20])


def _extraer_pais(affiliations):
    texto = _limpiar_celda(affiliations)
    if not texto:
        return ""

    texto_normalizado = normalizar_texto(texto)
    for pais in PAISES_FRECUENTES:
        if normalizar_texto(pais) in texto_normalizado:
            return pais

    partes = [parte.strip() for parte in re.split(r";|,", texto) if parte.strip()]
    if partes:
        candidato = partes[-1]
        if len(candidato) <= 40 and not any(caracter.isdigit() for caracter in candidato):
            return candidato
    return ""


def _resumen_tres_lineas(abstract, max_caracteres=700):
    texto = _limpiar_celda(abstract)
    if not texto:
        return ""
    oraciones = re.split(r"(?<=[.!?])\s+", texto)
    resumen = " ".join(oraciones[:3]).strip()
    if len(resumen) > max_caracteres:
        resumen = resumen[:max_caracteres].rsplit(" ", 1)[0].strip() + "..."
    return resumen


def procesar_csv_scopus(archivo):
    """Convierte un CSV Scopus en registros compatibles con Sheets/Excel."""
    df_original = _leer_csv_robusto(archivo)
    df_original.columns = [_limpiar_celda(columna) for columna in df_original.columns]
    mapping = detectar_columnas_scopus(df_original.columns)

    if "title" not in mapping:
        raise ValueError("El CSV no contiene una columna reconocible para el título del documento.")

    autores = _serie_limpia(df_original, mapping, "authors")
    titulos = _serie_limpia(df_original, mapping, "title")
    anios = _serie_limpia(df_original, mapping, "year").map(_extraer_anio)
    citas = _serie_limpia(df_original, mapping, "citation_count").map(_extraer_citas)
    tipos = _serie_limpia(df_original, mapping, "source_document_type").map(
        _normalizar_tipo_documento
    )
    dois = _serie_limpia(df_original, mapping, "doi").map(limpiar_doi)
    abstracts = _serie_limpia(df_original, mapping, "abstract")
    author_keywords = _serie_limpia(df_original, mapping, "author_keywords")
    indexed_keywords = _serie_limpia(df_original, mapping, "indexed_keywords")
    affiliations = _serie_limpia(df_original, mapping, "affiliations")

    registros = []
    for indice in df_original.index:
        keywords_autor = _separar_keywords(author_keywords.loc[indice])
        keywords_indexadas = _separar_keywords(indexed_keywords.loc[indice])
        keywords_abstract = _extraer_keywords_desde_abstract(abstracts.loc[indice])
        palabras = _limpiar_keywords(
            keywords_autor,
            keywords_indexadas,
            keywords_abstract,
        )

        clasificacion = clasificar_categoria_articulo(
            titulo=titulos.loc[indice],
            resumen=abstracts.loc[indice],
            keywords=keywords_autor,
            topics=keywords_indexadas,
            concepts=keywords_abstract,
            tipo_documento=tipos.loc[indice],
        )

        registros.append(
            {
                "Categoria": clasificacion["categoria"],
                "Nombre del Articulo": titulos.loc[indice],
                "Autor(es)": autores.loc[indice],
                "Pais": _extraer_pais(affiliations.loc[indice]),
                "Año publicacion": anios.loc[indice],
                "Cantidad de citas": citas.loc[indice],
                "Tipo documento": tipos.loc[indice],
                "DOI": dois.loc[indice],
                "Palabras Indexadas": palabras,
                "Resumen 3 lineas": _resumen_tres_lineas(abstracts.loc[indice]),
                "Justificación categoría": clasificacion["justificacion"],
            }
        )

    df_procesado = pd.DataFrame(registros, columns=COLUMNAS).fillna("")
    df_procesado = df_procesado[df_procesado["Nombre del Articulo"].astype(str).str.strip() != ""]
    return {
        "dataframe": df_procesado.reset_index(drop=True),
        "column_mapping": mapping,
        "total_original": len(df_original),
        "total_procesado": len(df_procesado),
    }


def detectar_duplicados_importacion(df_importado, df_existente, umbral=0.90):
    """Marca duplicados por DOI y similitud de título evitando comparaciones cuadráticas."""
    df = df_importado.copy()
    df["_duplicado"] = False
    df["_motivo_duplicado"] = ""

    dois_existentes = set()
    if not df_existente.empty and "DOI" in df_existente.columns:
        dois_existentes = {
            limpiar_doi(doi).lower()
            for doi in df_existente["DOI"].astype(str)
            if limpiar_doi(doi)
        }

    dois_importados = df["DOI"].astype(str).map(lambda doi: limpiar_doi(doi).lower())
    duplicado_doi_existente = dois_importados.isin(dois_existentes) & (dois_importados != "")
    duplicado_doi_archivo = dois_importados.duplicated(keep="first") & (dois_importados != "")

    df.loc[duplicado_doi_existente, "_duplicado"] = True
    df.loc[duplicado_doi_existente, "_motivo_duplicado"] = "DOI ya existe"
    df.loc[duplicado_doi_archivo, "_duplicado"] = True
    df.loc[duplicado_doi_archivo, "_motivo_duplicado"] = "DOI repetido en CSV"

    titulos_existentes = []
    if not df_existente.empty and "Nombre del Articulo" in df_existente.columns:
        titulos_existentes = [
            titulo
            for titulo in df_existente["Nombre del Articulo"].astype(str)
            if normalizar_texto(titulo)
        ]

    titulos_normalizados_archivo = df["Nombre del Articulo"].astype(str).map(normalizar_texto)
    duplicado_titulo_archivo = titulos_normalizados_archivo.duplicated(keep="first") & (
        titulos_normalizados_archivo != ""
    )
    sin_duplicado = ~df["_duplicado"]
    df.loc[duplicado_titulo_archivo & sin_duplicado, "_duplicado"] = True
    df.loc[duplicado_titulo_archivo & sin_duplicado, "_motivo_duplicado"] = (
        "Título repetido en CSV"
    )

    if titulos_existentes:
        # Para archivos grandes evitamos comparar cada título importado contra todos
        # los existentes. Primero agrupamos por letra inicial y tamaño aproximado;
        # RapidFuzz solo se aplica sobre candidatos plausibles.
        buckets = {}
        for titulo in titulos_existentes:
            titulo_normalizado = normalizar_texto(titulo)
            if not titulo_normalizado:
                continue
            clave = titulo_normalizado[:1]
            buckets.setdefault(clave, []).append(titulo_normalizado)

        for indice, titulo in df.loc[~df["_duplicado"], "Nombre del Articulo"].items():
            titulo_normalizado = normalizar_texto(titulo)
            if not titulo_normalizado:
                continue
            longitud = len(titulo_normalizado)
            candidatos = [
                candidato
                for candidato in buckets.get(titulo_normalizado[:1], [])
                if abs(len(candidato) - longitud) <= max(20, longitud * 0.35)
            ]
            if not candidatos:
                continue
            resultado = process.extractOne(
                titulo_normalizado,
                candidatos,
                scorer=fuzz.token_sort_ratio,
                score_cutoff=umbral * 100,
            )
            if resultado:
                df.at[indice, "_duplicado"] = True
                df.at[indice, "_motivo_duplicado"] = (
                    f"Título similar a uno existente ({resultado[1]:.1f}%)"
                )

    return df
