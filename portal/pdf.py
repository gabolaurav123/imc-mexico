"""Designed machinery PDFs with private/public snapshot isolation."""
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

import reportlab
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (CondPageBreak, Flowable, KeepTogether, LongTable, Paragraph,
                               SimpleDocTemplate, Spacer, Table, TableStyle)
from .services import public_web_references, web_research_for_provenance

NAVY = colors.HexColor("#000033")
ORANGE = colors.HexColor("#E38C1A")
BLUE = colors.HexColor("#0095D9")
SILVER = colors.HexColor("#DDE3E9")
CHARCOAL = colors.HexColor("#253047")
MUTED = colors.HexColor("#617086")
LIGHT = colors.HexColor("#F3F6F9")
LOGO_PATH = Path(__file__).resolve().parent / "static" / "portal" / "imc-logo.png"
LABELS = {
    "brand": "Marca", "model": "Modelo", "year": "Año", "serial": "Número de serie",
    "hours": "Horas de uso", "location": "Ubicación", "condition": "Condición declarada",
    "power": "Potencia", "weight": "Peso", "capacity": "Capacidad", "dimensions": "Dimensiones",
    "fuel": "Combustible", "kilometers": "Kilometraje", "engine": "Motor", "transmission": "Transmisión",
    "attachments": "Accesorios",
}
AVAILABILITY = {"available": "Disponible", "reserved": "Reservada", "sold": "Vendida", "withdrawn": "Retirada"}
PRIVATE_FIELDS = {"serial", "vin", "plate_transcription", "plate_kind", "plate_type", "no_plate", "notes",
                  "document", "owner_email", "owner_phone", "email", "phone"}


@lru_cache(maxsize=1)
def _fonts():
    # Licensed fonts ship with ReportLab on both Windows and Linux. Embed them
    # so accented text does not depend on the recipient's installed fonts.
    directory = Path(reportlab.__file__).resolve().parent / "fonts"
    for name, filename in (("IMCSans", "Vera.ttf"), ("IMCSansBold", "VeraBd.ttf")):
        pdfmetrics.registerFont(TTFont(name, str(directory / filename)))
    pdfmetrics.registerFontFamily("IMCSans", normal="IMCSans", bold="IMCSansBold",
                                  italic="IMCSans", boldItalic="IMCSansBold")
    return "IMCSans", "IMCSansBold"


class PhotoPanel(Flowable):
    """Fit the complete preview; do not crop equipment or alter its proportions."""
    def __init__(self, reader, width, height):
        super().__init__()
        self.reader, self.width, self.height = reader, width, height

    def draw(self):
        canvas = self.canv
        canvas.saveState()
        canvas.setFillColor(LIGHT)
        canvas.roundRect(0, 0, self.width, self.height, 4, fill=1, stroke=0)
        iw, ih = self.reader.getSize()
        scale = min((self.width - 4 * mm) / iw, (self.height - 4 * mm) / ih)
        width, height = iw * scale, ih * scale
        canvas.drawImage(self.reader, (self.width - width) / 2, (self.height - height) / 2,
                         width=width, height=height, preserveAspectRatio=True, mask="auto")
        canvas.restoreState()


