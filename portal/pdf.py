"""Designed machinery PDFs with private/public snapshot isolation."""
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from decimal import Decimal, InvalidOperation
import re
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
from reportlab.platypus import (CondPageBreak, Flowable, LongTable, PageBreak, Paragraph,
                               SimpleDocTemplate, Spacer, Table, TableStyle)
from .services import PLATE_TECHNICAL_LABELS, WEB_FIELD_LABELS, _reference_text
from .commercial import VISUAL_LABELS, ESTIMATE_LABELS, AGE_LABELS
from .category_profiles import PROFILE_FIELD_LABELS, display_field_value

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
    **PLATE_TECHNICAL_LABELS, **VISUAL_LABELS, **ESTIMATE_LABELS, **AGE_LABELS, **PROFILE_FIELD_LABELS,
}
AVAILABILITY = {"available": "Disponible", "reserved": "Reservada", "sold": "Vendida", "withdrawn": "Retirada"}
PRIVATE_FIELDS = {"serial", "vin", "plate_transcription", "plate_kind", "plate_type", "no_plate", "notes",
                  "document", "owner_email", "owner_phone", "email", "phone"}
_WORKFLOW_CLAUSES = (
    re.compile(r"(?:^|[.;])\s*Estimaci[oó]n orientativa, editable y sujeta a confirmaci[oó]n\.?", re.IGNORECASE),
    re.compile(r"(?:^|[.;])\s*Precios publicados[^.]*no acreditan una venta cerrada[^.]*\.?", re.IGNORECASE),
    re.compile(r"(?:^|[.;])\s*Sin conversi[oó]n[^.]*\.?", re.IGNORECASE),
    re.compile(r"(?:^|[.;])\s*(?:el )?año de esta unidad por confirmar\.?", re.IGNORECASE),
    re.compile(r"(?:^|[.;])\s*(?:pendiente de revisi[oó]n|pendiente de confirmar|por confirmar|por revisar|sujeto a verificaci[oó]n|sin estimar)\.?", re.IGNORECASE),
)
_WORKFLOW_TAIL = re.compile(
    r"(?:[;,]\s*|\s+)(?:pendiente de revisi[oó]n|pendiente de confirmar|por confirmar|"
    r"por revisar|sujeto a verificaci[oó]n|sin estimar|confirmar)\b[^.;]*[.;]?",
    re.IGNORECASE,
)
_OPERATING_STATUS = {"Confirmado por el propietario": "Funcionamiento declarado por el propietario",
                     "Pendiente de confirmar": ""}


def _present(value):
    return value is not None and value != "" and not isinstance(value, (dict, list, bool))


def _price(value, currency):
    if not _present(value):
        return "Consultar precio"
    try:
        amount = Decimal(str(value))
        if amount.is_finite() and len(str(value)) < 24 and -6 <= amount.adjusted() <= 18:
            decimals = 0 if amount == amount.to_integral_value() else 2
            value = f"{amount:,.{decimals}f}"
    except (InvalidOperation, ValueError):
        pass
    return f"{value} {currency or 'MXN'}"


def _pdf_text(value):
    """Keep downloadable copy free of workflow-review warnings.

    Values still describe the machine (including known visible defects), but
    review-routing phrases belong in the editing workflow, not a PDF sent to a
    prospective reader.
    """
    clean = str(value if value is not None else "")
    for pattern in _WORKFLOW_CLAUSES:
        clean = pattern.sub("", clean)
    clean = _WORKFLOW_TAIL.sub("", clean)
    clean = re.sub(r"\b(?:confirmaci[oó]n|confirmar)\b[^.;]*[.;]?", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"[ \t]{2,}", " ", clean)
    clean = re.sub(r"\s+([,;.])", r"\1", clean)
    clean = clean.strip()
    clean = re.sub(r"^[,;]+\s*", "", clean)
    return re.sub(r"[,;]+$", "", clean).strip()


def _display_value(key, value):
    return _pdf_text(_OPERATING_STATUS.get(value, value) if key == "operating_status" else value)


def _estimate_price(value, currency):
    return _price(value, currency) if _present(value) else ""


