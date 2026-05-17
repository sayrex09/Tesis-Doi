from io import BytesIO

import pandas as pd
import streamlit as st

from services.category_service import clasificar_categoria_articulo
from services.comparison_service import generar_tabla_comparacion_tesis_articulos
from services.doi_service import buscar_datos_por_doi, doi_es_valido, limpiar_doi
from services.duplicate_service import buscar_titulo_similar, existe_doi
from services.excel_service import (
    COLUMNAS,
    agregar_articulo,
    agregar_articulos,
    cargar_articulos,
    crear_excel_si_no_existe,
    dataframe_to_csv,
    dataframe_to_excel,
    guardar_articulos,
)
from services.ieee_reference_service import preparar_exportacion_referencias
from services.prisma_service import generar_reporte_prisma, reporte_prisma_to_json
from services.scopus_import_service import (
    detectar_duplicados_importacion,
    procesar_csv_scopus,
)
from services.thesis_pdf_service import analizar_tesis_pdf


TIPOS_DOCUMENTO = ["Artículo", "Tesis", "Libro", "Conferencia", "Otro"]
TIPOS_CROSSREF = {
    "journal-article": "Artículo",
    "proceedings-article": "Conferencia",
    "book": "Libro",
    "book-chapter": "Libro",
    "posted-content": "Artículo",
    "dissertation": "Tesis",
}


def convertir_entero(valor, por_defecto=0):
    try:
        if valor in ("", None) or pd.isna(valor):
            return por_defecto
        return int(float(valor))
    except Exception:
        return por_defecto


def mapear_tipo_documento(tipo_api):
    if not tipo_api:
        return "Artículo"
    return TIPOS_CROSSREF.get(str(tipo_api).strip().lower(), "Otro")


def inicializar_estado_formulario():
    valores_iniciales = {
        "form_categoria": "Pendiente",
        "form_nombre": "",
        "form_autores": "",
        "form_pais": "",
        "form_anio": 0,
        "form_citas": 0,
        "form_tipo": "Artículo",
        "form_doi": "",
        "form_revista": "",
        "form_volumen": "",
        "form_numero": "",
        "form_paginas": "",
        "form_url": "",
        "form_editorial": "",
        "form_palabras": "",
        "form_resumen": "",
        "form_justificacion_categoria": "",
        "form_permitir_titulo_similar": False,
    }

    for clave, valor in valores_iniciales.items():
        st.session_state.setdefault(clave, valor)


def aplicar_datos_doi(datos_crossref, datos_openalex):
    if datos_crossref.get("Nombre del Articulo"):
        st.session_state["form_nombre"] = datos_crossref["Nombre del Articulo"]
    if datos_crossref.get("Autor(es)"):
        st.session_state["form_autores"] = datos_crossref["Autor(es)"]
    if datos_crossref.get("Año publicacion"):
        st.session_state["form_anio"] = convertir_entero(datos_crossref["Año publicacion"])
    if datos_crossref.get("Tipo documento"):
        st.session_state["form_tipo"] = mapear_tipo_documento(datos_crossref["Tipo documento"])
    if datos_crossref.get("DOI"):
        st.session_state["form_doi"] = limpiar_doi(datos_crossref["DOI"])
    if datos_crossref.get("Revista/Conferencia"):
        st.session_state["form_revista"] = datos_crossref["Revista/Conferencia"]
    if datos_crossref.get("Volumen"):
        st.session_state["form_volumen"] = datos_crossref["Volumen"]
    if datos_crossref.get("Numero"):
        st.session_state["form_numero"] = datos_crossref["Numero"]
    if datos_crossref.get("Paginas"):
        st.session_state["form_paginas"] = datos_crossref["Paginas"]
    if datos_crossref.get("URL"):
        st.session_state["form_url"] = datos_crossref["URL"]
    if datos_crossref.get("Editorial"):
        st.session_state["form_editorial"] = datos_crossref["Editorial"]
    if datos_crossref.get("Resumen 3 lineas"):
        st.session_state["form_resumen"] = datos_crossref["Resumen 3 lineas"]

    st.session_state["form_citas"] = convertir_entero(
        datos_openalex.get("Cantidad de citas", 0)
    )
    if datos_openalex.get("Palabras Indexadas"):
        st.session_state["form_palabras"] = datos_openalex["Palabras Indexadas"]

    clasificacion = clasificar_categoria_articulo(
        titulo=datos_crossref.get("Nombre del Articulo", ""),
        resumen=datos_crossref.get("Resumen 3 lineas", ""),
        keywords=datos_openalex.get("_keywords", []),
        topics=datos_openalex.get("_topics", []),
        concepts=datos_openalex.get("_concepts", []),
        tipo_documento=datos_crossref.get("Tipo documento", ""),
    )
    st.session_state["form_categoria"] = clasificacion["categoria"]
    st.session_state["form_justificacion_categoria"] = clasificacion["justificacion"]


def validar_articulo(nuevo_articulo, df_actual, permitir_titulo_similar=False):
    nombre = str(nuevo_articulo.get("Nombre del Articulo", "")).strip()
    doi = limpiar_doi(nuevo_articulo.get("DOI", ""))

    if not nombre:
        return False, "error", "El nombre del artículo es obligatorio."

    if doi and existe_doi(df_actual, doi):
        return False, "error", "El DOI ingresado ya existe en la base de datos."

    titulo_similar = buscar_titulo_similar(df_actual, nombre, umbral=0.90)
    if titulo_similar:
        similitud = titulo_similar["similitud"] * 100
        mensaje = (
            "Posible artículo duplicado. "
            f"Coincide {similitud:.1f}% con: {titulo_similar['titulo']}"
        )
        if permitir_titulo_similar:
            return True, "warning", f"{mensaje}. Se guardará porque confirmaste la revisión."
        return False, "warning", mensaje

    return True, "success", "Artículo válido."


def mostrar_mensaje_api(mensaje):
    if not mensaje:
        return
    if "encontró" in mensaje:
        st.success(mensaje)
    elif "válido" in mensaje:
        st.warning(mensaje)
    else:
        st.info(mensaje)


