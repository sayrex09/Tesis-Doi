# Gestor de Artículos Académicos

Aplicación simple en Python y Streamlit para registrar artículos académicos de una revisión sistemática. La base principal es Google Sheets y, si no hay conexión o credenciales válidas, se usa el Excel local `data/articulos.xlsx` como respaldo.

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

La base de datos principal es Google Sheets:

```text
https://docs.google.com/spreadsheets/d/1keQ5XgJu-dHpIyhcHqmNXUc6GRiw3wp8XEeh2nWddfQ/edit
```

El respaldo local es:

```text
data/articulos.xlsx
```

Si Google Sheets no responde, la aplicación muestra un mensaje amigable y sigue trabajando con Excel local.

## Configuración de Google Sheets

1. Crea una cuenta de servicio en Google Cloud.
2. Descarga el JSON de credenciales.
3. Comparte el Google Sheets con el correo `client_email` de la cuenta de servicio como editor.
4. Copia `.streamlit/secrets.toml.example` como `.streamlit/secrets.toml`.
5. Pega los valores reales del JSON en `.streamlit/secrets.toml`.

Si `worksheet_name` queda vacío, la aplicación usará la primera pestaña del Google Sheets. Si indicas un nombre y no existe, la aplicación intentará crear esa pestaña.

No subas `.streamlit/secrets.toml` a Git. El archivo está ignorado en `.gitignore`.

## Búsqueda por DOI

La sección **Buscar artículo por DOI** consulta:

- Crossref: nombre del artículo, autores, año de publicación, tipo de documento y DOI.
- OpenAlex: cantidad de citas y palabras indexadas disponibles.

El sistema acepta DOI escritos como texto simple, URL de `doi.org`, URL de `dx.doi.org`, `doi:10...` o `urn:doi:10...`. Si alguna API no responde o no encuentra datos, la aplicación muestra un mensaje amigable y permite completar el registro manualmente.

OpenAlex se consulta primero con las palabras clave actuales (`keywords`) y temas (`topics`). Si no existen, usa conceptos (`concepts`) como respaldo.

## Clasificación automática

Al buscar un artículo por DOI, la aplicación clasifica automáticamente la columna `Categoría` como:

- `Macro`: país, sector, industria, mercado, economía, políticas públicas o contexto nacional/internacional.
- `Meso`: empresas, organizaciones, gestión empresarial, SOC, ERP, procesos, toma de decisiones o ciberseguridad organizacional.
- `Micro`: algoritmos, modelos de IA, machine learning, deep learning, detección de amenazas, phishing, malware, datasets o frameworks técnicos.

La clasificación usa reglas sobre título, resumen, keywords, topics y concepts. También llena la columna `Justificación categoría`, que puede editarse manualmente antes de guardar.

## Importación CSV de Scopus

La sección **Importar CSV de Scopus** permite cargar archivos exportados desde Scopus y convertirlos al formato interno del sistema. La importación:

- Detecta columnas aunque cambien ligeramente de nombre, como `Authors`, `Document title`, `Year`, `Citation count`, `DOI`, `Abstract`, `Author keywords` e `Indexed keywords`.
- Limpia valores vacíos, `NaN`, caracteres especiales y espacios duplicados.
- Normaliza tipo de documento, citas, DOI, país, palabras clave y resumen.
- Clasifica automáticamente cada registro como `Macro`, `Meso`, `Micro` o `Pendiente`.
- Genera `Justificación categoría`.
- Detecta duplicados por DOI y similitud de título antes de guardar.
- Guarda registros válidos en Google Sheets o, si falla la conexión, en Excel local.

Para archivos grandes, el guardado se hace por lotes y la detección de títulos similares usa un filtrado previo para evitar comparaciones innecesarias.

## Validación de duplicados

Antes de guardar un artículo, el sistema valida:

- Si el DOI ya existe, no guarda el registro y muestra un error.
- Si no hay DOI, o aunque exista uno nuevo, compara el título contra los artículos guardados.
- La comparación normaliza los títulos convirtiendo a minúsculas, quitando tildes, signos de puntuación y espacios dobles.
- Si la similitud del título es mayor o igual al 90%, muestra **Posible artículo duplicado**.
- Si confirmas manualmente que no es el mismo artículo, puedes activar la opción para guardar aunque exista advertencia por título parecido.

## Copias de seguridad

Antes de sobrescribir el Excel al guardar un artículo, el sistema crea una copia en:

```text
data/backups/
```

Esto ayuda a recuperar la información si el archivo se edita accidentalmente o se cierra mal Excel.

## Funciones principales

- Registrar artículos manualmente.
- Completar campos usando DOI.
- Importar CSV exportado desde Scopus.
- Consultar todos los artículos guardados.
- Buscar por palabra clave.
- Filtrar por categoría, año de publicación, tipo de documento, país y cantidad de citas.
- Descargar una copia en Excel.
- Descargar los datos filtrados en CSV.
