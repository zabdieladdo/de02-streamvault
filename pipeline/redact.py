"""Remove the API key from any text before it is shown or stored."""
import re

_API_KEY_PARAM = re.compile(r"(api_key=)[^&\s'\")]*", re.IGNORECASE)


def redact(text: object, secret: str | None = None) -> str:
    """Replace the key, and anything after `api_key=` up to `&` or the end, with ***."""
    text = _API_KEY_PARAM.sub(r"\1***", str(text))
    if secret:
        text = text.replace(secret, "***")
    return text