def filtrar_articulos(df):
    df_filtrado = df.copy()

    palabra_clave = st.text_input("Buscar por palabra clave")
    if palabra_clave.strip():
        texto = palabra_clave.strip().lower()
        mascara = df_filtrado.astype(str).apply(
            lambda fila: fila.str.lower().str.contains(texto, na=False).any(),
            axis=1,
        )
        df_filtrado = df_filtrado[mascara]

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        categorias = ["Todas"] + sorted(
            [str(valor) for valor in df["Categoria"].dropna().unique() if str(valor).strip()]
        )
        categoria = st.selectbox("Categoría", categorias)

    with col2:
        anios = ["Todos"] + sorted(
            [
                convertir_entero(valor)
                for valor in df["Año publicacion"].dropna().unique()
                if convertir_entero(valor) > 0
            ]
        )
        anio = st.selectbox("Año publicación", anios)

    with col3:
        tipos = ["Todos"] + sorted(
            [
                str(valor)
                for valor in df["Tipo documento"].dropna().unique()
                if str(valor).strip()
            ]
        )
        tipo = st.selectbox("Tipo documento", tipos)

    with col4:
        paises = ["Todos"] + sorted(
            [str(valor) for valor in df["Pais"].dropna().unique() if str(valor).strip()]
        )
        pais = st.selectbox("País", paises)

    with col5:
        citas_numericas = df["Cantidad de citas"].apply(convertir_entero)
        max_citas = int(citas_numericas.max()) if not citas_numericas.empty else 0
        if max_citas > 0:
            rango_citas = st.slider(
                "Cantidad de citas",
                min_value=0,
                max_value=max_citas,
                value=(0, max_citas),
                step=1,
            )
        else:
            st.number_input("Cantidad de citas", min_value=0, value=0, disabled=True)
            rango_citas = (0, 0)

    if categoria != "Todas":
        df_filtrado = df_filtrado[df_filtrado["Categoria"].astype(str) == categoria]
    if anio != "Todos":
        df_filtrado = df_filtrado[
            df_filtrado["Año publicacion"].apply(convertir_entero) == anio
        ]
    if tipo != "Todos":
        df_filtrado = df_filtrado[df_filtrado["Tipo documento"].astype(str) == tipo]
    if pais != "Todos":
        df_filtrado = df_filtrado[df_filtrado["Pais"].astype(str) == pais]
    if max_citas > 0:
        citas_filtradas = df_filtrado["Cantidad de citas"].apply(convertir_entero)
        df_filtrado = df_filtrado[
            (citas_filtradas >= rango_citas[0]) & (citas_filtradas <= rango_citas[1])
        ]

    return df_filtrado


@st.cache_data(show_spinner=False)
def cargar_articulos_cacheado():
    """Lee el Excel local con caché para evitar recargas innecesarias."""
    return cargar_articulos()


def invalidar_cache_articulos():
    cargar_articulos_cacheado.clear()


def cargar_articulos_principal():
    """Carga artículos desde almacenamiento local."""
    return cargar_articulos_cacheado(), "Excel local", None


def agregar_articulo_principal(nuevo_articulo, fuente_datos):
    """Guarda un artículo en Excel local con backup automático."""
    if agregar_articulo(nuevo_articulo):
        invalidar_cache_articulos()
        return True, "Excel local", None

    return (
        False,
        "Excel local",
        "No se pudo guardar el artículo. Cierra el Excel si está abierto e inténtalo de nuevo.",
    )


def agregar_articulos_principal(nuevos_articulos, fuente_datos):
    """Guarda lotes importados desde CSV en Excel local."""
    if not nuevos_articulos:
        return True, fuente_datos, None

    if agregar_articulos(nuevos_articulos):
        invalidar_cache_articulos()
        return True, "Excel local", None

    return (
        False,
        "Excel local",
        "No se pudo importar el CSV. Cierra el Excel si está abierto e inténtalo de nuevo.",
    )


def preparar_excel_descarga(df):
    try:
        return dataframe_to_excel(df)
    except Exception:
        buffer = BytesIO()
        df.to_excel(buffer, index=False, engine="openpyxl")
        buffer.seek(0)
        return buffer


