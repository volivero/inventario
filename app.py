
import io
import uuid
from datetime import datetime

import streamlit as st
import pandas as pd

import gspread
from google.oauth2.service_account import Credentials
from gspread_dataframe import set_with_dataframe
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

import mimetypes



# --------------------------
# Configuración de página
# --------------------------
st.set_page_config(
    page_title="Inventario sencillo (Sheets + Drive)",
    page_icon="📦",
    layout="wide",
)

st.title("📦 Sistema de Inventario (Google Sheets + Imágenes en Drive)")
st.caption("Campos mínimos: Cantidad, Descripción, Observación e Imagen.")


# --------------------------
# Utilidades de credenciales
# --------------------------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def get_credentials():
    # Desde .streamlit/secrets.toml
    info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return creds

@st.cache_resource(show_spinner=False)
def get_clients():
    creds = get_credentials()
    gc = gspread.authorize(creds)
    drive = build("drive", "v3", credentials=creds)
    return gc, drive

gc, drive = get_clients()


# --------------------------
# Parámetros de la hoja
# --------------------------
SHEET_ID = st.secrets["sheets"]["sheet_id"]
WS_NAME  = st.secrets["sheets"]["worksheet_name"]

# Carpeta de Drive para imágenes (opcional)
DRIVE_FOLDER_ID = st.secrets.get("drive", {}).get("folder_id", "").strip()


# --------------------------
# Helpers de Google Sheets
# --------------------------
def open_or_create_worksheet(sheet_id: str, ws_name: str):
    sh = gc.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(ws_name)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=ws_name, rows=1000, cols=10)
        ws.append_row(["id", "timestamp", "cantidad", "descripcion", "observacion", "imagen_url", "drive_file_id"])
    # Asegurar encabezados
    headers = ws.row_values(1)
    expected = ["id", "timestamp", "cantidad", "descripcion", "observacion", "imagen_url", "drive_file_id"]
    if headers != expected:
        ws.update("A1:G1", [expected])
    return ws

@st.cache_data(show_spinner=False, ttl=60)
def read_inventory_df() -> pd.DataFrame:
    ws = open_or_create_worksheet(SHEET_ID, WS_NAME)
    data = ws.get_all_records()
    df = pd.DataFrame(data)
    if df.empty:
        df = pd.DataFrame(columns=["id", "timestamp", "cantidad", "descripcion", "observacion", "imagen_url", "drive_file_id"])
    # tipos
    if "cantidad" in df.columns:
        df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0).astype(int)
    return df

def append_row_to_sheet(row: dict):
    ws = open_or_create_worksheet(SHEET_ID, WS_NAME)
    values = [
        row.get("id", ""),
        row.get("timestamp", ""),
        row.get("cantidad", 0),
        row.get("descripcion", ""),
        row.get("observacion", ""),
        row.get("imagen_url", ""),
        row.get("drive_file_id", "")
    ]
    print("➡️ Guardando fila en Google Sheets:", values)   # debug
    ws.append_row(values)
    print("✅ Fila guardada en Google Sheets")



# --------------------------
# Helpers de Google Drive
# --------------------------
def upload_image_to_drive(file_obj, filename: str, folder_id: str, mime_type: str | None = None) -> tuple[str, str]:
    """
    Sube el archivo a Drive en folder_id, hace público el archivo y retorna:
    (public_view_url, file_id)
    """
    if not folder_id:
        raise RuntimeError("No hay DRIVE_FOLDER_ID configurado en secrets.toml")

    # Nombre "seguro"
    safe_name = filename.replace("/", "_").replace("\\", "_")

    # Determinar mimetype de forma robusta
    mt = mime_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"

    media = MediaIoBaseUpload(file_obj, mimetype=mt, resumable=False)
    metadata = {
        "name": safe_name,
        "parents": [folder_id],
    }

    created = drive.files().create(body=metadata, media_body=media, fields="id").execute()
    file_id = created["id"]

    # Permiso público (lector)
    drive.permissions().create(
        fileId=file_id,
        body={"role": "reader", "type": "anyone"},
    ).execute()

    public_url = f"https://drive.google.com/uc?export=view&id={file_id}"
    return public_url, file_id


# --------------------------
# UI: Tabs
# --------------------------
tab1, tab2 = st.tabs(["➕ Agregar ítem", "📋 Inventario"])

