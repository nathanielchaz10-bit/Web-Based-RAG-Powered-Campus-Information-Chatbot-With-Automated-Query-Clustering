from app.core.config import settings

def is_valid_hccs_domain(email: str) -> bool:
    return email.endswith(f"@{settings.HCCS_DOMAIN}")