def inyectar_estilos_ui():
    st.markdown(
        """
        <style>
        :root {
            --td-bg: #f8fafc;
            --td-surface: #ffffff;
            --td-border: #e5e7eb;
            --td-text: #111827;
            --td-muted: #64748b;
            --td-primary: #2563eb;
            --td-success: #16a34a;
            --td-warning: #d97706;
            --td-danger: #dc2626;
        }
        .main .block-container {
            padding-top: 1.4rem;
            padding-bottom: 2.5rem;
            max-width: 1280px;
        }
        h1, h2, h3 {
            letter-spacing: 0;
            color: var(--td-text);
        }
        div[data-testid="stSidebar"] {
            background: #0f172a;
        }
        div[data-testid="stSidebar"] * {
            color: #e5e7eb;
        }
        div[data-testid="stSidebar"] [data-testid="stRadio"] label {
            font-size: 0.92rem;
        }
        .td-page-title {
            font-size: 1.6rem;
            font-weight: 750;
            margin: 0 0 .25rem 0;
            color: var(--td-text);
        }
        .td-page-subtitle {
            color: var(--td-muted);
            font-size: .98rem;
            margin-bottom: 1.2rem;
        }
        .td-band {
            border: 1px solid var(--td-border);
            background: var(--td-surface);
            padding: 1rem 1.1rem;
            border-radius: 8px;
            margin: .8rem 0 1rem 0;
        }
        .td-metric-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: .8rem;
            margin: .6rem 0 1rem 0;
        }
        .td-metric {
            border: 1px solid var(--td-border);
            background: var(--td-surface);
            border-radius: 8px;
            padding: .9rem 1rem;
        }
        .td-metric-label {
            color: var(--td-muted);
            font-size: .78rem;
            font-weight: 650;
            text-transform: uppercase;
            letter-spacing: .02em;
        }
        .td-metric-value {
            color: var(--td-text);
            font-size: 1.65rem;
            font-weight: 780;
            line-height: 1.2;
            margin-top: .3rem;
        }
        .td-metric-help {
            color: var(--td-muted);
            font-size: .84rem;
            margin-top: .25rem;
        }
        .td-status-row {
            display: flex;
            flex-wrap: wrap;
            gap: .45rem;
            margin: .5rem 0 .8rem 0;
        }
        .td-chip {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: .22rem .55rem;
            font-size: .78rem;
            font-weight: 650;
            border: 1px solid transparent;
            white-space: nowrap;
        }
        .td-chip.success { color: #166534; background: #dcfce7; border-color: #bbf7d0; }
        .td-chip.warning { color: #92400e; background: #fef3c7; border-color: #fde68a; }
        .td-chip.danger { color: #991b1b; background: #fee2e2; border-color: #fecaca; }
        .td-chip.info { color: #1d4ed8; background: #dbeafe; border-color: #bfdbfe; }
        .td-chip.neutral { color: #475569; background: #f1f5f9; border-color: #e2e8f0; }
        .td-step {
            display: grid;
            grid-template-columns: 30px 1fr;
            gap: .65rem;
            align-items: start;
            padding: .55rem 0;
            border-bottom: 1px solid #eef2f7;
        }
        .td-step:last-child { border-bottom: 0; }
        .td-step-index {
            width: 28px;
            height: 28px;
            border-radius: 999px;
            display: grid;
            place-items: center;
            color: white;
            background: var(--td-primary);
            font-size: .82rem;
            font-weight: 750;
        }
        .td-step-title {
            font-weight: 720;
            color: var(--td-text);
            margin-bottom: .1rem;
        }
        .td-step-body {
            color: var(--td-muted);
            font-size: .9rem;
        }
        @media (max-width: 900px) {
            .td-metric-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }
        @media (max-width: 560px) {
            .td-metric-grid {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def mostrar_titulo_modulo(titulo, subtitulo):
    st.markdown(f'<div class="td-page-title">{titulo}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="td-page-subtitle">{subtitulo}</div>', unsafe_allow_html=True)


def mostrar_metricas(metricas):
    tarjetas = []
    for etiqueta, valor, ayuda in metricas:
        tarjetas.append(
            '<div class="td-metric">'
            f'<div class="td-metric-label">{etiqueta}</div>'
            f'<div class="td-metric-value">{valor}</div>'
            f'<div class="td-metric-help">{ayuda}</div>'
            "</div>"
        )
    st.markdown(
        f'<div class="td-metric-grid">{"".join(tarjetas)}</div>',
        unsafe_allow_html=True,
    )


def chip_estado(texto, tipo="neutral"):
    return f'<span class="td-chip {tipo}">{texto}</span>'


def mostrar_chips_estado(chips):
    contenido = "".join(chip_estado(texto, tipo) for texto, tipo in chips)
    st.markdown(f'<div class="td-status-row">{contenido}</div>', unsafe_allow_html=True)


def obtener_metricas_dashboard(df):
    total = len(df)
    dois_validos = 0
    sin_doi = 0
    if not df.empty and "DOI" in df.columns:
        dois_validos = int(df["DOI"].astype(str).map(lambda doi: doi_es_valido(limpiar_doi(doi))).sum())
        sin_doi = int((df["DOI"].astype(str).str.strip() == "").sum())

    duplicados = 0
    if not df.empty:
        dois = df.get("DOI", pd.Series(dtype=str)).astype(str).map(lambda doi: limpiar_doi(doi).lower())
        titulos = df.get("Nombre del Articulo", pd.Series(dtype=str)).astype(str).str.lower().str.strip()
        duplicados = int((dois[dois != ""].duplicated().sum()) + (titulos[titulos != ""].duplicated().sum()))

    analisis_tesis = st.session_state.get("analisis_tesis_pdf")
    comparacion = generar_tabla_comparacion_tesis_articulos(df, analisis_tesis) if not df.empty else pd.DataFrame()
    citados = int((comparacion["Estado"] == "Citado").sum()) if not comparacion.empty else 0
    falta_integrar = int((comparacion["Estado"] == "Falta integrar").sum()) if not comparacion.empty else 0

    return {
        "total": total,
        "dois_validos": dois_validos,
        "sin_doi": sin_doi,
        "duplicados": duplicados,
        "citados": citados,
        "falta_integrar": falta_integrar,
    }


def mostrar_analisis_tesis_pdf():
    mostrar_titulo_modulo(
        "Tesis PDF",
        "Sube la tesis, extrae sus secciones académicas y detecta qué partes necesitan sustento bibliográfico.",
    )
    archivo_tesis = st.file_uploader(
        "Sube tu tesis en PDF",
        type=["pdf"],
        help=(
            "El sistema extrae el texto y reconoce automaticamente titulo, problema, "
            "objetivos, justificacion, estado del arte, marco teorico, metodologia, "
            "alcances y limitaciones."
        ),
        key="tesis_pdf",
    )

    if archivo_tesis is None:
        st.info("Sube un PDF para que tesis-doi reconozca la informacion principal de la tesis.")
        return

    if st.button("Reconocer informacion de la tesis", type="primary"):
        try:
            with st.spinner("Leyendo PDF y detectando secciones academicas..."):
                st.session_state["analisis_tesis_pdf"] = analizar_tesis_pdf(archivo_tesis)
        except ImportError as error:
            st.error(str(error))
        except ValueError as error:
            st.error(str(error))
        except Exception as error:
            st.error(f"No se pudo analizar la tesis: {error}")

    resultado = st.session_state.get("analisis_tesis_pdf")
    if not resultado:
        return

    secciones = resultado["secciones"]
    total_detectadas = sum(1 for datos in secciones.values() if datos["encontrado"])

    st.subheader("Informacion reconocida")
    st.text_input("Titulo detectado", value=resultado["titulo"], disabled=True)

    col_paginas, col_palabras, col_secciones = st.columns(3)
    col_paginas.metric("Paginas PDF", resultado["paginas"])
    col_palabras.metric("Palabras extraidas", resultado["palabras_extraidas"])
    col_secciones.metric("Secciones detectadas", f"{total_detectadas}/{len(secciones)}")

    st.subheader("Secciones academicas detectadas")
    for datos in secciones.values():
        estado = "detectada" if datos["encontrado"] else "requiere verificacion"
        with st.expander(f"{datos['nombre']} ({estado})", expanded=datos["encontrado"]):
            if datos["encontrado"]:
                st.write(datos["extracto"])
            else:
                st.warning(
                    "No se reconocio esta seccion con suficiente confianza. "
                    "Revisa si el PDF tiene encabezados distintos o texto escaneado."
                )

    st.subheader("Partes que necesitan citas academicas")
    st.dataframe(
        pd.DataFrame(resultado["necesidades_citas"]),
        use_container_width=True,
        hide_index=True,
    )

    st.download_button(
        "Descargar texto extraido de la tesis",
        data=resultado["texto_extraido"].encode("utf-8"),
        file_name="tesis_texto_extraido.txt",
        mime="text/plain",
    )


def mostrar_reporte_prisma(df_articulos):
    mostrar_titulo_modulo(
        "PRISMA 2020",
        "Configura criterios de revisión, clasifica artículos y genera conteos trazables para tu tesis.",
    )
    if df_articulos.empty:
        st.info("No hay artículos disponibles para generar el reporte PRISMA.")
        return

    analisis_tesis = st.session_state.get("analisis_tesis_pdf", {})
    titulo_detectado = analisis_tesis.get("titulo", "")
    tema_default = (
        titulo_detectado
        if titulo_detectado and titulo_detectado != "requiere verificacion"
        else "Sistema web ERP modular para PYMES aplicado a inventario, compras, producción y dashboard"
    )

    with st.form("formulario_prisma"):
        tema_investigacion = st.text_area(
            "Tema de investigación",
            value=tema_default,
        )
        objetivo_revision = st.text_area(
            "Objetivo de la revisión sistemática",
            value=(
                "Identificar estudios académicos que sustenten el desarrollo de un "
                "sistema web ERP modular para PYMES, la centralización de información, "
                "la trazabilidad operativa y el apoyo a la toma de decisiones."
            ),
        )
        variables = st.text_input(
            "Variables o ejes temáticos separados por coma",
            value="ERP modular, PYMES, trazabilidad, inventario, compras, producción, dashboard, toma de decisiones",
        )

        col_anio_inicio, col_anio_fin, col_otros = st.columns(3)
        with col_anio_inicio:
            anio_inicio = st.number_input(
                "Año inicio",
                min_value=1900,
                max_value=2100,
                value=2020,
                step=1,
            )
        with col_anio_fin:
            anio_fin = st.number_input(
                "Año fin",
                min_value=1900,
                max_value=2100,
                value=2026,
                step=1,
            )
        with col_otros:
            registros_otros = st.number_input(
                "Registros por otros métodos",
                min_value=0,
                value=0,
                step=1,
            )

        requerir_texto_completo = st.checkbox(
            "Excluir si no hay acceso a texto completo",
            value=False,
            help=(
                "Si el archivo no tiene una columna de acceso a texto completo, "
                "el sistema marcará ese dato como no disponible y recomendará revisión manual."
            ),
        )
        generar_prisma = st.form_submit_button("Generar reporte PRISMA")

    if generar_prisma:
        variables_lista = [
            variable.strip()
            for variable in variables.split(",")
            if variable.strip()
        ]
        st.session_state["reporte_prisma"] = generar_reporte_prisma(
            df_articulos,
            tema_investigacion=tema_investigacion,
            objetivo_revision=objetivo_revision,
            anio_inicio=anio_inicio,
            anio_fin=anio_fin,
            variables=variables_lista,
            registros_otros_metodos=registros_otros,
            requerir_texto_completo=requerir_texto_completo,
        )

    reporte = st.session_state.get("reporte_prisma")
    if not reporte:
        return

    resumen = reporte["resumen_prisma"]
    col_identificados, col_cribados, col_incluidos = st.columns(3)
    col_identificados.metric(
        "Registros identificados",
        resumen["total_registros_identificados"],
    )
    col_cribados.metric("Registros cribados", resumen["registros_cribados"])
    col_incluidos.metric(
        "Estudios incluidos",
        resumen["estudios_incluidos_revision"],
    )

    st.subheader("Tabla de clasificación de artículos")
    st.dataframe(
        pd.DataFrame(reporte["articulos"]),
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Conteo PRISMA")
    st.json(resumen)

    st.subheader("Razones de exclusión")
    st.dataframe(
        pd.DataFrame(reporte["razones_exclusion"]),
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Diagrama PRISMA en Mermaid")
    st.code(reporte["diagrama_mermaid"], language="mermaid")

    st.subheader("Interpretación académica")
    st.write(reporte["interpretacion_academica"])

    st.download_button(
        "Descargar reporte PRISMA JSON",
        data=reporte_prisma_to_json(reporte),
        file_name="reporte_prisma_2020.json",
        mime="application/json",
    )


def mostrar_dashboard(df):
    mostrar_titulo_modulo(
        "Dashboard",
        "Vista rápida del estado de tu tesis, artículos, DOI, coincidencias y avance de revisión.",
    )
    metricas = obtener_metricas_dashboard(df)
    analisis_tesis = st.session_state.get("analisis_tesis_pdf")
    reporte_prisma = st.session_state.get("reporte_prisma", {})
    incluidos_prisma = reporte_prisma.get("resumen_prisma", {}).get("estudios_incluidos_revision", 0)

    mostrar_metricas(
        [
            ("Artículos", metricas["total"], "Registros cargados en la base local"),
            ("DOI válidos", metricas["dois_validos"], f"Sin DOI: {metricas['sin_doi']}"),
            ("Falta integrar", metricas["falta_integrar"], "Útiles, pero no detectados en la tesis"),
            ("Incluidos PRISMA", incluidos_prisma, "Último reporte generado"),
        ]
    )

    tesis_estado = "Tesis analizada" if analisis_tesis else "Tesis pendiente"
    tesis_tipo = "success" if analisis_tesis else "warning"
    articulos_tipo = "success" if metricas["total"] else "warning"
    prisma_tipo = "success" if reporte_prisma else "neutral"
    mostrar_chips_estado(
        [
            (tesis_estado, tesis_tipo),
            (f"{metricas['total']} artículos cargados", articulos_tipo),
            (f"{metricas['duplicados']} posibles duplicados", "danger" if metricas["duplicados"] else "neutral"),
            ("PRISMA generado" if reporte_prisma else "PRISMA pendiente", prisma_tipo),
        ]
    )

    col_flujo, col_alertas = st.columns([1.1, .9])
    with col_flujo:
        st.markdown('<div class="td-band">', unsafe_allow_html=True)
        st.subheader("Flujo recomendado")
        pasos = [
            ("Subir tesis", "Reconoce título, objetivos, metodología y secciones que requieren citas."),
            ("Cargar DOI", "Importa CSV o registra DOI para completar metadatos académicos."),
            ("Comparar", "Detecta artículos citados, faltantes, repetidos y pendientes."),
            ("Evaluar", "Decide incluir, excluir o revisar manualmente cada artículo."),
            ("Exportar", "Genera IEEE, BibTeX, Excel, CSV y reporte PRISMA JSON."),
        ]
        for indice, (titulo, detalle) in enumerate(pasos, start=1):
            st.markdown(
                f"""
                <div class="td-step">
                    <div class="td-step-index">{indice}</div>
                    <div>
                        <div class="td-step-title">{titulo}</div>
                        <div class="td-step-body">{detalle}</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)

    with col_alertas:
        st.markdown('<div class="td-band">', unsafe_allow_html=True)
        st.subheader("Alertas de trabajo")
        if not analisis_tesis:
            st.warning("Sube el PDF de la tesis para habilitar comparación real contra el texto.")
        if metricas["sin_doi"]:
            st.info(f"{metricas['sin_doi']} artículos no tienen DOI. Completa DOI o fuente verificable.")
        if metricas["duplicados"]:
            st.error(f"Hay {metricas['duplicados']} posibles duplicados por DOI o título.")
        if metricas["total"] and not reporte_prisma:
            st.info("Genera PRISMA para documentar el proceso de selección.")
        if analisis_tesis and metricas["total"] and not metricas["falta_integrar"]:
            st.success("No hay artículos útiles pendientes de integrar según la comparación actual.")
        st.markdown("</div>", unsafe_allow_html=True)


