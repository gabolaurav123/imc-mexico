"""Pure parsers for retrieved public catalogues; no fetching or model inference."""
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

from .research import ResearchField

MAX_HTML_BYTES = 2_000_000
MAX_NODES = 20_000
MAX_ROWS = 500
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_IGNORED = {"script", "style", "template", "iframe", "object", "svg", "noscript"}


def _space(value):
    return " ".join(value.split())


class _Node:
    def __init__(self, tag, attrs=(), parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []

    def classes(self):
        return set(self.attrs.get("class", "").split())

    def hidden(self):
        style = re.sub(r"\s+", "", self.attrs.get("style", "").lower())
        return (self.tag in _IGNORED or "hidden" in self.attrs or self.attrs.get("aria-hidden") == "true"
                or "display:none" in style or "visibility:hidden" in style
                or ("hidden" in self.classes() and not {"unit", "metric"} <= self.classes()))

    def text(self):
        if self.hidden():
            return ""
        return _space("".join(child.text() if isinstance(child, _Node) else child for child in self.children))

    def nodes(self, tag=None):
        for child in self.children:
            if isinstance(child, _Node) and not child.hidden():
                if tag is None or child.tag == tag:
                    yield child
                yield from child.nodes(tag)


class _Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("document")
        self.stack, self.count = [self.root], 0

    def handle_starttag(self, tag, attrs):
        self.count += 1
        if self.count > MAX_NODES or len(self.stack) > 80:
            raise ValueError("Catalogue document limit")
        node = _Node(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_data(self, value):
        self.stack[-1].children.append(value)


def _ancestor(node, predicate):
    node = node.parent
    while node is not None:
        if predicate(node):
            return node
        node = node.parent
    return None


def _row(section, label, value, notes=""):
    section, label, value, notes = map(_space, (section, label, value, notes))
    if not section or not label or not value or len(section) > 100 or len(label) > 200 or len(value) > 300:
        return None
    evidence = f"{section}. {label}: {value}"
    if notes:
        evidence += f". Note: {notes}"
    if len(evidence) > 650:
        return None
    return {"section": section, "label": label, "value": value, "evidence": evidence, "notes": notes}


def _cat_rows(root):
    rows = []
    specifications = next((node for node in root.nodes() if node.attrs.get("id") == "specifications"), None)
    if specifications is None:
        return rows
    for table in specifications.nodes("table"):
        captions = list(table.nodes("caption"))
        if len(captions) != 1:
            continue
        section, found = captions[0].text(), []
        for tr in table.nodes("tr"):
            if _ancestor(tr, lambda node: node.tag == "table") is not table:
                continue
            cells = [node for node in tr.children if isinstance(node, _Node) and node.tag in {"td", "th"}]
            if len(cells) != 2:
                continue
            metrics = [node.text() for node in cells[1].nodes("span") if {"unit", "metric"} <= node.classes()]
            if len(set(metrics)) > 1:
                continue
            value = metrics[0] if metrics else cells[1].text()
            found.append((cells[0].text(), value))
        notes = " ".join(value for label, value in found if label.casefold() == "note")
        for label, value in found:
            row = _row(section, label, value, notes if label.casefold() != "note" else "")
            if row:
                rows.append(row)
            if len(rows) > MAX_ROWS:
                raise ValueError("Catalogue row limit")
    return rows


def _ritchie_rows(item):
    rows = []
    for grid in item.nodes("div"):
        if "two-grid" not in grid.classes():
            continue
        if _ancestor(grid, lambda node: bool(node.classes() & {"compare-block", "compare-row", "related-products"})):
            continue
        headings = list(grid.nodes("h3"))
        if len(headings) != 1:
            continue
        section = headings[0].text()
        if re.search(r"\b(?:option|compare)\b", section, re.I):
            continue
        for label in grid.nodes():
            if label.attrs.get("itemprop") != "name":
                continue
            container = _ancestor(label, lambda node: "row" in node.classes())
            if container is None:
                continue
            values = [node.text() for node in container.nodes() if node.attrs.get("itemprop") == "value"]
            units = [node.text() for node in container.nodes() if node.attrs.get("itemprop") == "unitText"]
            if len(values) != 1 or len(units) > 1:
                continue
            value = _space(values[0] + " " + (units[0] if units else ""))
            row = _row(section, label.text(), value)
            if row:
                rows.append(row)
            if len(rows) > MAX_ROWS:
                raise ValueError("Catalogue row limit")
    return rows


def _model_key(value):
    return re.sub(r"[\s-]+", "", value).casefold()


def _text_lines(node):
    """Visible source lines, including HTML breaks lost by ordinary text()."""
    if node.hidden():
        return ""
    if node.tag == "br":
        return "\n"
    text = "".join(_text_lines(child) if isinstance(child, _Node) else child for child in node.children)
    return text + ("\n" if node.tag in {"p", "div", "tr", "h2", "h3"} else "")


def _smith_document(root, output, identity, url):
    """Historical seller specification, accepted only for its literal unit.

    Unlike a manufacturer catalogue this must never become a model reference
    for another serial. Neither the URL nor a photo alt tag proves identity.
    """
    areas = [n for n in root.nodes("section") if "single-listing" in n.classes()]
    headings = [n.text() for area in areas for n in area.nodes("h2") if "fill" in n.classes()]
    if len(headings) != 1 or len(headings[0]) > 300:
        return output
    heading = headings[0]
    output["heading"] = heading
    heading_model = re.search(r"\bMODEL\s*#?\s*:\s*([A-Za-z0-9][A-Za-z0-9 .-]{0,79})(?=,|$)", heading, re.I)
    heading_serial = re.search(r"\bS/N\s*:\s*([A-Za-z0-9][A-Za-z0-9-]{0,79})(?=\s|,|$)", heading, re.I)
    attributes = {}
    for area in areas:
        for paragraph in area.nodes("p"):
            labels = [n.text() for n in paragraph.nodes("b")]
            lines = [_space(line) for line in _text_lines(paragraph).splitlines() if _space(line)]
            if len(labels) == 1 and len(lines) == 2 and lines[0] == labels[0] and labels[0] in {"Brand", "Model", "Type"}:
                if labels[0] in attributes:
                    return output
                attributes[labels[0]] = lines[1]
    brand_verified = _brand_key(attributes.get("Brand")) == _brand_key(identity.get("brand"))
    document_model = attributes.get("Model", "")
    output["model_info"] = {"requested_model": identity.get("model", ""),
                            "document_models": [document_model] if document_model else [],
                            "brand_verified": brand_verified}
    serial = identity.get("serial")
    if (not brand_verified or not heading_model or not heading_serial
            or not isinstance(serial, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 -]{0,79}", serial)
            or _model_key(heading_serial.group(1)) != _model_key(serial)
            or _model_key(heading_model.group(1)) != _model_key(identity["model"])
            or _model_key(document_model) != _model_key(identity["model"])
            or attributes.get("Type", "").casefold() not in {"forklift trucks", "forklifts"}):
        output["status"] = "identity_mismatch"
        return output
    homes = [n for area in areas for n in area.nodes() if n.attrs.get("id") == "home"]
    if len(homes) != 1:
        return output
    lines = [_space(line) for line in _text_lines(homes[0]).splitlines() if _space(line)]
    if len(lines) > MAX_ROWS:
        return output
    section, rows = "", []
    notes = "SPECIFICATIONS SUBJECT TO VERIFICATION" if "SPECIFICATIONS SUBJECT TO VERIFICATION" in lines else ""
    for line in lines:
        if line in {"SPECIFICATIONS:", "EQUIPPED WITH:", "NOTES:", "DELIVERY:"}:
            section = line.rstrip(":")
            continue
        if section == "SPECIFICATIONS":
            split = re.fullmatch(r"(.+?)\s+-{2,}\s+(.+)", line)
            if not split:
                continue
            row = _row(section, split.group(1), split.group(2), notes)
        elif section == "EQUIPPED WITH" and re.fullmatch(r"\d+(?:[.,]\d+)?\s*(?:in|mm|cm)\s+FORKS", line, re.I):
            row = _row(section, "FORKS", line, notes)
        else:
            continue
        if row:
            # The exact visible heading and raw source row travel together.
            row["literal"] = line
            rows.append(row)
    output["rows"] = rows
    numeric = r"\d+(?:[.,]\d+)*"
    mass, length = numeric + r"\s*(?:LBS?|KG)", numeric + r"\s*(?:in|mm|cm|m)"
    rules = {
        "CAPACITY": ("capacity", mass), "LIFT HEIGHT": ("lift_height", length),
        "BATTERIES": ("voltage", numeric + r"\s*V"),
        "TRUCK WEIGHT W/O BATTERIES": ("weight", mass),
        "TRUCK WEIGHT WITH BATTERIES": ("weight", mass),
        "MIN/MAX BATTERY WEIGHT": ("battery_weight", mass + r"\s*/\s*" + mass),
        "AMP HOUR CAPACITY": ("battery_capacity", numeric),
        "FORKS": ("fork_length", length + r"\s+FORKS"),
    }
    grouped = {}
    for row in rows:
        rule = rules.get(row["label"].upper())
        if rule and re.fullmatch(rule[1], row["value"], re.I):
            grouped.setdefault(rule[0], []).append(row)
    fields, conflicts = [], []
    for key, options in grouped.items():
        by_label = {}
        for row in options:
            by_label.setdefault(row["label"], set()).add(row["value"])
        if any(len(values) != 1 for values in by_label.values()):
            conflicts.append(key)
            continue
        options = list({row["label"]: row for row in options}.values())
        # Retain labels whenever they carry units or a configuration qualifier.
        raw = "\n".join(row["literal"] for row in options)
        value = ("; ".join(f"{row['label']}: {row['value']}" for row in options)
                 if key in {"weight", "battery_weight", "battery_capacity"} else options[0]["value"])
        evidence = heading + "\n" + raw + ("\n" + notes if notes else "")
        if len(value) <= 300 and len(evidence) <= 650:
            fields.append(ResearchField(key=key, value=value, scope="exact_serial", source_url=url,
                evidence=evidence, matched_brand=attributes["Brand"], matched_model=document_model,
                matched_serial=heading_serial.group(1)))
    output.update(status="matched", fields=fields, conflicting_fields=conflicts)
    return output


def _brand_key(value):
    value = _space(str(value or "")).casefold().replace("®", "")
    return "caterpillar" if value in {"cat", "caterpillar"} else value


def _heading_models(heading, brand, provider):
    raw = heading.strip()
    aliases = ("Caterpillar", "Cat") if _brand_key(brand) == "caterpillar" else (str(brand),)
    matched_brand = False
    for alias in sorted(aliases, key=len, reverse=True):
        match = re.match(re.escape(alias) + r"(?:®)?\s+", raw, re.I)
        if match:
            raw, matched_brand = raw[match.end():], True
            break
    if provider == "ritchie":
        if not matched_brand:
            return [], False
        raw = re.sub(r"\s+(?:Hydraulic Excavator|Backhoe Loader|Wheel Loader|Crawler Excavator|Shovel)$", "", raw, flags=re.I)
    models = [_space(part) for part in raw.split("/")]
    if any(not re.fullmatch(r"[\w .-]{1,80}", model) or not re.search(r"\d", model) for model in models):
        return [], matched_brand
    return models, matched_brand


def _candidates(rows, identity, url):
    candidates = {key: [] for key in ("power", "weight", "capacity", "engine", "transmission")}
    for row in rows:
        section, label, value = row["section"], row["label"], row["value"]
        if re.search(r"\b(?:optional|option|counterweight)\b", section + " " + label, re.I):
            continue
        key = None
        if re.fullmatch(r"Engine(?: - Standard)?", section, re.I) and re.match(r"(?:Rated )?Net (?:Peak )?Power\b", label, re.I):
            key = "power"
        elif section.casefold() in {"weights", "operational", "operating specifications"} and re.fullmatch(r"Operating Weight(?: - (?:Maximum|Minimum))?", label, re.I):
            key = "weight"
            if label.casefold() != "operating weight":
                value = f"{label}: {value}"
        elif section.casefold() in {"buckets", "loader", "bucket"} and label.casefold() in {"bucket capacity", "reference bucket capacity"}:
            key = "capacity"
            if label.casefold() == "reference bucket capacity":
                value = f"{label}: {value}"
        elif re.fullmatch(r"Engine(?: - Standard)?", section, re.I) and label.casefold() == "engine model":
            key = "engine"
            if section.casefold() == "engine - standard":
                value = f"{section}. {label}: {value}"
        elif section.casefold() == "transmission" and label.casefold() in {"transmission", "transmission type"}:
            key = "transmission"
        numeric_unit = {
            "power": r"(?:kW|hp|bhp|PS|kVA)",
            "weight": r"(?:kg|t|lb|lbs|ton|tons)",
            "capacity": r"(?:m3|m³|yd3|yd³|cu\.?\s*(?:yd|ft)|l|L)",
        }
        if key in numeric_unit and not re.fullmatch(r"\d+(?:[.,]\d+)?\s*" + numeric_unit[key], row["value"], re.I):
            continue
        if key in {"engine", "transmission"} and (len(row["value"]) > 120 or re.search(r"[<>\x00-\x1f]", row["value"])):
            continue
        if key and len(value) <= 300:
            candidates[key].append((value, row))
    # The overview's net rating takes priority over standard-engine tests with
    # different standards. Within that overview, conflicting values are vetoed.
    common_power = [(value, row) for value, row in candidates["power"] if row["section"].casefold() == "engine"]
    if common_power:
        candidates["power"] = common_power
    fields, conflicts = [], []
    for key, options in candidates.items():
        values = {value for value, _ in options}
        if len(values) > 1:
            conflicts.append(key)
            continue
        if not options:
            continue
        value, row = options[0]
        # No number/unit inference, no conversion, no unit-identity assertion.
        fields.append(ResearchField(key=key, value=value, scope="model", source_url=url,
            evidence=row["evidence"], matched_brand=identity["brand"], matched_model=identity["model"], matched_serial=None))
    return fields, conflicts


def parse_catalog_html(html, url, identity):
    """Return document rows plus eligible literal fields for one exact model.

    Source URL must be the actual safely retrieved final URL. This pure parser
    never follows links, trusts a canonical URL, signs evidence, or fetches data.
    The caller still runs source/identity/literal checks and signs accepted facts.
    """
    output = {"status": "invalid_document", "title": "", "heading": "", "source_url": url,
              "model_info": {"requested_model": "", "document_models": [], "brand_verified": False},
              "rows": [], "fields": [], "conflicting_fields": []}
    try:
        parsed_url = urlsplit(url)
        host = parsed_url.hostname
        if (parsed_url.scheme != "https" or parsed_url.username or parsed_url.password
                or parsed_url.port not in (None, 443) or re.search(r"[\x00-\x20]", url)):
            output["status"] = "unsupported_source"
            return output
        provider = ("cat" if host == "h-cpc.cat.com" and parsed_url.path == "/cmms/v2" else
                    "ritchie" if host in {"ritchiespecs.com", "www.ritchiespecs.com"} and parsed_url.path.startswith("/model/") else
                    "smith" if host == "www.smithmachinery.com" and re.fullmatch(r"/listing/[a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)*/?", parsed_url.path) and not parsed_url.query else None)
        if provider is None:
            output["status"] = "unsupported_source"
            return output
        if not isinstance(html, str) or len(html.encode("utf-8")) > MAX_HTML_BYTES or not isinstance(identity, dict):
            return output
        brand, model = identity.get("brand"), identity.get("model")
        if not isinstance(brand, str) or not isinstance(model, str) or not brand.strip() or not re.fullmatch(r"[\w .-]{1,80}", model):
            return output
        parser = _Document()
        parser.feed(html)
        parser.close()
        root = parser.root
        titles = [node.text() for node in root.nodes("title")]
        if len(titles) != 1 or len(titles[0]) > 180:
            return output
        output["title"] = titles[0]
        if provider == "smith":
            return _smith_document(root, output, identity, url)
        area = root if provider == "cat" else next((node for node in root.nodes() if "item-details" in node.classes()), None)
        if area is None:
            return output
        headings = [node.text() for node in area.nodes("h1") if node.text()]
        if len(headings) != 1 or len(headings[0]) > 300:
            return output
        output["heading"] = headings[0]
        if not output["title"]:
            if len(headings[0]) > 180:
                return output
            output["title"] = headings[0]
        models, heading_brand = _heading_models(headings[0], brand, provider)
        brand_verified = (heading_brand if provider == "ritchie" else
                          _brand_key(brand) == "caterpillar" and bool(re.search(r"\b(?:Caterpillar|Cat)\b", output["title"], re.I)))
        output["model_info"] = {"requested_model": model, "document_models": models, "brand_verified": brand_verified}
        output["rows"] = _cat_rows(root) if provider == "cat" else _ritchie_rows(area)
        if not brand_verified or not any(_model_key(item) == _model_key(model) for item in models):
            output["status"] = "identity_mismatch"
        elif len(models) != 1:
            output["status"] = "ambiguous_models"
        else:
            output["status"] = "matched"
            output["fields"], output["conflicting_fields"] = _candidates(output["rows"], identity, url)
        return output
    except (ValueError, TypeError, RecursionError):
        return output
