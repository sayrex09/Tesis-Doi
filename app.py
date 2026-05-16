from io import BytesIO

import pandas as pd
import streamlit as st

from services.category_service import clasificar_categoria_articulo
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
from services.scopus_import_service import (
    detectar_duplicados_importacion,
    procesar_csv_scopus,
)


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


def main():
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


if __name__ == "__main__":
    main()
