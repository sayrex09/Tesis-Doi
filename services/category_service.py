import re
import unicodedata


def _normalizar(texto):
    """Normaliza texto para que las reglas funcionen igual en español e inglés."""
    if not texto:
        return ""

    texto = str(texto).lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(caracter for caracter in texto if not unicodedata.combining(caracter))
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def _unir_textos(*valores):
    partes = []
    for valor in valores:
        if isinstance(valor, (list, tuple, set)):
            partes.extend(str(item) for item in valor if item)
        elif valor:
            partes.append(str(valor))
    return " ".join(partes)


def _contar_coincidencias(texto, palabras):
    coincidencias = []
    texto_normalizado = _normalizar(texto)

    for palabra in palabras:
        palabra_normalizada = _normalizar(palabra)
        if not palabra_normalizada:
            continue

        patron = rf"\b{re.escape(palabra_normalizada)}\b"
        if re.search(patron, texto_normalizado):
            coincidencias.append(palabra)

    return coincidencias


# Macro: foco amplio en país, sector, industria, economía, políticas o impacto global.
PALABRAS_MACRO = [
    "country",
    "countries",
    "national",
    "international",
    "global",
    "region",
    "regional",
    "sector",
    "industry",
    "market",
    "economy",
    "economic",
    "policy",
    "public policy",
    "regulation",
    "government",
    "society",
    "societal",
    "impact",
    "macroeconomic",
    "pais",
    "paises",
    "nacional",
    "internacional",
    "global",
    "sector",
    "industria",
    "mercado",
    "economia",
    "politica publica",
    "regulacion",
    "gobierno",
    "impacto",
]


# Meso: foco organizacional, empresarial, gerencial o de operación de seguridad.
PALABRAS_MESO = [
    "company",
    "companies",
    "enterprise",
    "business",
    "organization",
    "organisational",
    "organizational",
    "management",
    "managerial",
    "governance",
    "decision making",
    "incident management",
    "incident response",
    "security operations center",
    "soc",
    "erp",
    "process",
    "processes",
    "workflow",
    "risk management",
    "cybersecurity management",
    "empresa",
    "empresas",
    "organizacion",
    "organizaciones",
    "gestion",
    "gerencial",
    "gobernanza",
    "toma de decisiones",
    "gestion de incidentes",
    "centro de operaciones de seguridad",
    "procesos",
    "riesgo",
]


# Micro: foco técnico en modelos, algoritmos, detección, datasets o módulos concretos.
PALABRAS_MICRO = [
    "algorithm",
    "algorithms",
    "model",
    "models",
    "machine learning",
    "deep learning",
    "artificial intelligence",
    "neural network",
    "transformer",
    "classification",
    "classifier",
    "prediction",
    "detection",
    "threat detection",
    "anomaly detection",
    "intrusion detection",
    "phishing",
    "malware",
    "ransomware",
    "dataset",
    "datasets",
    "benchmark",
    "framework",
    "feature extraction",
    "random forest",
    "support vector machine",
    "svm",
    "cnn",
    "lstm",
    "bert",
    "module",
    "modulo",
    "algoritmo",
    "algoritmos",
    "modelo",
    "modelos",
    "aprendizaje automatico",
    "aprendizaje profundo",
    "inteligencia artificial",
    "red neuronal",
    "clasificacion",
    "prediccion",
    "deteccion",
    "deteccion de amenazas",
    "deteccion de intrusiones",
    "conjunto de datos",
    "extraccion de caracteristicas",
]


def clasificar_categoria_articulo(
    titulo,
    resumen="",
    keywords=None,
    topics=None,
    concepts=None,
    tipo_documento="",
):
    """
    Clasifica un artículo como Macro, Meso, Micro o Pendiente usando reglas simples.

    La lógica pondera más el título y los metadatos de OpenAlex porque suelen resumir
    mejor el foco del trabajo. El abstract ayuda, pero con menor peso para evitar que
    menciones contextuales cambien una clasificación técnica.
    """
    texto_titulo = titulo or ""
    texto_resumen = resumen or ""
    texto_metadatos = _unir_textos(keywords, topics, concepts, tipo_documento)

    if not _normalizar(_unir_textos(texto_titulo, texto_resumen, texto_metadatos)):
        return {
            "categoria": "Pendiente",
            "justificacion": "No hay metadatos suficientes para clasificar el artículo.",
        }

    reglas = {
        "Macro": PALABRAS_MACRO,
        "Meso": PALABRAS_MESO,
        "Micro": PALABRAS_MICRO,
    }
    pesos = {"titulo": 3, "metadatos": 2, "resumen": 1}
    puntajes = {"Macro": 0, "Meso": 0, "Micro": 0}
    coincidencias = {"Macro": [], "Meso": [], "Micro": []}

    for categoria, palabras in reglas.items():
        coincidencias_titulo = _contar_coincidencias(texto_titulo, palabras)
        coincidencias_metadatos = _contar_coincidencias(texto_metadatos, palabras)
        coincidencias_resumen = _contar_coincidencias(texto_resumen, palabras)

        puntajes[categoria] += len(coincidencias_titulo) * pesos["titulo"]
        puntajes[categoria] += len(coincidencias_metadatos) * pesos["metadatos"]
        puntajes[categoria] += len(coincidencias_resumen) * pesos["resumen"]

        coincidencias[categoria] = list(
            dict.fromkeys(
                coincidencias_titulo + coincidencias_metadatos + coincidencias_resumen
            )
        )

    puntaje_maximo = max(puntajes.values())
    if puntaje_maximo == 0:
        return {
            "categoria": "Pendiente",
            "justificacion": "No se encontraron palabras clave suficientes para clasificar con confianza.",
        }

    candidatas = [
        categoria for categoria, puntaje in puntajes.items() if puntaje == puntaje_maximo
    ]

    # Desempate: se privilegia Micro para focos técnicos, luego Meso para gestión
    # organizacional, y finalmente Macro para contexto amplio de sector o país.
    for prioridad in ["Micro", "Meso", "Macro"]:
        if prioridad in candidatas:
            categoria_final = prioridad
            break

    palabras_encontradas = ", ".join(coincidencias[categoria_final][:6])
    justificacion = (
        f"Clasificado como {categoria_final} por coincidencias en metadatos: "
        f"{palabras_encontradas}."
        if palabras_encontradas
        else f"Clasificado como {categoria_final} por el foco general del artículo."
    )

    return {
        "categoria": categoria_final,
        "justificacion": justificacion,
    }
