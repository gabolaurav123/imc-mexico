"""Request policy for the chosen model; never silently substitute another model."""
import re


DEFAULT_MODEL = "gpt-6-astra"
REASONING_OUTPUT_ALLOWANCE = 3500
MIN_REASONING_TIMEOUT = 120


def is_astra_model(model):
    return isinstance(model, str) and bool(re.fullmatch(r"gpt-6-astra(?:-\d{4}-\d{2}-\d{2})?", model))


def model_options(model):
    return {"reasoning": {"effort": "low"}} if is_astra_model(model) else {}


def output_limit(model, legacy):
    return legacy + REASONING_OUTPUT_ALLOWANCE if is_astra_model(model) else legacy


def request_timeout(model, legacy):
    return max(MIN_REASONING_TIMEOUT, legacy) if is_astra_model(model) else legacy


def token_reservation(model, legacy):
    # Additional output also consumes the reserved daily token capacity.
    return legacy + REASONING_OUTPUT_ALLOWANCE if is_astra_model(model) else legacy
