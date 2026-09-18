"""Request policy for the chosen model; never silently substitute another model."""
import re


DEFAULT_MODEL = "gpt-5.6-luna"
REASONING_OUTPUT_ALLOWANCE = 3500
MIN_REASONING_TIMEOUT = 120


def is_reasoning_model(model):
    return isinstance(model, str) and bool(re.fullmatch(r"gpt-5\.6-(?:luna|terra)(?:-\d{4}-\d{2}-\d{2})?", model))


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
