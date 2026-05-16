# Gestor de Artículos Académicos

Aplicación simple en Python y Streamlit para registrar artículos académicos de una revisión sistemática. Los datos se guardan localmente en un archivo Excel llamado `articulos.xlsx`.

## Instalación

```bash
pip install -r requirements.txt
```

## Ejecución

Desde la carpeta del proyecto:

```bash
streamlit run app.py
```

## Base de datos

La base de datos local es:

```text
data/articulos.xlsx
```

Si el archivo no existe, la aplicación lo crea automáticamente con las columnas necesarias.

## Búsqueda por DOI

La sección **Buscar artículo por DOI** consulta:

- Crossref: nombre del artículo, autores, año de publicación, tipo de documento y DOI.
- OpenAlex: cantidad de citas y conceptos o palabras indexadas disponibles.

Si alguna API no responde o no encuentra datos, la aplicación muestra un mensaje amigable y permite completar el registro manualmente.

## Validación de duplicados

Antes de guardar un artículo, el sistema valida:

- Si el DOI ya existe, no guarda el registro y muestra un error.
- Si no hay DOI, o aunque exista uno nuevo, compara el título contra los artículos guardados.
- La comparación normaliza los títulos convirtiendo a minúsculas, quitando tildes, signos de puntuación y espacios dobles.
- Si la similitud del título es mayor o igual al 90%, muestra **Posible artículo duplicado** y evita guardar el registro.

## Funciones principales

- Registrar artículos manualmente.
- Completar campos usando DOI.
- Consultar todos los artículos guardados.
- Buscar por palabra clave.
- Filtrar por categoría, año de publicación, tipo de documento y país.
- Descargar el Excel actualizado.
- Descargar los datos filtrados en CSV.
