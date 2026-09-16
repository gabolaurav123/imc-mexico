"""Generate internal/public PDFs from the same immutable sheet snapshot."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate,
                               Spacer, Table, TableStyle)
from .services import public_web_references, web_research_for_provenance

NAVY = colors.HexColor("#000033")
ORANGE = colors.HexColor("#E38C1A")
BLUE = colors.HexColor("#0095D9")
SILVER = colors.HexColor("#BCBDBF")
CHARCOAL = colors.HexColor("#231F20")
MUTED = CHARCOAL
LIGHT = colors.Color(0.97, 0.97, 0.975)
LOGO_PATH = Path(__file__).resolve().parent / "static" / "portal" / "imc-logo.png"
LABELS = {
    "brand": "Marca", "model": "Modelo", "year": "Año", "serial": "Número de serie",
    "hours": "Horas de uso", "location": "Ubicación", "condition": "Condición declarada",
    "power": "Potencia", "weight": "Peso", "capacity": "Capacidad", "dimensions": "Dimensiones",
    "fuel": "Combustible", "kilometers": "Kilometraje", "engine": "Motor", "transmission": "Transmisión",
}
AVAILABILITY = {"available": "Disponible", "reserved": "Reservada", "sold": "Vendida", "withdrawn": "Retirada"}
PRIVATE_FIELDS = {"serial", "vin", "plate_transcription", "plate_kind", "plate_type", "no_plate", "notes",
                  "document", "owner_email", "owner_phone", "email", "phone"}


def build_pdf(machine, data, assets, public=False, version=None):
    """Return PDF bytes. Public mode always requires an explicit version allowlist.

    Calling views must check authentication or active Publication token. This
    function independently filters images, serials, notes and contact details.
    """
    snapshot = version.data if version else {}
    values = dict(snapshot.get("data", data))
    title = snapshot.get("title", machine.title)
    provenance = snapshot.get("provenance", getattr(machine, "provenance", {}))
    reference_snapshot = snapshot if version else {"data": values, "provenance": provenance,
                                                   "web_research": web_research_for_provenance(provenance)}
    web_references = public_web_references(reference_snapshot)
    reference_by_field = {item["field"]: item for item in web_references}
    asset_list = list(assets)
    if version:
        allowed = set(str(a) for a in snapshot.get("asset_ids", []))
        asset_list = [a for a in asset_list if str(a.pk) in allowed]
    if public:
        if not version:
            raise ValueError("Una ficha de difusión requiere una versión autorizada.")
        public_ids = {str(a) for a in snapshot.get("public_asset_ids", [])}
        asset_list = [a for a in asset_list if str(a.pk) in public_ids and a.public_authorized
                      and a.purpose not in {"plate", "document"}]
        for field in PRIVATE_FIELDS:
            values.pop(field, None)
        if not snapshot.get("contact_authorized"):
            values.pop("contact_public", None)
    else:
        # Documents belong to the private asset viewer, never the PDF gallery.
        asset_list = [a for a in asset_list if a.purpose != "document"]
    asset_list.sort(key=lambda a: (not a.is_cover, a.position, str(a.pk)))
    output = BytesIO()
    # Use the unmodified official file; the canvas preserves its original ratio
    # and alpha channel. Source assets ship with the application, independently
    # of static URL hashing or storage permissions for user-uploaded photographs.
    brand_logo = ImageReader(str(LOGO_PATH))
    document = SimpleDocTemplate(output, pagesize=A4, rightMargin=19 * mm, leftMargin=19 * mm,
                                 topMargin=44 * mm, bottomMargin=21 * mm,
                                 title=f"{machine.folio} - {title}", author="IMC México",
                                 pageCompression=1)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="IMCTitle", fontName="Helvetica-Bold", fontSize=25,
                              leading=29, textColor=NAVY, spaceAfter=10, wordWrap="CJK"))
    styles.add(ParagraphStyle(name="IMCHeading", fontName="Helvetica-Bold", fontSize=12,
                              leading=16, textColor=NAVY, spaceBefore=15, spaceAfter=8, keepWithNext=True))
    styles.add(ParagraphStyle(name="IMCBody", fontName="Helvetica", fontSize=10,
                              leading=15, textColor=CHARCOAL, spaceAfter=8, wordWrap="CJK"))
    styles.add(ParagraphStyle(name="IMCSmall", fontName="Helvetica", fontSize=8,
                              leading=11, textColor=MUTED, spaceAfter=5, wordWrap="CJK"))
    styles.add(ParagraphStyle(name="IMCLabel", parent=styles["IMCSmall"], fontName="Helvetica-Bold"))

    def para(text, style="IMCBody"):
        # Never interpret owner-provided markup as ReportLab tags.
        clean = str(text or "").replace("\x00", "").replace("\r\n", "\n")
        return Paragraph(escape(clean).replace("\n", "<br/>"), styles[style])

    now = timezone.localtime(version.created_at if version else timezone.now())
    story = [para(title, "IMCTitle"),
             para(f"{machine.folio}  ·  Versión {version.number if version else machine.revision}  ·  {now:%d/%m/%Y}", "IMCSmall")]
    draft = not public and (not version or getattr(machine, "approved_version_id", None) != getattr(version, "pk", None))
    state = "FICHA PARA DIFUSIÓN" if public else "VERSIÓN INTERNA - DATOS PRIVADOS"
    if draft:
        state += "  /  PENDIENTE DE REVISIÓN"
    status_table = Table([[para(state, "IMCLabel")]], colWidths=[172 * mm])
    status_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHT),
                                      ("BOX", (0, 0), (-1, -1), 0.5, SILVER),
                                      ("LINEBEFORE", (0, 0), (0, -1), 2.5, BLUE),
                                      ("LEFTPADDING", (0, 0), (-1, -1), 10),
                                      ("TOPPADDING", (0, 0), (-1, -1), 9),
                                      ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story.extend([Spacer(1, 3 * mm), status_table, Spacer(1, 6 * mm)])
    images, unreadable = [], 0
    for asset in asset_list:
        if asset.kind != "image" or asset.processing_status != "ready" or not asset.preview:
            continue
        try:
            with asset.preview.open("rb") as stream:
                image_bytes = BytesIO(stream.read())
            picture = Image(image_bytes)
            ratio = min(82 * mm / picture.imageWidth, 59 * mm / picture.imageHeight)
            picture.drawWidth, picture.drawHeight = picture.imageWidth * ratio, picture.imageHeight * ratio
            picture.hAlign = "CENTER"
            label = "Placa de identificación - uso interno" if asset.purpose == "plate" else "Fotografía proporcionada por el anunciante"
            images.append([picture, Spacer(1, 2 * mm), para(label, "IMCSmall")])
        except (OSError, ValueError):
            unreadable += 1
    for index in range(0, len(images), 2):
        cells = images[index:index + 2]
        if len(cells) == 1:
            cells.append("")
        gallery = Table([cells], colWidths=[86 * mm, 86 * mm])
        gallery.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                    ("LEFTPADDING", (0, 0), (-1, -1), 2),
                                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
        story.append(gallery)
    if unreadable:
        story.append(para("Una fotografía no estaba disponible al generar este documento.", "IMCSmall"))
    if any(a.kind == "video" for a in asset_list):
        story.append(para("Video disponible en la ficha web autorizada.", "IMCSmall"))
    price = str(values.get("price") or "Consultar precio")
    if values.get("price"):
        price += " " + str(values.get("currency") or "MXN")
    commercial = [
        [para("DISPONIBILIDAD", "IMCLabel"), para("PRECIO", "IMCLabel")],
        [para(AVAILABILITY.get(machine.availability, machine.availability)), para(price)],
    ]
    commercial_table = Table(commercial, colWidths=[86 * mm, 86 * mm])
    commercial_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHT),
                                         ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                         ("LEFTPADDING", (0, 0), (-1, -1), 10),
                                         ("TOPPADDING", (0, 0), (-1, 0), 10),
                                         ("BOTTOMPADDING", (0, 1), (-1, -1), 5)]))
    story.extend([Spacer(1, 3 * mm), commercial_table])
    if values.get("description"):
        story.extend([para("Descripción", "IMCHeading"), para(values["description"])])
    rows = []
    keys = list(LABELS)
    category = getattr(machine, "category", None)
    category_fields = getattr(category, "fields", []) or []
    custom_labels = {f.get("key"): f.get("label", f.get("key")) for f in category_fields if isinstance(f, dict)}
    for key in category_fields:
        field_key = key.get("key") if isinstance(key, dict) else key
        if field_key and field_key not in keys:
            keys.append(field_key)
    for key in keys:
        if public and key in PRIVATE_FIELDS | {"contact_public"}:
            continue
        value = values.get(key)
        if value is None or value == "" or isinstance(value, (dict, list)):
            continue
        label = LABELS.get(key, custom_labels.get(key, key.replace("_", " ").capitalize()))
        reference = reference_by_field.get(key)
        display_value = f"{value}\n{reference['scope_label']}" if reference else value
        rows.append([para(label, "IMCLabel"), para(display_value)])
    if rows:
        story.append(para("Características y datos declarados", "IMCHeading"))
        details = Table(rows, colWidths=[55 * mm, 117 * mm], hAlign="LEFT")
        details.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT]),
                                    ("LEFTPADDING", (0, 0), (-1, -1), 9),
                                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        story.append(details)
    if web_references:
        story.append(para("Fuentes de referencia", "IMCHeading"))
        for reference in web_references:
            story.append(para(f"{reference['label']}: {reference['scope_label']}. {reference['review_label']}.", "IMCSmall"))
            if reference["source_url"]:
                url = escape(reference["source_url"], {'"': "&quot;", "'": "&#39;"})
                title = escape(reference["source_title"])
                story.append(Paragraph(f'<link href="{url}" color="#006A9B">{title}</link>', styles["IMCSmall"]))
            else:
                story.append(para("Fuente privada; el enlace se conserva en la revisión interna.", "IMCSmall"))
    if not public and values.get("notes"):
        story.extend([para("Notas internas del anunciante", "IMCHeading"), para(values["notes"])])
    contact = snapshot.get("public_contact") if snapshot.get("contact_authorized") else None
    if not public and not contact:
        contact = values.get("contact_public")
    if contact:
        if isinstance(contact, dict):
            contact = "\n".join(str(contact[k]) for k in ("text", "name", "company", "email", "phone") if contact.get(k))
        if isinstance(contact, str):
            story.extend([para("Contacto autorizado", "IMCHeading"), para(contact)])
    if not public and provenance:
        story.append(para("Procedencia y revisión", "IMCHeading"))
        sources = {"user": "Declaración del usuario", "image": "Imagen", "plate": "Placa",
                   "visual_proposal": "Propuesta visual", "external": "Fuente externa", "web": "Referencia web", "system": "Texto de preparación"}
        reviews = {"clear": "Lectura clara", "confirmed": "Confirmado por el usuario",
                   "needs_review": "Necesita revisión", "not_identifiable": "No identificable"}
        for key, meta in provenance.items():
            if not isinstance(meta, dict):
                continue
            label = LABELS.get(key, key.replace("_", " ").capitalize())
            source = sources.get(meta.get("source"), str(meta.get("source") or "Sin origen registrado"))
            review = reviews.get(meta.get("review"), str(meta.get("review") or "Pendiente"))
            story.append(para(f"{label}: {source}. {review}.", "IMCSmall"))
    story.extend([Spacer(1, 0 if web_references else 4 * mm), para(
        "La información y las fotografías fueron proporcionadas por el anunciante y pueden incluir asistencia de IA. "
        "La revisión de la ficha no constituye una inspección, certificación ni garantía de condición mecánica. "
        "Confirma los datos y la disponibilidad con IMC México.", "IMCSmall")])

    def page(canvas, doc):
        canvas.saveState()
        width, height = A4
        canvas.drawImage(brand_logo, 19 * mm, height - 34 * mm,
                         width=24 * mm, height=24 * mm, preserveAspectRatio=True,
                         anchor="c", mask="auto")
        canvas.setFillColor(NAVY)
        canvas.setFont("Helvetica-Bold", 15)
        canvas.drawString(49 * mm, height - 20 * mm, "IMC MÉXICO")
        canvas.setFillColor(CHARCOAL)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(49 * mm, height - 27 * mm, "FICHA DE MAQUINARIA")
        canvas.setStrokeColor(ORANGE)
        canvas.setLineWidth(2)
        canvas.line(19 * mm, height - 38 * mm, width - 19 * mm, height - 38 * mm)
        canvas.setStrokeColor(SILVER)
        canvas.setLineWidth(0.5)
        canvas.line(19 * mm, 17 * mm, width - 19 * mm, 17 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(19 * mm, 12 * mm, f"IMC México  |  {machine.folio}")
        canvas.drawRightString(width - 19 * mm, 12 * mm, f"Página {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=page, onLaterPages=page)
    return output.getvalue()
