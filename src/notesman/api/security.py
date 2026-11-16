"""Pure helpers for auth decisions, kept free of I/O so they are easy to test."""

ASSIGNABLE_ROLES = ("user", "admin")


def resolve_role(existing: str | None, email: str, superadmin_email: str) -> str:
    """Role to store at sign-in. Superadmin comes only from SUPERADMIN_EMAIL."""
    if superadmin_email and email.strip().lower() == superadmin_email.strip().lower():
        return "superadmin"
    if existing == "superadmin":  # env no longer matches this email
        return "admin"
    return existing or "user"


def safe_return_path(path: str | None) -> str:
    """Only allow same-site relative paths, so login cannot be used as an open redirect."""
    if not path or any(ord(c) < 32 for c in path):
        return "/"
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/"
    return path


def origin_of(url: str) -> str:
    from urllib.parse import urlparse

    u = urlparse(url)
    return f"{u.scheme}://{u.netloc}"