def build_pdf(machine, data, assets, public=False, version=None):
    """Return PDF bytes. Public mode always needs an authorized snapshot."""
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
        allowed = {str(a) for a in snapshot.get("asset_ids", [])}
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
        asset_list = [a for a in asset_list if a.purpose != "document"]
    asset_list.sort(key=lambda a: (a.purpose == "plate", not a.is_cover, a.position, str(a.pk)))

    regular, bold = _fonts()
    output, width = BytesIO(), 176 * mm
    # SimpleDocTemplate adds six points of horizontal frame padding. Account
    # for it so text, photo panels, header and footer share the same edges.
    document = SimpleDocTemplate(output, pagesize=A4, rightMargin=17 * mm - 6, leftMargin=17 * mm - 6,
                                 topMargin=39 * mm, bottomMargin=21 * mm,
                                 title=f"{machine.folio} - {title}", author="IMC México",
                                 subject="Ficha técnica y comercial de maquinaria", pageCompression=1)
    styles = {}
    definitions = {
        "Title": dict(fontName=bold, fontSize=23, leading=27, textColor=NAVY, spaceAfter=5),
        "Heading": dict(fontName=bold, fontSize=11, leading=15, textColor=NAVY,
                        spaceBefore=13, spaceAfter=7, keepWithNext=True),
        "Body": dict(fontSize=9, leading=13.5, textColor=CHARCOAL, spaceAfter=6),
        "Small": dict(fontSize=7.2, leading=10.3, textColor=MUTED, spaceAfter=4),
        "Label": dict(fontName=bold, fontSize=6.8, leading=9, textColor=MUTED, spaceAfter=3),
        "Value": dict(fontName=bold, fontSize=10.5, leading=14, textColor=NAVY, spaceAfter=2),
        "Eyebrow": dict(fontName=bold, fontSize=7.3, leading=10, textColor=BLUE, spaceAfter=5),
    }
    for name, overrides in definitions.items():
        styles[name] = ParagraphStyle(name="IMC" + name, **{"fontName": regular, "wordWrap": "CJK", **overrides})

    def para(text, style="Body"):
        clean = str(text if text is not None else "").replace("\x00", "").replace("\r\n", "\n")
        return Paragraph(escape(clean).replace("\n", "<br/>"), styles[style])

    def section(label, items):
        if items:
            heading = para(label, "Heading")
            if isinstance(items[0], Paragraph):
                # Reserve room for the heading and opening lines while letting
                # lengthy descriptions flow through the remaining cover space.
                story.append(CondPageBreak(30 * mm))
                heading.keepWithNext = False
            story.append(heading)
            story.extend(items)

    def panel(cells, widths):
        table = Table([cells], colWidths=widths, hAlign="LEFT", splitInRow=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        return table

    now = timezone.localtime(version.created_at if version else timezone.now())
    category = getattr(machine, "category", None)
    category_name = snapshot.get("category_name", "") if version else getattr(category, "name", "")
    draft = not public and (not version or getattr(machine, "approved_version_id", None) != getattr(version, "pk", None))
    state = "FICHA PARA DIFUSIÓN" if public else "VERSIÓN INTERNA - DATOS PRIVADOS"
    if draft:
        state += " / PENDIENTE DE REVISIÓN"
    story = [para(category_name.upper() if category_name else "FICHA TÉCNICA Y COMERCIAL", "Eyebrow"),
             para(title, "Title"),
             para(f"{machine.folio}  |  Versión {version.number if version else machine.revision}  |  {now:%d/%m/%Y}", "Small"),
             para(state, "Label"), Spacer(1, 3 * mm)]

    pictures, unreadable = [], 0
    for asset in asset_list:
        if asset.kind != "image" or asset.processing_status != "ready" or not asset.preview:
            continue
        try:
            with asset.preview.open("rb") as stream:
                reader = ImageReader(BytesIO(stream.read()))
            reader.getRGBData()
            pictures.append((asset, reader))
        except (OSError, ValueError):
            unreadable += 1
    primary = next((item for item in pictures if item[0].purpose != "plate"), None)
    if primary:
        story.extend([PhotoPanel(primary[1], width, 73 * mm), Spacer(1, 2 * mm),
                      para("VISTA PRINCIPAL  |  Fotografía proporcionada por el anunciante", "Label")])
    else:
        text = "Sin fotografía autorizada en esta versión." if public else "Las fotografías de la maquinaria se incorporarán aquí."
        story.append(panel([[para("VISTA DEL EQUIPO", "Eyebrow"), para(text)]], [width]))
    if unreadable:
        story.append(para("Una fotografía no estaba disponible al generar este documento.", "Small"))

    price_value = values.get("price")
    price = f"{price_value} {values.get('currency') or 'MXN'}" if price_value not in (None, "") else "Consultar precio"
    commercial = [[para("PRECIO", "Label"), para(price, "Value")],
                  [para("DISPONIBILIDAD", "Label"), para(AVAILABILITY.get(machine.availability, machine.availability), "Value")],
                  [para("UBICACIÓN", "Label"), para(values.get("location") or "Por confirmar")]]
    story.extend([Spacer(1, 3 * mm), panel(commercial, [width * .34, width * .30, width * .36])])
    section("Descripción del equipo", [para(values["description"])] if values.get("description") else [])

    keys = list(LABELS)
    category_fields = getattr(category, "fields", []) or []
    custom_labels = {f.get("key"): f.get("label", f.get("key")) for f in category_fields if isinstance(f, dict)}
    for key in category_fields:
        field_key = key.get("key") if isinstance(key, dict) else key
        if field_key and field_key not in keys:
            keys.append(field_key)
    entries = []
    for key in keys:
        if key == "location" or (public and key in PRIVATE_FIELDS | {"contact_public"}):
            continue
        value = values.get(key)
        if value is None or value == "" or isinstance(value, (dict, list)):
            continue
        label = LABELS.get(key, custom_labels.get(key, key.replace("_", " ").capitalize()))
        reference = reference_by_field.get(key)
        cell = [para(label.upper() + (" · PRIVADO" if key in PRIVATE_FIELDS else ""), "Label"), para(value)]
        if reference:
            cell.append(para(reference["scope_label"], "Small"))
        entries.append(cell)
    if entries:
        rows = [entries[i:i + 2] + ([""] if i + 1 == len(entries) else []) for i in range(0, len(entries), 2)]
        # A repeating table heading lets the first rows use the cover page's
        # remaining space and labels specifications that continue onto a page.
        details = LongTable([[para("Características y datos declarados", "Heading"), ""]] + rows,
                            colWidths=[width / 2] * 2, hAlign="LEFT", splitInRow=1, repeatRows=1)
        details.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [LIGHT, colors.white]),
            ("LINEBELOW", (0, 1), (-1, -1), .4, SILVER),
            ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("SPAN", (0, 0), (-1, 0)), ("LEFTPADDING", (0, 0), (-1, 0), 0),
            ("TOPPADDING", (0, 0), (-1, 0), 13), ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
        ]))
        story.append(details)

    extra_pictures = [item for item in pictures if item is not primary]
    if extra_pictures:
        gallery_items = []
        for i in range(0, len(extra_pictures), 2):
            cells = []
            for offset, (asset, reader) in enumerate(extra_pictures[i:i + 2]):
                label = "PLACA DE IDENTIFICACIÓN - USO INTERNO" if asset.purpose == "plate" else f"VISTA ADICIONAL {i + offset + 1:02d}"
                cells.append([PhotoPanel(reader, 84 * mm, 59 * mm), Spacer(1, 2 * mm), para(label, "Label")])
            if len(cells) == 1:
                cells.append("")
            gallery = Table([cells], colWidths=[width / 2] * 2, hAlign="LEFT")
            gallery.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
            gallery_items.append(gallery)
        section("Galería del equipo", gallery_items)
    if any(a.kind == "video" for a in asset_list):
        story.append(para("Video disponible en la ficha web autorizada.", "Small"))

    contact = snapshot.get("public_contact") if snapshot.get("contact_authorized") else None
    if not public and not contact:
        contact = values.get("contact_public")
    if isinstance(contact, dict):
        contact = "\n".join(str(contact[k]) for k in ("text", "name", "company", "email", "phone") if contact.get(k))
    if isinstance(contact, str) and contact:
        label = "Contacto autorizado" if snapshot.get("contact_authorized") else "Contacto indicado · uso interno"
        section(label, [panel([[para(contact)]], [width])])

    if web_references:
        reference_items = [para("Las referencias del modelo no confirman la configuración de esta unidad.", "Small")]
        for index, reference in enumerate(web_references, 1):
            label = para(f"{index:02d}  {reference['label']} · {reference['scope_label']}. {reference['review_label']}.", "Small")
            if reference["source_url"]:
                url = escape(reference["source_url"], {'"': "&quot;", "'": "&#39;"})
                link_title = escape(reference["source_title"] or "Consultar fuente")
                link = Paragraph(f'<link href="{url}" color="#0074A5">{link_title}</link>', styles["Small"])
            else:
                link = para("Fuente privada; el enlace se conserva en la revisión interna.", "Small")
            reference_items.append(KeepTogether([label, link, Spacer(1, 1.5 * mm)]))
        section("Fuentes de referencia", reference_items)
    if not public and values.get("notes"):
        section("Notas internas del anunciante", [para(values["notes"])])
    if not public and provenance:
        sources = {"user": "Declaración del usuario", "image": "Imagen", "plate": "Placa",
                   "visual_proposal": "Propuesta visual", "external": "Fuente externa", "web": "Referencia web", "system": "Texto de preparación"}
        reviews = {"clear": "Lectura clara", "confirmed": "Confirmado por el usuario",
                   "needs_review": "Necesita revisión", "not_identifiable": "No identificable"}
        lines = []
        for key, meta in provenance.items():
            if isinstance(meta, dict):
                label = LABELS.get(key, key.replace("_", " ").capitalize())
                source = sources.get(meta.get("source"), str(meta.get("source") or "Sin origen registrado"))
                review = reviews.get(meta.get("review"), str(meta.get("review") or "Pendiente"))
                lines.append(para(f"{label}: {source}. {review}.", "Small"))
        section("Procedencia y revisión · uso interno", lines)
    story.extend([Spacer(1, 4 * mm), para(
        "La información y las fotografías fueron proporcionadas por el anunciante y pueden incluir asistencia de IA. "
        "La revisión de la ficha no constituye una inspección, certificación ni garantía de condición mecánica. "
        "Confirma los datos y la disponibilidad con IMC México.", "Small")])

    brand_logo = ImageReader(str(LOGO_PATH))
    def page(canvas, doc):
        canvas.saveState()
        page_width, height = A4
        canvas.setFillColor(NAVY)
        canvas.rect(0, height - 31 * mm, page_width, 31 * mm, fill=1, stroke=0)
        canvas.setFillColor(ORANGE)
        canvas.rect(0, height - 2 * mm, page_width, 2 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.roundRect(17 * mm, height - 28 * mm, 24 * mm, 23 * mm, 3, fill=1, stroke=0)
        canvas.drawImage(brand_logo, 18 * mm, height - 27 * mm, width=22 * mm, height=21 * mm,
                         preserveAspectRatio=True, anchor="c", mask="auto")
        canvas.setFont(bold, 15)
        canvas.drawString(47 * mm, height - 15 * mm, "IMC MÉXICO")
        canvas.setFont(regular, 7)
        canvas.setFillColor(colors.HexColor("#D7E4F1"))
        canvas.drawString(47 * mm, height - 22 * mm, "FICHA DE MAQUINARIA")
        canvas.setFillColor(colors.white)
        canvas.setFont(bold, 7.3)
        canvas.drawRightString(page_width - 17 * mm, height - 15 * mm,
                              "FICHA PÚBLICA" if public else "PDF INTERNO")
        canvas.setFont(regular, 6.8)
        canvas.setFillColor(colors.HexColor("#D7E4F1"))
        canvas.drawRightString(page_width - 17 * mm, height - 22 * mm, str(machine.folio))
        canvas.setFillColor(BLUE)
        canvas.rect(0, height - 31.7 * mm, page_width, .7 * mm, fill=1, stroke=0)
        canvas.setStrokeColor(SILVER)
        canvas.setLineWidth(.5)
        canvas.line(17 * mm, 16 * mm, page_width - 17 * mm, 16 * mm)
        canvas.setStrokeColor(ORANGE)
        canvas.setLineWidth(2)
        canvas.line(17 * mm, 16 * mm, 33 * mm, 16 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont(regular, 7)
        canvas.drawString(17 * mm, 11 * mm, "IMC México  |  " + ("Ficha para difusión" if public else "Documento interno"))
        canvas.drawRightString(page_width - 17 * mm, 11 * mm, f"Página {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=page, onLaterPages=page)
    return output.getvalue()