def mostrar_busqueda_doi(df, fuente_datos):
    st.subheader("Buscar artículo por DOI")
    doi_busqueda = st.text_input("DOI para buscar", placeholder="10.1000/xyz123")

    if st.button("Buscar datos por DOI", type="primary"):
        doi_limpio = limpiar_doi(doi_busqueda)

        if not doi_limpio:
            st.warning("Ingresa un DOI para realizar la búsqueda.")
        elif not doi_es_valido(doi_limpio):
            st.warning("El texto ingresado no parece un DOI válido. Revisa el formato.")
        else:
            with st.spinner("Consultando Crossref y OpenAlex..."):
                resultado_doi = buscar_datos_por_doi(doi_limpio)

            for mensaje in resultado_doi.get("mensajes", []):
                mostrar_mensaje_api(mensaje)

            if resultado_doi.get("encontrado"):
                aplicar_datos_doi(
                    resultado_doi.get("crossref", {}),
                    resultado_doi.get("openalex", {}),
                )
                st.success("Datos encontrados. El formulario fue actualizado.")
            else:
                st.warning(
                    "No se encontraron datos automáticos o la API no respondió. "
                    "Puedes registrar el artículo manualmente."
                )
        st.session_state["form_doi"] = doi_limpio

    return df, fuente_datos


