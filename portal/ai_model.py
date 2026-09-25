"""Pin every new stage to GPT-6 Luna; retain explicit historical job policy."""
import re


DEFAULT_MODEL = "gpt-6-luna"
VISION_MODEL = DEFAULT_MODEL
REASONING_OUTPUT_ALLOWANCE = 3500
MIN_REASONING_TIMEOUT = 120


def is_reasoning_model(model):
    return isinstance(model, str) and bool(re.fullmatch(r"gpt-(?:5\.6-(?:luna|terra)|6-luna)(?:-\d{4}-\d{2}-\d{2})?", model))


def image_model(model):
    """No fallback: GPT-6 Luna reads images and handles research itself.

    Preserve the recorded 5.6 policy for older explicitly configured jobs.
    """
    model_options(model)
    return "gpt-5.6-terra" if re.fullmatch(r"gpt-5\.6-luna(?:-\d{4}-\d{2}-\d{2})?", model or "") else model


def model_options(model):
    # The owner explicitly disabled Astra because of its cost. This also blocks
    # historical queued jobs before a provider request can be dispatched.
    if isinstance(model, str) and model.casefold().startswith("gpt-6-astra"):
        raise ValueError("Astra está deshabilitado. Configura GPT-6 Luna.")
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
