"""Explicit stage policy: Terra for photo reading, Luna for text and research."""
import re


DEFAULT_MODEL = "gpt-5.6-luna"
VISION_MODEL = "gpt-5.6-terra"
REASONING_OUTPUT_ALLOWANCE = 3500
MIN_REASONING_TIMEOUT = 120


def is_reasoning_model(model):
    return isinstance(model, str) and bool(re.fullmatch(r"gpt-5\.6-(?:luna|terra)(?:-\d{4}-\d{2}-\d{2})?", model))


def image_model(model):
    """The owner's permitted Terra tier replaces only Luna's visual pass.

    This is one call per photograph, not a second attempt. Legacy explicitly
    selected models retain their configuration; Astra still fails closed.
    """
    model_options(model)
    return VISION_MODEL if re.fullmatch(r"gpt-5\.6-luna(?:-\d{4}-\d{2}-\d{2})?", model or "") else model


def model_options(model):
    # The owner explicitly disabled Astra because of its cost. This also blocks
    # historical queued jobs before a provider request can be dispatched.
    if isinstance(model, str) and model.casefold().startswith("gpt-6-astra"):
        raise ValueError("Astra está deshabilitado. Configura GPT-5.6 Luna o Terra.")
    return {"reasoning": {"effort": "low"}} if is_reasoning_model(model) else {}


def output_limit(model, legacy):
    return legacy + REASONING_OUTPUT_ALLOWANCE if is_reasoning_model(model) else legacy


def request_timeout(model, legacy):
    return max(MIN_REASONING_TIMEOUT, legacy) if is_reasoning_model(model) else legacy


def token_reservation(model, legacy):
    # Additional output also consumes the reserved daily token capacity.
    return legacy + REASONING_OUTPUT_ALLOWANCE if is_reasoning_model(model) else legacy