def mostrar_importacion_csv(df, fuente_datos):
    st.subheader("Importar CSV académico")
    archivo_scopus = st.file_uploader(
        "Selecciona un CSV exportado desde Scopus u otra base académica",
        type=["csv"],
        help="El sistema detecta columnas como Authors, Document title, Year, DOI, Abstract y keywords aunque cambien ligeramente de nombre.",
    )

    if archivo_scopus is not None:
        try:
            with st.spinner("Procesando CSV académico..."):
                resultado_importacion = procesar_csv_scopus(archivo_scopus)
                df_importado = resultado_importacion["dataframe"]
                df_importado = detectar_duplicados_importacion(df_importado, df)

            total_duplicados = int(df_importado["_duplicado"].sum())
            total_validos = len(df_importado) - total_duplicados
            mostrar_metricas(
                [
                    ("Procesados", len(df_importado), "Registros leídos del CSV"),
                    ("Listos", total_validos, "Sin duplicados detectados"),
                    ("Duplicados", total_duplicados, "No se importarán automáticamente"),
                    ("Columnas", len(resultado_importacion["column_mapping"]), "Campos reconocidos"),
                ]
            )

            with st.expander("Columnas detectadas"):
                st.json(resultado_importacion["column_mapping"])

            if total_duplicados:
                st.warning(
                    "Se detectaron duplicados por DOI o similitud de título. "
                    "Esos registros no se importarán."
                )

            columnas_preview = COLUMNAS + ["_duplicado", "_motivo_duplicado"]
            st.dataframe(
                df_importado[columnas_preview].head(100),
                use_container_width=True,
                hide_index=True,
            )

            if st.button("Importar registros válidos desde CSV", type="primary"):
                df_validos = df_importado[~df_importado["_duplicado"]][COLUMNAS]
                registros = df_validos.to_dict("records")
                guardado, fuente_guardado, error_guardado = agregar_articulos_principal(
                    registros,
                    fuente_datos,
                )

                if not registros:
                    st.warning("No hay registros nuevos para importar.")
                elif guardado:
                    st.success(f"Se importaron {len(registros)} artículos en {fuente_guardado}.")
                    df, fuente_datos, _ = cargar_articulos_principal()
                else:
                    st.error(error_guardado or "No se pudo importar el CSV.")
        except ValueError as error:
            st.error(str(error))
        except Exception as error:
            st.error(f"No se pudo procesar el CSV: {error}")

    return df, fuente_datos


