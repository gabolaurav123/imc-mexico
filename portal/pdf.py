"""Designed machinery PDFs with private/public snapshot isolation."""
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from decimal import Decimal, InvalidOperation
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
from reportlab.platypus import (CondPageBreak, Flowable, LongTable, Paragraph,
                               SimpleDocTemplate, Spacer, Table, TableStyle)
from .services import (PLATE_TECHNICAL_LABELS, WEB_FIELD_LABELS, _reference_text,
                       public_web_references, web_research_for_provenance)
from .services import public_valuation, valuations_for_provenance
from .commercial import VISUAL_LABELS, ESTIMATE_LABELS, ESTIMATE_LABEL, AGE_LABELS, AGE_LABEL
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
SOURCE_LABELS = {"user": "Anunciante", "image": "Fotografía", "plate": "Lectura de placa",
                 "visual_proposal": "Propuesta visual", "external": "Fuente externa",
                 "web": "Referencia documental", "system": "Texto de preparación", "valuation": "Comparables de mercado"}
REVIEW_LABELS = {"clear": "Lectura clara", "confirmed": "Confirmado por el anunciante",
                 "needs_review": "Por revisar", "not_identifiable": "No identificable"}


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
    reference_snapshot = snapshot if version else {"data": values, "provenance": provenance,
                                                   "web_research": web_research_for_provenance(provenance)}
    web_references = [] if public else public_web_references(reference_snapshot, include_private=True)
    reference_by_field = {item["field"]: item for item in web_references}
    valuation_snapshot = snapshot if version else {"data": values, "provenance": provenance,
                                                  "valuations": valuations_for_provenance(provenance)}
    valuation = {} if public else public_valuation(valuation_snapshot)
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
    document = SimpleDocTemplate(output, pagesize=A4, rightMargin=17 * mm - 6, leftMargin=17 * mm - 6,
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

    def origin(key):
        reference = reference_by_field.get(key)
        if reference:
            return reference["scope_label"] + ". " + reference["review_label"]
        meta = provenance.get(key, {})
        if not isinstance(meta, dict) or not meta.get("source"):
            return "Dato de la ficha"
        label = SOURCE_LABELS.get(meta.get("source"), "Origen registrado")
        review = REVIEW_LABELS.get(meta.get("review"), "Por revisar")
        # Never copy raw evidence, asset identifiers, or an unvalidated URL into
        # public copy. A source label describes how the value entered the file.
        if meta.get("source") in {"plate", "image"} and meta.get("review") == "clear":
            return label
        return label + ". " + review

    def specification_table(label, keys, labels=None):
        entries = [key for key in keys if _present(values.get(key)) and not (public and key in PRIVATE_FIELDS)]
        if not entries:
            return
        rows = [[para(label, "WhiteHeading"), "", ""]]
        for key in entries:
            name = LABELS.get(key, (labels or {}).get(key, key.replace("_", " ").capitalize()))
            rows.append([para(name, "TableLabel"), para(display_field_value(key, values[key]), "TableValue"), para('' if public else origin(key), "Small")])
        table = LongTable(rows, colWidths=[35 * mm, 101 * mm, 40 * mm], hAlign="LEFT",
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
                    if _present(values.get(key)) and len(str(values[key])) <= 40 and "\n" not in str(values[key])]
    summary_keys = summary_keys[:4]
    displayed_identity = summary_keys if primary else []
    if primary:
        if summary_keys:
            identity = [para("EL EQUIPO", "Eyebrow")]
            for key in summary_keys:
                identity.extend([para(LABELS[key].upper(), "Label"), para(values[key], "Value")])
                if isinstance(provenance.get(key), dict) and provenance[key].get("source"):
                    identity.append(para(origin(key), "Small"))
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
        caption = "PLACA DE IDENTIFICACIÓN  |  Evidencia de uso interno" if primary_is_plate else "VISTA PRINCIPAL  |  Fotografía del equipo"
        story.extend([Spacer(1, 2 * mm), para(caption, "Label")])
    elif not public:
        text = "Las fotografías de la maquinaria se incorporarán aquí."
        story.append(panel([[para("VISTA DEL EQUIPO", "Eyebrow"), para(text)]], [width]))
    if unreadable:
        story.append(para("Una fotografía no estaba disponible al generar este documento.", "Small"))

    price = _price(values.get("price"), values.get("currency")) if _present(values.get("price")) else ""
    price_label = ("PRECIO SUGERIDO"
                   if provenance.get("price", {}).get("source") == "valuation"
                   and valuation.get("status") != "conditional_reference" else "PRECIO")
    commercial = []
    if price:
        commercial.append([para(price_label, "Label"), para(price, "Value")])
    commercial.append([para("DISPONIBILIDAD", "Label"), para(AVAILABILITY.get(machine.availability, machine.availability), "Value")])
    display_location = values.get("location") or ', '.join(str(values[key]) for key in ('location_city','location_region','location_country') if values.get(key))
    if _present(display_location):
        commercial.append([para("UBICACIÓN", "Label"), para(display_location, "Value")])
    story.extend([Spacer(1, 3 * mm), panel(commercial, [width * .34, width * .30, width * .36])])
    highlights = [key for key in ("power", "weight", "capacity", "engine", "transmission", "fuel")
                  if _present(values.get(key)) and len(str(values[key])) <= 65 and "\n" not in str(values[key])][:3]
    if highlights:
        cells = [[para(LABELS[key].upper(), "Label"), para(values[key], "Value"), para(origin(key), "Small")]
                 for key in highlights]
        story.extend([Spacer(1, 2 * mm), panel(cells, [width / len(cells)] * len(cells))])
    section("Descripción del equipo", [para(values["description"])] if values.get("description") else [])
    category_fields = getattr(category, "fields", []) or []
    custom_labels = {f.get("key"): f.get("label", f.get("key")) for f in category_fields if isinstance(f, dict)}
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
        age_items.append(para("Rango orientativo; no sustituye el año exacto de fabricación.", "Small"))
        if values.get("estimated_year_basis"):
            age_items.append(para(f"{AGE_LABELS['estimated_year_basis']}: {values['estimated_year_basis']}"))
        section(AGE_LABEL, age_items)
    specification_table("Especificaciones técnicas", [key for key in ("power", "weight", "capacity", "dimensions", "engine", "transmission", "fuel",
                                                                       "vibration_frequency", "centrifugal_force", "compaction_depth", "digging_depth", "hydraulic_system",
                                                                       "front_tire_size", "rear_tire_size", "mast_tilt", "load_tire_tread",
                                                                       "voltage", "lift_height", "load_center", "battery_weight", "battery_capacity", "fork_length")
                                                        if key not in highlights])
    specification_table("Uso y configuración", [key for key in ("hours", "kilometers", "condition", *PROFILE_FIELD_LABELS)
                                                   if key not in displayed_identity])
    specification_table("Estado aparente, componentes y aplicaciones", list(VISUAL_LABELS))
    if any(_present(values.get(key)) for key in ESTIMATE_LABELS):
        valuation_label = ("Referencia de mercado condicional. El rango reúne comparables con una condición documentada; "
                           "no confirma la condición de esta unidad ni su funcionamiento. No se completó un precio de anuncio sugerido."
                           if valuation.get("status") == "conditional_reference" else ESTIMATE_LABEL)
        items = [para(valuation_label, "Small")]
        if _present(values.get("estimate_min")) and _present(values.get("estimate_max")):
            items.append(para(f"{values['estimate_min']} - {values['estimate_max']} {values.get('estimate_currency') or ''}", "Value"))
        else:
            for key in ("estimate_min", "estimate_max"):
                if _present(values.get(key)):
                    items.append(para(f"{ESTIMATE_LABELS[key]}: {values[key]} {values.get('estimate_currency') or ''}", "Value"))
        for key in ("estimate_market", "estimate_basis", "estimate_missing_info"):
            if values.get(key):
                items.append(para(f"{ESTIMATE_LABELS[key]}: {values[key]}"))
        if valuation.get("edited"):
            items.append(para("Estimación modificada en la ficha.", "Small"))
        section("Referencia de valor y precio", items)
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
                label = "PLACA - USO INTERNO" if plates else f"VISTA ADICIONAL {i + offset + 1:02d}"
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
        label = "Contacto autorizado" if snapshot.get("contact_authorized") else "Contacto indicado · uso interno"
        section(label, [panel([[para(contact)]], [width])])

    if not public:
        gallery(plate_pictures, "Documentación de placa / uso interno", plates=True)
        if values.get("plate_transcription"):
            section("Transcripción de placa / uso interno", [para(values["plate_transcription"])])
        if values.get("notes"):
            section("Notas internas del anunciante", [para(values["notes"])])
    if not public and provenance:
        lines = []
        for key, meta in provenance.items():
            if isinstance(meta, dict) and (key in {"title", "description"} or _present(values.get(key))):
                label = LABELS.get(key, key.replace("_", " ").capitalize())
                line = f"{label}: {origin(key)}."
                if meta.get("source") == "plate" and meta.get("evidence"):
                    line += " Texto leído: " + str(meta["evidence"])
                lines.append(para(line, "Small"))
        section("Trazabilidad de la información / uso interno", lines)
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
        canvas.setFont(regular, 6.5)
        canvas.drawString(17 * mm, 6.5 * mm,
                          "Datos del anunciante con posible asistencia de IA. No constituye inspección ni garantía mecánica.")
        canvas.restoreState()

    document.build(story, onFirstPage=page, onLaterPages=page)
    return output.getvalue()
