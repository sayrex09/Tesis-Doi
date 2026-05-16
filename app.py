from io import BytesIO

import pandas as pd
import streamlit as st

from services.doi_service import buscar_en_crossref, buscar_en_openalex, limpiar_doi
from services.duplicate_service import buscar_titulo_similar, existe_doi
from services.excel_service import (
    EXCEL_PATH,
    agregar_articulo,
    cargar_articulos,
    crear_excel_si_no_existe,
    obtener_columnas,
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

    st.session_state["form_citas"] = convertir_entero(
        datos_openalex.get("Cantidad de citas", 0)
    )
    if datos_openalex.get("Palabras Indexadas"):
        st.session_state["form_palabras"] = datos_openalex["Palabras Indexadas"]


def validar_articulo(nuevo_articulo, df_actual):
    nombre = str(nuevo_articulo.get("Nombre del Articulo", "")).strip()
    doi = limpiar_doi(nuevo_articulo.get("DOI", ""))

    if not nombre:
        return False, "error", "El nombre del artículo es obligatorio."

    if doi and existe_doi(df_actual, doi):
        return False, "error", "El DOI ingresado ya existe en el Excel."

    titulo_similar = buscar_titulo_similar(df_actual, nombre, umbral=0.90)
    if titulo_similar:
        similitud = titulo_similar["similitud"] * 100
        mensaje = (
            "Posible artículo duplicado. "
            f"Coincide {similitud:.1f}% con: {titulo_similar['titulo']}"
        )
        return False, "warning", mensaje

    return True, "success", "Artículo válido."


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

    col1, col2, col3, col4 = st.columns(4)

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

    return df_filtrado


def preparar_excel_descarga():
    buffer = BytesIO()
    df = cargar_articulos()
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
    df = cargar_articulos()

    st.header("1. Buscar artículo por DOI")
    doi_busqueda = st.text_input("DOI para buscar", placeholder="10.1000/xyz123")

    if st.button("Buscar datos por DOI", type="primary"):
        doi_limpio = limpiar_doi(doi_busqueda)

        if not doi_limpio:
            st.warning("Ingresa un DOI para realizar la búsqueda.")
        else:
            datos_crossref = buscar_en_crossref(doi_limpio)
            datos_openalex = buscar_en_openalex(doi_limpio)

            encontro_crossref = any(
                datos_crossref.get(campo)
                for campo in ["Nombre del Articulo", "Autor(es)", "Año publicacion"]
            )
            encontro_openalex = bool(
                datos_openalex.get("Cantidad de citas")
                or datos_openalex.get("Palabras Indexadas")
            )

            if encontro_crossref or encontro_openalex:
                aplicar_datos_doi(datos_crossref, datos_openalex)
                st.success("Datos encontrados. El formulario fue actualizado.")
            else:
                st.warning(
                    "No se encontraron datos automáticos o la API no respondió. "
                    "Puedes registrar el artículo manualmente."
                )
                st.session_state["form_doi"] = doi_limpio

    st.header("2. Registrar artículo")
    with st.form("formulario_articulo"):
        col1, col2 = st.columns(2)

        with col1:
            categoria = st.text_input("Categoría", key="form_categoria")
            nombre = st.text_area("Nombre del Articulo", key="form_nombre")
            autores = st.text_input("Autor(es)", key="form_autores")
            pais = st.text_input("Pais", key="form_pais")
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
        }

        es_valido, tipo_mensaje, mensaje = validar_articulo(nuevo_articulo, df)

        if not es_valido:
            if tipo_mensaje == "warning":
                st.warning(mensaje)
            else:
                st.error(mensaje)
        elif agregar_articulo(nuevo_articulo):
            st.success("Artículo registrado correctamente.")
            df = cargar_articulos()
        else:
            st.error("No se pudo guardar el artículo. Revisa el archivo Excel.")

    st.header("3. Artículos registrados")
    if df.empty:
        st.info("Todavía no hay artículos registrados.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)

    st.header("4. Filtros y exportación")
    if df.empty:
        st.info("Registra artículos para habilitar filtros y descargas.")
        return

    df_filtrado = filtrar_articulos(df)
    st.caption(f"Resultados filtrados: {len(df_filtrado)} de {len(df)} artículos")
    st.dataframe(df_filtrado, use_container_width=True, hide_index=True)

    col_excel, col_csv = st.columns(2)

    with col_excel:
        st.download_button(
            "Descargar Excel actualizado",
            data=preparar_excel_descarga(),
            file_name=EXCEL_PATH.name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with col_csv:
        csv = df_filtrado.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "Descargar datos filtrados en CSV",
            data=csv,
            file_name="articulos_filtrados.csv",
            mime="text/csv",
        )


if __name__ == "__main__":
    main()