def mostrar_formulario_articulo(df, fuente_datos):
    st.subheader("Registrar artículo manualmente")
    with st.form("formulario_articulo"):
        col1, col2 = st.columns(2)

        with col1:
            categoria = st.text_input("Categoría", key="form_categoria")
            nombre = st.text_area("Nombre del Articulo", key="form_nombre")
            autores = st.text_input("Autor(es)", key="form_autores")
            pais = st.text_input("Pais", key="form_pais")
            justificacion_categoria = st.text_area(
                "Justificación categoría",
                key="form_justificacion_categoria",
            )
            anio = st.number_input(
                "Año publicacion",
                min_value=0,
                max_value=2100,
                step=1,
                key="form_anio",
            )

        with col2:
            citas = st.number_input(
                "Cantidad de citas",
                min_value=0,
                step=1,
                key="form_citas",
            )
            tipo = st.selectbox(
                "Tipo documento",
                TIPOS_DOCUMENTO,
                key="form_tipo",
            )
            doi = st.text_input("DOI", key="form_doi")
            revista = st.text_input("Revista/Conferencia", key="form_revista")
            col_volumen, col_numero = st.columns(2)
            with col_volumen:
                volumen = st.text_input("Volumen", key="form_volumen")
            with col_numero:
                numero = st.text_input("Número", key="form_numero")
            paginas = st.text_input("Páginas o número de artículo", key="form_paginas")
            url = st.text_input("URL", key="form_url")
            editorial = st.text_input("Editorial", key="form_editorial")
            palabras = st.text_area("Palabras Indexadas", key="form_palabras")
            resumen = st.text_area("Resumen 3 lineas", key="form_resumen")
            permitir_titulo_similar = st.checkbox(
                "Guardar aunque se detecte título parecido",
                key="form_permitir_titulo_similar",
                help="Úsalo solo si revisaste la advertencia y confirmas que no es el mismo artículo.",
            )

        enviar = st.form_submit_button("Guardar artículo")

    if enviar:
        nuevo_articulo = {
            "Categoria": categoria.strip(),
            "Nombre del Articulo": nombre.strip(),
            "Autor(es)": autores.strip(),
            "Pais": pais.strip(),
            "Año publicacion": convertir_entero(anio),
            "Cantidad de citas": convertir_entero(citas),
            "Tipo documento": tipo,
            "DOI": limpiar_doi(doi),
            "Revista/Conferencia": revista.strip(),
            "Volumen": volumen.strip(),
            "Numero": numero.strip(),
            "Paginas": paginas.strip(),
            "URL": url.strip(),
            "Editorial": editorial.strip(),
            "Palabras Indexadas": palabras.strip(),
            "Resumen 3 lineas": resumen.strip(),
            "Justificación categoría": justificacion_categoria.strip(),
        }

        es_valido, tipo_mensaje, mensaje = validar_articulo(
            nuevo_articulo,
            df,
            permitir_titulo_similar=permitir_titulo_similar,
        )

        if not es_valido:
            if tipo_mensaje == "warning":
                st.warning(mensaje)
            else:
                st.error(mensaje)
        else:
            guardado, fuente_guardado, error_guardado = agregar_articulo_principal(
                nuevo_articulo,
                fuente_datos,
            )

            if not guardado:
                st.error(error_guardado or "No se pudo guardar el artículo.")
            else:
                if tipo_mensaje == "warning":
                    st.warning(mensaje)
                st.success(f"Artículo registrado correctamente en {fuente_guardado}.")
                df, fuente_datos, _ = cargar_articulos_principal()

    return df, fuente_datos


def mostrar_gestion_articulos(df, fuente_datos):
    mostrar_titulo_modulo(
        "Gestión de DOI y artículos",
        "Busca metadatos por DOI, importa CSV académicos y registra artículos con validación de duplicados.",
    )
    mostrar_chips_estado(
        [
            ("Validación DOI", "info"),
            ("Importación CSV", "neutral"),
            ("Duplicados", "warning"),
            ("Metadatos académicos", "success"),
        ]
    )

    tabs = st.tabs(["Buscar DOI", "Importar CSV", "Registrar manual", "Base local"])
    with tabs[0]:
        df, fuente_datos = mostrar_busqueda_doi(df, fuente_datos)
    with tabs[1]:
        df, fuente_datos = mostrar_importacion_csv(df, fuente_datos)
    with tabs[2]:
        df, fuente_datos = mostrar_formulario_articulo(df, fuente_datos)
    with tabs[3]:
        st.subheader("Artículos registrados")
        if df.empty:
            st.info("Todavía no hay artículos registrados.")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)

    return df, fuente_datos


def mostrar_comparacion_tesis_articulos(df):
    mostrar_titulo_modulo(
        "Comparación tesis-artículos",
        "Detecta artículos citados, útiles no integrados, repetidos y pendientes de revisión.",
    )
    if df.empty:
        st.info("Carga artículos para habilitar la comparación.")
        return

    analisis_tesis = st.session_state.get("analisis_tesis_pdf")
    if not analisis_tesis:
        st.warning("Sube y analiza el PDF de tesis para comparar contra el texto real.")

    comparacion = generar_tabla_comparacion_tesis_articulos(df, analisis_tesis)
    conteos = comparacion["Estado"].value_counts().to_dict()
    mostrar_metricas(
        [
            ("Citados", conteos.get("Citado", 0), "Detectados en el texto de la tesis"),
            ("Falta integrar", conteos.get("Falta integrar", 0), "Relevantes, pero no citados"),
            ("Duplicados", conteos.get("Duplicado", 0), "Revisar antes de exportar"),
            ("Pendientes", conteos.get("Pendiente", 0), "Requieren más datos"),
        ]
    )

    estado = st.multiselect(
        "Filtrar por estado",
        sorted(comparacion["Estado"].unique()),
        default=sorted(comparacion["Estado"].unique()),
    )
    relevancia = st.multiselect(
        "Filtrar por relevancia",
        sorted(comparacion["Relevancia"].unique()),
        default=sorted(comparacion["Relevancia"].unique()),
    )
    vista = comparacion[
        comparacion["Estado"].isin(estado) & comparacion["Relevancia"].isin(relevancia)
    ]
    st.dataframe(vista, use_container_width=True, hide_index=True)


def mostrar_evaluacion_articulos(df):
    mostrar_titulo_modulo(
        "Evaluación de artículos",
        "Revisa qué estudios conviene incluir, excluir o dejar como dudosos antes del reporte final.",
    )
    if df.empty:
        st.info("Carga artículos para habilitar la evaluación.")
        return

    reporte = st.session_state.get("reporte_prisma")
    if reporte:
        articulos = pd.DataFrame(reporte["articulos"])
        decisiones = sorted(articulos["decision"].unique())
        decision = st.multiselect("Filtrar por decisión", decisiones, default=decisiones)
        articulos = articulos[articulos["decision"].isin(decision)]
        st.dataframe(articulos, use_container_width=True, hide_index=True)
        return

    st.info("Aún no hay reporte PRISMA generado. Se muestra una evaluación preliminar por coincidencia con tesis.")
    comparacion = generar_tabla_comparacion_tesis_articulos(
        df,
        st.session_state.get("analisis_tesis_pdf"),
    )
    st.dataframe(comparacion, use_container_width=True, hide_index=True)


