"""Literal pairs of printed units, without conversions or load-condition inference."""
from dataclasses import dataclass
import re


_UNITS = {"weight": {"lb", "kg"}, "capacity": {"lb", "kg"}, "lift_height": {"in", "mm"}}
_PAIR = (r"(?P<number_a>\d+(?:\.\d+)?)\s+(?P<unit_a>lbs?|kg|in|mm)\s*[/;]\s*"
         r"(?P<number_b>\d+(?:\.\d+)?)\s+(?P<unit_b>lbs?|kg|in|mm)")


@dataclass(frozen=True)
class DualMeasurement:
    parts: tuple[str, str]
    signature: tuple[tuple[str, str], ...]
    row_label: str = ""

    @property
    def canonical(self):
        return (self.row_label + ": " if self.row_label else "") + " / ".join(self.parts)


def parse_dual_measurement(key, value):
    """Accept only one complete lb/kg or in/mm pair with no qualifiers.

    C: is the existing forklift lift-height row label. MAX/MIN, other labels,
    extra numbers, repeated units and any load conditions remain opaque text.
    """
    if key not in _UNITS or not isinstance(value, str):
        return None
    prefix = r"(?:(?P<label>C)\s*:\s*)?" if key == "lift_height" else ""
    match = re.fullmatch(prefix + _PAIR, value.strip(), re.I)
    if not match:
        return None
    units = tuple(match[f"unit_{side}"].casefold().removesuffix("s") for side in ("a", "b"))
    if set(units) != _UNITS[key]:
        return None
    numbers = tuple(match[f"number_{side}"] for side in ("a", "b"))
    parts = tuple(f"{match[f'number_{side}']} {match[f'unit_{side}']}" for side in ("a", "b"))
    return DualMeasurement(parts, tuple(sorted(zip(units, numbers))),
                           (match.groupdict().get("label") or "").upper())


def canonical_dual_measurement(key, value):
    parsed = parse_dual_measurement(key, value)
    return parsed.canonical if parsed else value


def equivalent_dual_measurements(key, left, right):
    """Both printed figures must match; never compare via calculated conversion."""
    first, second = parse_dual_measurement(key, left), parse_dual_measurement(key, right)
    return bool(first and second and first.signature == second.signature)