with tab1:
    st.subheader("Agregar un nuevo ítem al inventario")

    with st.form(key="add_form", clear_on_submit=True):
        c1, c2 = st.columns([1, 1])
        with c1:
            cantidad = st.number_input("Cantidad", min_value=0, step=1, value=1)
            descripcion = st.text_input("Descripción", placeholder="Ej. Módulo FV 550 Wp mono PERC")
        with c2:
            observacion = st.text_area("Observación", placeholder="Notas, estado, ubicación, proveedor, etc.", height=90)

        st.markdown("**Imagen del producto** (elige una opción):")
        cc1, cc2 = st.columns([1, 1])
        with cc1:
            img_file = st.file_uploader("Subir imagen (JPG/PNG)", type=["jpg", "jpeg", "png"])
            drive_enabled = bool(DRIVE_FOLDER_ID)
            if img_file and not drive_enabled:
                st.info("Para almacenar la imagen en Drive, configura `[drive].folder_id` en `secrets.toml`. Si no, usa un URL abajo.")
        with cc2:
            img_url_manual = st.text_input("...o pega un URL público de la imagen", placeholder="https://...")

        submitted = st.form_submit_button("Guardar ítem", use_container_width=True)

    # if submitted:
    #     # Validaciones
    #     if not descripcion.strip():
    #         st.error("La descripción es obligatoria.")
    #         st.stop()

    #     imagen_url = ""
    #     drive_file_id = ""

    #     try:
    #         if img_file and DRIVE_FOLDER_ID:
    #             # Subir a Drive
    #             file_bytes = io.BytesIO(img_file.read())
    #             unique_name = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{img_file.name}"
    #             imagen_url, drive_file_id = upload_image_to_drive(file_bytes, unique_name, DRIVE_FOLDER_ID)
    #         elif img_url_manual.strip():
    #             imagen_url = img_url_manual.strip()
    #         else:
    #             imagen_url = ""  # sin imagen

    #         row = {
    #             "id": str(uuid.uuid4())[:8],
    #             "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    #             "cantidad": int(cantidad),
    #             "descripcion": descripcion.strip(),
    #             "observacion": observacion.strip(),
    #             "imagen_url": imagen_url,
    #             "drive_file_id": drive_file_id,
    #         }
    #         append_row_to_sheet(row)
    #         st.success("Ítem guardado correctamente.")
    #         st.cache_data.clear()  # refrescar la tabla
    #     except Exception as e:
    #         st.error(f"Ocurrió un error guardando el ítem: {e}")

if submitted:
    if not descripcion.strip():
        st.error("La descripción es obligatoria.")
        st.stop()

    imagen_url = ""
    drive_file_id = ""

    try:
        if img_file and DRIVE_FOLDER_ID:
            # Subir a Drive con mimetype explícito
            file_bytes = io.BytesIO(img_file.read())
            unique_name = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{img_file.name}"
            imagen_url, drive_file_id = upload_image_to_drive(
                file_bytes,
                unique_name,
                DRIVE_FOLDER_ID,
                mime_type=getattr(img_file, "type", None)  # <- clave del fix
            )
        elif img_url_manual.strip():
            imagen_url = img_url_manual.strip()
        else:
            imagen_url = ""  # sin imagen

        row = {
            "id": str(uuid.uuid4())[:8],
            "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "cantidad": int(cantidad),
            "descripcion": descripcion.strip(),
            "observacion": observacion.strip(),
            "imagen_url": imagen_url,
            "drive_file_id": drive_file_id,
        }
        append_row_to_sheet(row)
        st.success("Ítem guardado correctamente.")
        st.cache_data.clear()  # refrescar tabla
    except Exception as e:
        st.error(f"Ocurrió un error guardando el ítem: {e}")



with tab2:
    st.subheader("Inventario")

    # Botón para forzar refresco desde Google Sheets
    if st.button("🔄 Actualizar inventario", use_container_width=True):
        st.cache_data.clear()

    df = read_inventory_df()

    if df.empty:
        st.info("No hay ítems en el inventario.")
    else:
        try:
            st.dataframe(
                df[["id", "timestamp", "cantidad", "descripcion", "observacion", "imagen_url"]],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "imagen_url": st.column_config.ImageColumn("Imagen", help="Vista desde URL pública"),
                    "descripcion": st.column_config.TextColumn("Descripción", width="medium"),
                    "observacion": st.column_config.TextColumn("Observación", width="large"),
                    "cantidad": st.column_config.NumberColumn("Cantidad", format="%d"),
                    "timestamp": st.column_config.TextColumn("Creado (UTC)"),
                    "id": st.column_config.TextColumn("ID"),
                },
            )
        except Exception:
            st.dataframe(
                df[["id", "timestamp", "cantidad", "descripcion", "observacion", "imagen_url"]],
                use_container_width=True,
                hide_index=True,
            )
            with st.expander("Vista rápida de imágenes"):
                g = df.dropna(subset=["imagen_url"])
                cols = st.columns(5)
                i = 0
                for _, r in g.iterrows():
                    with cols[i % 5]:
                        st.image(r["imagen_url"], caption=r["descripcion"], use_container_width=True)
                    i += 1

        # Botón para descargar CSV
        st.download_button(
            label="⬇️ Descargar CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name=f"inventario_{datetime.utcnow().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            use_container_width=True,
        )
