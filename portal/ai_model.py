"""Use the requested GPT-5.6 Luna/Terra policy; retain historical job models."""
import re


DEFAULT_MODEL = "gpt-5.6-luna"
VISION_MODEL = "gpt-5.6-terra"
REASONING_OUTPUT_ALLOWANCE = 3500
MIN_REASONING_TIMEOUT = 120


def is_reasoning_model(model):
    return isinstance(model, str) and bool(re.fullmatch(r"gpt-(?:5\.6-(?:luna|terra)|6-luna)(?:-\d{4}-\d{2}-\d{2})?", model))


def image_model(model):
    """Route new Luna jobs to Terra for vision, without retrying another model.

    Other explicitly configured models retain their existing stage policy.
    """
    model_options(model)
    return "gpt-5.6-terra" if re.fullmatch(r"gpt-5\.6-luna(?:-\d{4}-\d{2}-\d{2})?", model or "") else model


def model_options(model):
    # The owner explicitly disabled Astra because of its cost. This also blocks
    # historical queued jobs before a provider request can be dispatched.
    if isinstance(model, str) and model.casefold().startswith("gpt-6-astra"):
        raise ValueError("Astra está deshabilitado. Configura GPT-5.6 Luna o GPT-5.6 Terra.")
    return {"reasoning": {"effort": "low"}} if is_reasoning_model(model) else {}


def output_limit(model, legacy):
    return legacy + REASONING_OUTPUT_ALLOWANCE if is_reasoning_model(model) else legacy


def request_timeout(model, legacy):
    return max(MIN_REASONING_TIMEOUT, legacy) if is_reasoning_model(model) else legacy


def token_reservation(model, legacy):
    # Additional output also consumes the reserved daily token capacity.
    return legacy + REASONING_OUTPUT_ALLOWANCE if is_reasoning_model(model) else legacy


def provider_configuration_failure(exc):
    """Expose a bounded error code, never a provider response or credential."""
    from openai import AuthenticationError, NotFoundError, PermissionDeniedError
    if isinstance(exc, AuthenticationError):
        return 'credentials_unavailable'
    if isinstance(exc, (NotFoundError, PermissionDeniedError)):
        return 'model_unavailable'
    return ''
