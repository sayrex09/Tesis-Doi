import re
import unicodedata
from collections import OrderedDict


SECCIONES_TESIS = OrderedDict(
    [
        (
            "planteamiento_problema",
            {
                "nombre": "Planteamiento del problema",
                "patrones": [
                    r"planteamiento del problema",
                    r"realidad problematica",
                    r"descripcion del problema",
                    r"formulacion del problema",
                    r"problema de investigacion",
                ],
            },
        ),
        (
            "objetivo_general",
            {
                "nombre": "Objetivo general",
                "patrones": [
                    r"objetivo general",
                    r"objetivo principal",
                    r"proposito general",
                ],
            },
        ),
        (
            "objetivos_especificos",
            {
                "nombre": "Objetivos especificos",
                "patrones": [
                    r"objetivos especificos",
                    r"objetivo especifico",
                ],
            },
        ),
        (
            "justificacion",
            {
                "nombre": "Justificacion",
                "patrones": [
                    r"justificacion",
                    r"justificacion de la investigacion",
                    r"importancia de la investigacion",
                ],
            },
        ),
        (
            "estado_arte",
            {
                "nombre": "Estado del arte",
                "patrones": [
                    r"estado del arte",
                    r"antecedentes",
                    r"antecedentes de la investigacion",
                    r"trabajos relacionados",
                    r"revision de literatura",
                ],
            },
        ),
        (
            "marco_teorico",
            {
                "nombre": "Marco teorico",
                "patrones": [
                    r"marco teorico",
                    r"bases teoricas",
                    r"fundamento teorico",
                    r"fundamentos teoricos",
                ],
            },
        ),
        (
            "metodologia",
            {
                "nombre": "Metodologia",
                "patrones": [
                    r"metodologia",
                    r"metodologia de la investigacion",
                    r"materiales y metodos",
                    r"metodos",
                    r"diseno metodologico",
                ],
            },
        ),
        (
            "alcances_limitaciones",
            {
                "nombre": "Alcances y limitaciones",
                "patrones": [
                    r"alcances y limitaciones",
                    r"alcance y limitaciones",
                    r"alcances",
                    r"limitaciones",
                    r"delimitacion",
                    r"delimitaciones",
                ],
            },
        ),
    ]
)


NECESIDADES_CITAS = [
    {
        "seccion": "Planteamiento del problema",
        "necesidad": (
            "Sustentar problemas de informacion dispersa, uso de hojas de calculo, "
            "baja trazabilidad y falta de visibilidad operativa en PYMES."
        ),
    },
    {
        "seccion": "Justificacion",
        "necesidad": (
            "Respaldar beneficios de sistemas ERP/web modulares para centralizar datos, "
            "mejorar procesos y apoyar decisiones."
        ),
    },
    {
        "seccion": "Estado del arte",
        "necesidad": (
            "Comparar soluciones ERP, sistemas de gestion empresarial, inventario, "
            "compras, produccion y dashboards en contextos similares."
        ),
    },
    {
        "seccion": "Marco teorico",
        "necesidad": (
            "Definir ERP, modularidad, trazabilidad, dashboard, informacion en tiempo real "
            "y gestion de procesos empresariales."
        ),
    },
    {
        "seccion": "Metodologia",
        "necesidad": (
            "Sustentar el enfoque aplicado, desarrollo de software, piloto, validacion "
            "funcional y recoleccion de requerimientos."
        ),
    },
    {
        "seccion": "Alcances y limitaciones",
        "necesidad": (
            "Justificar el alcance por modulos iniciales, piloto en una empresa y "
            "restricciones de generalizacion."
        ),
    },
]


def _normalizar(texto):
    texto = str(texto or "").lower().strip()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(caracter for caracter in texto if not unicodedata.combining(caracter))
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _limpiar_linea(linea):
    linea = str(linea or "").replace("\ufeff", " ")
    linea = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", linea)
    return re.sub(r"\s+", " ", linea).strip()


def _limpiar_texto(texto):
    lineas = [_limpiar_linea(linea) for linea in str(texto or "").splitlines()]
    lineas = [linea for linea in lineas if linea]
    return "\n".join(lineas)


def extraer_texto_pdf(archivo_pdf, max_paginas=None):
    """Extrae texto de un PDF cargado desde Streamlit usando pypdf."""
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise ImportError(
            "Falta la dependencia pypdf. Instalela con: pip install pypdf"
        ) from error

    try:
        if hasattr(archivo_pdf, "seek"):
            archivo_pdf.seek(0)

        lector = PdfReader(archivo_pdf)
        total_paginas = len(lector.pages)
        limite = total_paginas if max_paginas is None else min(total_paginas, max_paginas)
        textos = []

        for indice in range(limite):
            textos.append(lector.pages[indice].extract_text() or "")

        return _limpiar_texto("\n".join(textos)), total_paginas
    except Exception as error:
        raise ValueError(f"No se pudo leer el PDF de la tesis: {error}") from error


