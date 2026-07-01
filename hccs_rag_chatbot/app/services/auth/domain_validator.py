from app.core.config import settings


def is_valid_hccs_domain(email: str | None) -> bool:
    """True only for a non-empty address on the configured school domain.

    Case-insensitive and null-safe. This matters because the app is published as
    an *External* OAuth app, so Google lets any account reach the callback — this
    server-side check is the sole gate keeping non-school accounts out. It must
    never crash on a missing email, nor wrongly reject a mixed-case one.
    """
    if not email:
        return False
    domain = settings.HCCS_DOMAIN.strip().lower()
    return email.strip().lower().endswith(f"@{domain}")