def mostrar_reportes_exportacion(df):
    mostrar_titulo_modulo(
        "Reportes y exportación",
        "Filtra artículos y exporta tablas, referencias IEEE, BibTeX y archivos listos para tu tesis.",
    )
    if df.empty:
        st.info("Registra artículos para habilitar filtros y descargas.")
        return

    df_filtrado = filtrar_articulos(df)
    st.caption(f"Resultados filtrados: {len(df_filtrado)} de {len(df)} artículos")
    st.dataframe(df_filtrado, use_container_width=True, hide_index=True)

    col_excel, col_csv = st.columns(2)
    with col_excel:
        st.download_button(
            "Descargar copia en Excel",
            data=preparar_excel_descarga(df_filtrado),
            file_name="articulos_filtrados.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with col_csv:
        st.download_button(
            "Descargar datos filtrados en CSV",
            data=dataframe_to_csv(df_filtrado),
            file_name="articulos_filtrados.csv",
            mime="text/csv",
        )

    st.subheader("Referencias bibliográficas")
    col_formato, col_et_al, col_limite = st.columns([1, 1, 1])

    with col_formato:
        formato_ieee = st.selectbox(
            "Formato de archivo",
            ["TXT", "DOCX", "CSV", "BibTeX"],
        )

    with col_et_al:
        usar_et_al = st.checkbox(
            "Usar et al. en muchos autores",
            value=False,
        )

    with col_limite:
        limite_et_al = st.number_input(
            "Límite para et al.",
            min_value=2,
            max_value=20,
            value=6,
            step=1,
            disabled=not usar_et_al,
        )

    try:
        archivo_ieee, mime_ieee, contenido_ieee = preparar_exportacion_referencias(
            df_filtrado,
            formato_ieee,
            usar_et_al=usar_et_al,
            limite_et_al=limite_et_al,
        )
        st.download_button(
            "Exportar referencias",
            data=contenido_ieee,
            file_name=archivo_ieee,
            mime=mime_ieee,
        )
    except ImportError:
        st.error(
            "No se pudo generar el DOCX porque falta la dependencia python-docx. "
            "Instálala con: pip install python-docx"
        )


def mostrar_sidebar(df):
    st.sidebar.title("Tesis-DOI")
    st.sidebar.caption("Gestión documental para tesis y revisión académica")
    modulo = st.sidebar.radio(
        "Módulo",
        [
            "Dashboard",
            "Tesis PDF",
            "Gestión DOI",
            "Comparación",
            "Evaluación",
            "PRISMA",
            "Reportes",
        ],
    )

    metricas = obtener_metricas_dashboard(df)
    st.sidebar.divider()
    st.sidebar.metric("Artículos", metricas["total"])
    st.sidebar.metric("DOI válidos", metricas["dois_validos"])
    st.sidebar.metric("Falta integrar", metricas["falta_integrar"])
    st.sidebar.caption("Flujo sugerido: tesis, DOI, comparación, evaluación, PRISMA y exportación.")
    return modulo


def main_legacy():
    st.set_page_config(page_title="Gestor de Artículos Académicos", layout="wide")
    st.title("Gestor de Artículos Académicos")

    try:
        crear_excel_si_no_existe()
    except RuntimeError as error:
        st.error(str(error))
        st.stop()

    inicializar_estado_formulario()
    df, fuente_datos, _ = cargar_articulos_principal()
    st.success("Base de datos local activa: data/articulos.xlsx")

    mostrar_analisis_tesis_pdf()

    st.header("1. Buscar artículo por DOI")
    doi_busqueda = st.text_input("DOI para buscar", placeholder="10.1000/xyz123")

    if st.button("Buscar datos por DOI", type="primary"):
        doi_limpio = limpiar_doi(doi_busqueda)

        if not doi_limpio:
            st.warning("Ingresa un DOI para realizar la búsqueda.")
        elif not doi_es_valido(doi_limpio):
            st.warning("El texto ingresado no parece un DOI válido. Revisa el formato.")
        else:
            with st.spinner("Consultando Crossref y OpenAlex..."):
                resultado_doi = buscar_datos_por_doi(doi_limpio)

            for mensaje in resultado_doi.get("mensajes", []):
                mostrar_mensaje_api(mensaje)

            if resultado_doi.get("encontrado"):
                aplicar_datos_doi(
                    resultado_doi.get("crossref", {}),
                    resultado_doi.get("openalex", {}),
                )
                st.success("Datos encontrados. El formulario fue actualizado.")
            else:
                st.warning(
                    "No se encontraron datos automáticos o la API no respondió. "
                    "Puedes registrar el artículo manualmente."
                )
        st.session_state["form_doi"] = doi_limpio

    st.header("2. Importar CSV de Scopus")
    archivo_scopus = st.file_uploader(
        "Selecciona un CSV exportado desde Scopus",
        type=["csv"],
        help="El sistema detecta columnas como Authors, Document title, Year, DOI, Abstract y keywords aunque cambien ligeramente de nombre.",
    )

    if archivo_scopus is not None:
        try:
            with st.spinner("Procesando CSV de Scopus..."):
                resultado_importacion = procesar_csv_scopus(archivo_scopus)
                df_importado = resultado_importacion["dataframe"]
                df_importado = detectar_duplicados_importacion(df_importado, df)

            total_duplicados = int(df_importado["_duplicado"].sum())
            total_validos = len(df_importado) - total_duplicados
            col_total, col_validos, col_dup = st.columns(3)
            col_total.metric("Registros procesados", len(df_importado))
            col_validos.metric("Listos para importar", total_validos)
            col_dup.metric("Duplicados detectados", total_duplicados)

            with st.expander("Columnas detectadas"):
                st.json(resultado_importacion["column_mapping"])

            if total_duplicados:
                st.warning(
                    "Se detectaron duplicados por DOI o similitud de título. "
                    "Esos registros no se importarán."
                )

            columnas_preview = COLUMNAS + ["_duplicado", "_motivo_duplicado"]
            st.dataframe(
                df_importado[columnas_preview].head(100),
                use_container_width=True,
                hide_index=True,
            )

            if st.button("Importar registros válidos desde Scopus", type="primary"):
                df_validos = df_importado[~df_importado["_duplicado"]][COLUMNAS]
                registros = df_validos.to_dict("records")
                guardado, fuente_guardado, error_guardado = agregar_articulos_principal(
                    registros,
                    fuente_datos,
                )

                if not registros:
                    st.warning("No hay registros nuevos para importar.")
                elif guardado:
                    st.success(
                        f"Se importaron {len(registros)} artículos en {fuente_guardado}."
                    )
                    df, fuente_datos, _ = cargar_articulos_principal()
                else:
                    st.error(error_guardado or "No se pudo importar el CSV.")
        except ValueError as error:
            st.error(str(error))
        except Exception as error:
            st.error(f"No se pudo procesar el CSV de Scopus: {error}")

    st.header("3. Registrar artículo")
    with st.form("formulario_articulo"):
        col1, col2 = st.columns(2)

        with col1:
            categoria = st.text_input("Categoría", key="form_categoria")
            nombre = st.text_area("Nombre del Articulo", key="form_nombre")
            autores = st.text_input("Autor(es)", key="form_autores")
            pais = st.text_input("Pais", key="form_pais")
            justificacion_categoria = st.text_area(
                "Justificación categoría",
                key="form_justificacion_categoria",
            )
            anio = st.number_input(
                "Año publicacion",
                min_value=0,
                max_value=2100,
                step=1,
                key="form_anio",
            )

        with col2:
            citas = st.number_input(
                "Cantidad de citas",
                min_value=0,
                step=1,
                key="form_citas",
            )
            tipo = st.selectbox(
                "Tipo documento",
                TIPOS_DOCUMENTO,
                key="form_tipo",
            )
            doi = st.text_input("DOI", key="form_doi")
            revista = st.text_input("Revista/Conferencia", key="form_revista")
            col_volumen, col_numero = st.columns(2)
            with col_volumen:
                volumen = st.text_input("Volumen", key="form_volumen")
            with col_numero:
                numero = st.text_input("Número", key="form_numero")
            paginas = st.text_input("Páginas o número de artículo", key="form_paginas")
            url = st.text_input("URL", key="form_url")
            editorial = st.text_input("Editorial", key="form_editorial")
            palabras = st.text_area("Palabras Indexadas", key="form_palabras")
            resumen = st.text_area("Resumen 3 lineas", key="form_resumen")
            permitir_titulo_similar = st.checkbox(
                "Guardar aunque se detecte título parecido",
                key="form_permitir_titulo_similar",
                help="Úsalo solo si revisaste la advertencia y confirmas que no es el mismo artículo.",
            )

        enviar = st.form_submit_button("Guardar artículo")

    if enviar:
        nuevo_articulo = {
            "Categoria": categoria.strip(),
            "Nombre del Articulo": nombre.strip(),
            "Autor(es)": autores.strip(),
            "Pais": pais.strip(),
            "Año publicacion": convertir_entero(anio),
            "Cantidad de citas": convertir_entero(citas),
            "Tipo documento": tipo,
            "DOI": limpiar_doi(doi),
            "Revista/Conferencia": revista.strip(),
            "Volumen": volumen.strip(),
            "Numero": numero.strip(),
            "Paginas": paginas.strip(),
            "URL": url.strip(),
            "Editorial": editorial.strip(),
            "Palabras Indexadas": palabras.strip(),
            "Resumen 3 lineas": resumen.strip(),
            "Justificación categoría": justificacion_categoria.strip(),
        }

        es_valido, tipo_mensaje, mensaje = validar_articulo(
            nuevo_articulo,
            df,
            permitir_titulo_similar=permitir_titulo_similar,
        )

        if not es_valido:
            if tipo_mensaje == "warning":
                st.warning(mensaje)
            else:
                st.error(mensaje)
        else:
            guardado, fuente_guardado, error_guardado = agregar_articulo_principal(
                nuevo_articulo,
                fuente_datos,
            )

            if not guardado:
                st.error(error_guardado or "No se pudo guardar el artículo.")
            else:
                if tipo_mensaje == "warning":
                    st.warning(mensaje)
                st.success(f"Artículo registrado correctamente en {fuente_guardado}.")
                df, fuente_datos, _ = cargar_articulos_principal()

    st.header("4. Artículos registrados")
    if df.empty:
        st.info("Todavía no hay artículos registrados.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)

    st.header("5. Filtros y exportación")
    if df.empty:
        st.info("Registra artículos para habilitar filtros y descargas.")
        return

    df_filtrado = filtrar_articulos(df)
    st.caption(f"Resultados filtrados: {len(df_filtrado)} de {len(df)} artículos")
    st.dataframe(df_filtrado, use_container_width=True, hide_index=True)

    col_excel, col_csv = st.columns(2)

    with col_excel:
        st.download_button(
            "Descargar copia en Excel",
            data=preparar_excel_descarga(df_filtrado),
            file_name="articulos_filtrados.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with col_csv:
        st.download_button(
            "Descargar datos filtrados en CSV",
            data=dataframe_to_csv(df_filtrado),
            file_name="articulos_filtrados.csv",
            mime="text/csv",
        )

    st.subheader("Referencias bibliográficas IEEE")
    col_formato, col_et_al, col_limite = st.columns([1, 1, 1])

    with col_formato:
        formato_ieee = st.selectbox(
            "Formato de archivo",
            ["TXT", "DOCX", "CSV", "BibTeX"],
        )

    with col_et_al:
        usar_et_al = st.checkbox(
            "Usar et al. en muchos autores",
            value=False,
        )

    with col_limite:
        limite_et_al = st.number_input(
            "Límite para et al.",
            min_value=2,
            max_value=20,
            value=6,
            step=1,
            disabled=not usar_et_al,
        )

    try:
        archivo_ieee, mime_ieee, contenido_ieee = preparar_exportacion_referencias(
            df_filtrado,
            formato_ieee,
            usar_et_al=usar_et_al,
            limite_et_al=limite_et_al,
        )
        st.download_button(
            "Exportar referencias IEEE",
            data=contenido_ieee,
            file_name=archivo_ieee,
            mime=mime_ieee,
        )
    except ImportError:
        st.error(
            "No se pudo generar el DOCX porque falta la dependencia python-docx. "
            "Instálala con: pip install python-docx"
        )

    mostrar_reporte_prisma(df_filtrado)


def main():
    st.set_page_config(page_title="Tesis-DOI", layout="wide")
    inyectar_estilos_ui()
    st.title("Tesis-DOI")
    st.caption("Asistente académico para tesis, DOI, referencias, comparación documental y PRISMA 2020.")

    try:
        crear_excel_si_no_existe()
    except RuntimeError as error:
        st.error(str(error))
        st.stop()

    inicializar_estado_formulario()
    df, fuente_datos, _ = cargar_articulos_principal()
    modulo = mostrar_sidebar(df)

    if modulo == "Dashboard":
        mostrar_dashboard(df)
    elif modulo == "Tesis PDF":
        mostrar_analisis_tesis_pdf()
    elif modulo == "Gestión DOI":
        mostrar_gestion_articulos(df, fuente_datos)
    elif modulo == "Comparación":
        mostrar_comparacion_tesis_articulos(df)
    elif modulo == "Evaluación":
        mostrar_evaluacion_articulos(df)
    elif modulo == "PRISMA":
        mostrar_reporte_prisma(df)
    elif modulo == "Reportes":
        mostrar_reportes_exportacion(df)


if __name__ == "__main__":
    main()