def _estimate_range(minimum, maximum, currency):
    unit = currency or "MXN"
    low, high = _estimate_price(minimum, unit), _estimate_price(maximum, unit)
    suffix = " " + unit
    if low.endswith(suffix) and high.endswith(suffix):
        return f"{low[:-len(suffix)]}–{high}"
    return f"{low}–{high}"


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
    def __init__(self, reader, width, height, max_image_width=None):
        super().__init__()
        self.reader, self.width, self.height = reader, width, height
        self.max_image_width = max_image_width

    def draw(self):
        canvas = self.canv
        canvas.saveState()
        canvas.setFillColor(LIGHT)
        canvas.roundRect(0, 0, self.width, self.height, 4, fill=1, stroke=0)
        iw, ih = self.reader.getSize()
        scale = min((self.width - 4 * mm) / iw, (self.height - 4 * mm) / ih)
        if self.max_image_width:
            scale = min(scale, self.max_image_width / iw)
        width, height = iw * scale, ih * scale
        canvas.drawImage(self.reader, (self.width - width) / 2, (self.height - height) / 2,
                         width=width, height=height, preserveAspectRatio=True, mask="auto")
        canvas.restoreState()


class PdfDocTemplate(SimpleDocTemplate):
    """Overlay the shared masthead after each page's body is complete."""
    page_decorator = None

    def afterPage(self):
        super().afterPage()
        if self.page_decorator:
            self.page_decorator(self.canv, self)