def _quitar_numeracion_encabezado(texto_normalizado):
    texto = re.sub(r"^(capitulo|chapter)\s+[ivxlcdm0-9]+\s+", "", texto_normalizado)
    texto = re.sub(r"^[ivxlcdm]+\s+", "", texto)
    texto = re.sub(r"^\d+(?:\s+\d+)*\s+", "", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _coincide_encabezado(linea, patrones):
    linea_normalizada = _quitar_numeracion_encabezado(_normalizar(linea))
    if not linea_normalizada or len(linea_normalizada) > 90:
        return False

    for patron in patrones:
        if re.fullmatch(patron, linea_normalizada):
            return True
        if linea_normalizada.startswith(patron) and len(linea_normalizada) <= len(patron) + 20:
            return True
    return False


def _detectar_encabezados(lineas):
    encabezados = []
    for indice, linea in enumerate(lineas):
        for clave, config in SECCIONES_TESIS.items():
            if _coincide_encabezado(linea, config["patrones"]):
                encabezados.append(
                    {
                        "clave": clave,
                        "nombre": config["nombre"],
                        "linea": indice,
                    }
                )
                break
    return encabezados


def _compactar_extracto(lineas, max_caracteres=1800):
    texto = " ".join(_limpiar_linea(linea) for linea in lineas if _limpiar_linea(linea))
    texto = re.sub(r"\s+", " ", texto).strip()
    if len(texto) > max_caracteres:
        texto = texto[:max_caracteres].rsplit(" ", 1)[0].strip() + "..."
    return texto


def detectar_titulo_tesis(texto):
    """Intenta reconocer el titulo de la tesis desde las primeras lineas del PDF."""
    lineas = [_limpiar_linea(linea) for linea in texto.splitlines() if _limpiar_linea(linea)]
    primeras_lineas = lineas[:120]

    for indice, linea in enumerate(primeras_lineas):
        normalizada = _normalizar(linea)
        if normalizada in {"titulo", "titulo de tesis", "titulo del proyecto"}:
            for candidata in primeras_lineas[indice + 1 : indice + 5]:
                if len(candidata) >= 20:
                    return candidata.strip(" .")
        if normalizada.startswith("titulo ") and len(linea) > 20:
            return re.sub(r"^t[ií]tulo\s*[:.-]?\s*", "", linea, flags=re.IGNORECASE).strip(" .")

    primer_encabezado = next(
        (
            indice
            for indice, linea in enumerate(primeras_lineas)
            if any(
                _coincide_encabezado(linea, config["patrones"])
                for config in SECCIONES_TESIS.values()
            )
        ),
        len(primeras_lineas),
    )
    lineas_candidatas = primeras_lineas[:primer_encabezado] or primeras_lineas

    bloqueadores = {
        "universidad",
        "facultad",
        "escuela",
        "carrera",
        "tesis",
        "para optar",
        "autor",
        "asesor",
        "jurado",
        "dedicatoria",
        "agradecimiento",
        "repositorio",
    }
    mejores = []
    for indice, linea in enumerate(lineas_candidatas):
        normalizada = _normalizar(linea)
        if any(palabra in normalizada for palabra in bloqueadores):
            continue
        if not 25 <= len(linea) <= 220:
            continue
        if sum(caracter.isalpha() for caracter in linea) < 15:
            continue

        puntaje = len(linea)
        if any(termino in normalizada for termino in ["sistema", "erp", "web", "pyme", "empresa"]):
            puntaje += 80
        if indice < 60:
            puntaje += 30
        mejores.append((puntaje, linea.strip(" .")))

    return max(mejores, default=(0, "requiere verificacion"))[1]


def detectar_secciones_tesis(texto):
    """Detecta secciones academicas clave y devuelve extractos representativos."""
    lineas = [_limpiar_linea(linea) for linea in texto.splitlines() if _limpiar_linea(linea)]
    encabezados = _detectar_encabezados(lineas)
    secciones = {
        clave: {
            "nombre": config["nombre"],
            "encontrado": False,
            "extracto": "requiere verificacion",
        }
        for clave, config in SECCIONES_TESIS.items()
    }

    for posicion, encabezado in enumerate(encabezados):
        inicio = encabezado["linea"] + 1
        siguiente = (
            encabezados[posicion + 1]["linea"]
            if posicion + 1 < len(encabezados)
            else min(len(lineas), inicio + 120)
        )
        extracto = _compactar_extracto(lineas[inicio:siguiente])
        if len(extracto) < 25:
            continue

        clave = encabezado["clave"]
        actual = secciones[clave]["extracto"]
        if actual == "requiere verificacion" or len(extracto) > len(actual):
            secciones[clave] = {
                "nombre": encabezado["nombre"],
                "encontrado": True,
                "extracto": extracto,
            }

    return secciones


def detectar_necesidades_citas(secciones):
    """Lista las partes de la tesis que normalmente deben respaldarse con citas."""
    resultado = []
    secciones_por_nombre = {
        datos["nombre"]: datos for datos in secciones.values()
    }

    for item in NECESIDADES_CITAS:
        datos = secciones_por_nombre.get(item["seccion"], {})
        resultado.append(
            {
                "Seccion": item["seccion"],
                "Necesidad de cita academica": item["necesidad"],
                "Estado en PDF": "Detectada" if datos.get("encontrado") else "Requiere verificacion",
            }
        )

    return resultado


def analizar_tesis_pdf(archivo_pdf):
    """Reconoce datos principales de una tesis en PDF para orientar citas y articulos."""
    texto, total_paginas = extraer_texto_pdf(archivo_pdf)
    secciones = detectar_secciones_tesis(texto)

    return {
        "titulo": detectar_titulo_tesis(texto),
        "paginas": total_paginas,
        "palabras_extraidas": len(texto.split()),
        "secciones": secciones,
        "necesidades_citas": detectar_necesidades_citas(secciones),
        "texto_extraido": texto,
    }