def build_pdf(machine, data, assets, public=False, version=None):
    """Return PDF bytes. Public mode always needs an authorized snapshot."""
    snapshot = version.data if version else {}
    if public:
        from .public_data import public_projection
        values = public_projection(snapshot if version else {"data": data})
    else:
        values = dict(snapshot.get("data", data))
    title = snapshot.get("title", machine.title)
    if public:
        from .public_data import public_json
        title = public_json(snapshot, title=title).get("title") or "Maquinaria"
    provenance = {} if public else snapshot.get("provenance", getattr(machine, "provenance", {}))
    plate_ids = {str(value) for value in (snapshot.get("private_plate_asset_ids", []) if version
                                        else getattr(machine, "_detected_plate_asset_ids", set()))}

    def is_plate(asset):
        return asset.purpose == "plate" or str(asset.pk) in plate_ids

    asset_list = list(assets)
    if version:
        allowed = {str(a) for a in snapshot.get("asset_ids", [])}
        asset_list = [a for a in asset_list if str(a.pk) in allowed]
    if public:
        if not version:
            raise ValueError("Una ficha de difusión requiere una versión autorizada.")
        private_identifiers = {_reference_text(values.get(key)) for key in ("serial", "vin")} - {""}
        for key in set(WEB_FIELD_LABELS) | {"hours", "kilometers", "attachments"} | VISUAL_LABELS.keys() | ESTIMATE_LABELS.keys():
            if key in values and any(identifier in _reference_text(values[key]) for identifier in private_identifiers):
                values.pop(key)
        public_ids = {str(a) for a in snapshot.get("public_asset_ids", [])}
        asset_list = [a for a in asset_list if str(a.pk) in public_ids and a.public_authorized
                      and not is_plate(a) and a.purpose != "document"]
        for field in PRIVATE_FIELDS:
            values.pop(field, None)
        if not snapshot.get("contact_authorized"):
            values.pop("contact_public", None)
    else:
        asset_list = [a for a in asset_list if a.purpose != "document"]
    asset_list.sort(key=lambda a: (is_plate(a), not a.is_cover, a.position, str(a.pk)))

    regular, bold = _fonts()
    output, width = BytesIO(), 176 * mm
    # SimpleDocTemplate adds six points of horizontal frame padding. Account
    # for it so text, photo panels, header and footer share the same edges.
    document = PdfDocTemplate(output, pagesize=A4, rightMargin=17 * mm - 6, leftMargin=17 * mm - 6,
                                 topMargin=39 * mm, bottomMargin=21 * mm,
                                 title=f"{machine.folio} - {title}", author="IMC México",
                                 subject="Ficha técnica y comercial de maquinaria", pageCompression=1)
    styles = {}
    definitions = {
        "Title": dict(fontName=bold, fontSize=23, leading=27, textColor=NAVY, spaceAfter=5),
        "Heading": dict(fontName=bold, fontSize=11, leading=15, textColor=NAVY,
                        spaceBefore=10, spaceAfter=6, keepWithNext=True),
        "Body": dict(fontSize=9, leading=13, textColor=CHARCOAL, spaceAfter=5),
        "Small": dict(fontSize=7.2, leading=10.3, textColor=MUTED, spaceAfter=4),
        "Label": dict(fontName=bold, fontSize=6.8, leading=9, textColor=MUTED, spaceAfter=3),
        "Value": dict(fontName=bold, fontSize=10.5, leading=14, textColor=NAVY, spaceAfter=2),
        "Eyebrow": dict(fontName=bold, fontSize=7.3, leading=10, textColor=BLUE, spaceAfter=5),
        "TableLabel": dict(fontName=bold, fontSize=8, leading=11.5, textColor=NAVY, spaceAfter=2),
        "TableValue": dict(fontSize=8.5, leading=12.5, textColor=CHARCOAL, spaceAfter=2),
        "WhiteHeading": dict(fontName=bold, fontSize=9.5, leading=13, textColor=colors.white),
    }
    for name, overrides in definitions.items():
        styles[name] = ParagraphStyle(name="IMC" + name, **{"fontName": regular, "splitLongWords": 1, **overrides})

    def para(text, style="Body"):
        clean = _pdf_text(text).replace("\x00", "").replace("\r\n", "\n")
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

    def specification_table(label, keys, labels=None):
        entries = [(key, _display_value(key, values[key])) for key in keys
                   if _present(values.get(key)) and not (public and key in PRIVATE_FIELDS)]
        entries = [(key, value) for key, value in entries if _present(value)]
        if not entries:
            return
        rows = [[para(label, "WhiteHeading"), ""]]
        for key, value in entries:
            name = LABELS.get(key, (labels or {}).get(key, key.replace("_", " ").capitalize()))
            rows.append([para(name, "TableLabel"), para(value, "TableValue")])
        table = LongTable(rows, colWidths=[43 * mm, 133 * mm], hAlign="LEFT",
                          splitInRow=1, repeatRows=1)
        table.setStyle(TableStyle([
            ("SPAN", (0, 0), (-1, 0)), ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [LIGHT, colors.white]),
            ("LINEBELOW", (0, 1), (-1, -1), .4, SILVER),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.extend([Spacer(1, 4 * mm), table])

    now = timezone.localtime(version.created_at if version else timezone.now())
    category = getattr(machine, "category", None)
    category_name = snapshot.get("category_name", "") if version else getattr(category, "name", "")
    state = "FICHA PARA DIFUSIÓN" if public else "FICHA DEL PROPIETARIO"
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
    primary = next((item for item in pictures if not is_plate(item[0])), None)
    if not primary and not public:
        primary = next(iter(pictures), None)
    primary_is_plate = bool(primary and is_plate(primary[0]))
    identity_keys = ["brand", "model", "hours", "year"]
    serial_meta = provenance.get("serial", {})
    if not public and isinstance(serial_meta, dict) and (
        serial_meta.get("source") == "user" and serial_meta.get("review") == "confirmed"
        or serial_meta.get("source") == "plate" and serial_meta.get("review") == "clear"
        and serial_meta.get("component") == "machine"
    ):
        identity_keys.insert(2, "serial")
    summary_keys = [key for key in identity_keys
                    if _present(_display_value(key, values.get(key))) and len(str(values[key])) <= 40 and "\n" not in str(values[key])]
    summary_keys = summary_keys[:4]
    displayed_identity = summary_keys if primary else []
    if primary:
        if summary_keys:
            identity = [para("EL EQUIPO", "Eyebrow")]
            for key in summary_keys:
                identity.extend([para(LABELS[key].upper(), "Label"), para(_display_value(key, values[key]), "Value")])
                identity.append(Spacer(1, 1 * mm))
            hero = Table([[PhotoPanel(primary[1], 117 * mm, 58 * mm if primary_is_plate else 60 * mm,
                                     max_image_width=88 * mm if primary_is_plate else None), identity]],
                         colWidths=[122 * mm, 54 * mm], hAlign="LEFT")
            hero.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (1, 0), (1, 0), LIGHT),
                ("LINEBEFORE", (1, 0), (1, 0), 2, ORANGE),
                ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), 0),
                ("TOPPADDING", (0, 0), (0, 0), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (1, 0), (1, 0), 11), ("RIGHTPADDING", (1, 0), (1, 0), 8),
                ("TOPPADDING", (1, 0), (1, 0), 11),
            ]))
            story.append(hero)
        else:
            story.append(PhotoPanel(primary[1], width, 65 * mm if primary_is_plate else 73 * mm,
                                    max_image_width=88 * mm if primary_is_plate else None))
        caption = "PLACA DE IDENTIFICACIÓN" if primary_is_plate else "VISTA PRINCIPAL  |  Fotografía del equipo"
        story.extend([Spacer(1, 2 * mm), para(caption, "Label")])
    elif not public:
        text = "Las fotografías de la maquinaria se incorporarán aquí."
        story.append(panel([[para("VISTA DEL EQUIPO", "Eyebrow"), para(text)]], [width]))
    if unreadable:
        story.append(para("Una fotografía no estaba disponible al generar este documento.", "Small"))

    price = _price(values.get("price"), values.get("currency")) if _present(values.get("price")) else ""
    commercial = []
    # A valuation's suggested figure belongs under "Valor estimado". It must
    # not become an asking price merely because the owner downloads a PDF.
    if price and provenance.get("price", {}).get("source") != "valuation":
        commercial.append([para("PRECIO", "Label"), para(price, "Value")])
    commercial.append([para("DISPONIBILIDAD", "Label"), para(AVAILABILITY.get(machine.availability, machine.availability), "Value")])
    display_location = _pdf_text(values.get("location") or ', '.join(str(values[key]) for key in ('location_city','location_region','location_country') if values.get(key)))
    if _present(display_location):
        commercial.append([para("UBICACIÓN", "Label"), para(display_location, "Value")])
    story.extend([Spacer(1, 3 * mm), panel(commercial, [width * .34, width * .30, width * .36])])
    highlights = [key for key in ("power", "weight", "capacity", "engine", "transmission", "fuel")
                  if _present(_display_value(key, values.get(key))) and len(str(values[key])) <= 65 and "\n" not in str(values[key])][:3]
    if highlights:
        cells = [[para(LABELS[key].upper(), "Label"), para(_display_value(key, values[key]), "Value")]
                 for key in highlights]
        story.extend([Spacer(1, 2 * mm), panel(cells, [width / len(cells)] * len(cells))])
    category_fields = getattr(category, "fields", []) or []
    custom_labels = {f.get("key"): f.get("label", f.get("key")) for f in category_fields if isinstance(f, dict)}
    if any(_present(values.get(key)) for key in VISUAL_LABELS):
        # These observations are a single commercial block. Starting a fresh
        # page prevents its heading or first rows from being stranded on page 1.
        story.append(PageBreak())
        specification_table("Estado aparente, componentes y aplicaciones", list(VISUAL_LABELS))
    estimate_values = ("estimate_min", "estimate_max", "estimate_suggested_price")
    if any(_present(values.get(key)) for key in estimate_values):
        items = []
        if _present(values.get("estimate_min")) and _present(values.get("estimate_max")):
            items.append(para(_estimate_range(values["estimate_min"], values["estimate_max"], values.get("estimate_currency")), "Value"))
        else:
            for key in estimate_values:
                if _present(values.get(key)):
                    items.append(para(_estimate_price(values[key], values.get("estimate_currency")), "Value"))
                    break
        for key in ("estimate_market", "estimate_currency", "estimate_basis"):
            value = _pdf_text(values.get(key))
            if value:
                items.append(para(f"{ESTIMATE_LABELS[key]}: {value}"))
        section("Valor estimado", items)
    # Keep the concise commercial summary on page 1 and reserve page 2 for
    # visual condition. Descriptions and full specifications may legitimately
    # continue further when they are long.
    description = _pdf_text(values.get("description"))
    section("Descripción del equipo", [para(description)] if description else [])
    specification_table("Identificación del equipo", [key for key in ("brand", "model", "hours", "year", "serial", "country_of_origin", "manufacturer", "manufacturer_address")
                                                       if key not in displayed_identity])
    if any(_present(values.get(key)) for key in ("estimated_year_from", "estimated_year_to")):
        age_items = []
        if _present(values.get("estimated_year_from")) and _present(values.get("estimated_year_to")):
            age_items.append(para(f"{values['estimated_year_from']}–{values['estimated_year_to']}", "Value"))
        else:
            for key in ("estimated_year_from", "estimated_year_to"):
                if _present(values.get(key)):
                    prefix = "Desde" if key == "estimated_year_from" else "Hasta"
                    age_items.append(para(f"{prefix} {values[key]}", "Value"))
        age_basis = _pdf_text(values.get("estimated_year_basis"))
        if age_basis:
            age_items.append(para(f"{AGE_LABELS['estimated_year_basis']}: {age_basis}"))
        section("Año aproximado", age_items)
    specification_table("Especificaciones técnicas", [key for key in ("power", "weight", "capacity", "dimensions", "engine", "transmission", "fuel",
                                                                       "vibration_frequency", "centrifugal_force", "compaction_depth", "digging_depth", "hydraulic_system",
                                                                       "front_tire_size", "rear_tire_size", "mast_tilt", "load_tire_tread",
                                                                       "voltage", "lift_height", "load_center", "battery_weight", "battery_capacity", "fork_length")
                                                        if key not in highlights])
    specification_table("Uso y configuración", [key for key in ("hours", "kilometers", "condition", *PROFILE_FIELD_LABELS)
                                                   if key not in displayed_identity])
    custom_keys = [f.get("key") if isinstance(f, dict) else f for f in category_fields]
    custom_keys = list(dict.fromkeys(key for key in custom_keys if key and key not in LABELS
                                    and key not in PRIVATE_FIELDS | {"description", "contact_public", "price", "currency"}))
    specification_table("Datos adicionales de la categoría", custom_keys, custom_labels)

    extra_pictures = [item for item in pictures if item is not primary and not is_plate(item[0])]
    plate_pictures = [item for item in pictures if is_plate(item[0]) and item is not primary]

    def gallery(items, heading, plates=False):
        if not items:
            return
        gallery_items = []
        for i in range(0, len(items), 2):
            cells = []
            for offset, (asset, reader) in enumerate(items[i:i + 2]):
                label = "PLACA DE IDENTIFICACIÓN" if plates else f"VISTA ADICIONAL {i + offset + 1:02d}"
                cells.append([PhotoPanel(reader, 84 * mm, 59 * mm), Spacer(1, 2 * mm), para(label, "Label")])
            if len(cells) == 1:
                cells.append("")
            gallery = Table([cells], colWidths=[width / 2] * 2, hAlign="LEFT")
            gallery.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
            gallery_items.append(gallery)
        section(heading, gallery_items)

    gallery(extra_pictures, "Registro fotográfico")
    if any(a.kind == "video" for a in asset_list):
        story.append(para("Video disponible en la ficha web autorizada.", "Small"))

    contact = snapshot.get("public_contact") if snapshot.get("contact_authorized") else None
    if not public and not contact:
        contact = values.get("contact_public")
    if isinstance(contact, dict):
        contact = "\n".join(str(contact[k]) for k in ("text", "name", "company", "email", "phone") if contact.get(k))
    if isinstance(contact, str) and contact:
        label = "Contacto autorizado" if snapshot.get("contact_authorized") else "Contacto indicado"
        section(label, [panel([[para(contact)]], [width])])

    if not public:
        gallery(plate_pictures, "Documentación de placa", plates=True)
        if values.get("plate_transcription"):
            section("Transcripción de placa", [para(values["plate_transcription"])])
        if values.get("notes"):
            section("Notas del anunciante", [para(values["notes"])])
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
                               "FICHA PÚBLICA" if public else "FICHA DEL PROPIETARIO")
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
        canvas.drawString(17 * mm, 11 * mm, "IMC México  |  Ficha de maquinaria")
        canvas.drawRightString(page_width - 17 * mm, 11 * mm, f"Página {doc.page}")
        canvas.restoreState()

    document.page_decorator = page
    document.build(story)
    return output.getvalue()
