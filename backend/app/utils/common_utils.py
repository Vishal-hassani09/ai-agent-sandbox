import os
from app.config import settings

def get_safe_path(filename: str) -> str:
    base_path = os.path.abspath(settings.WORKSPACE_DIR)
    target_path = os.path.abspath(os.path.join(base_path, filename))


    if not target_path.startswith(base_path):
        raise PermissionError(f"Security Violation: Path '{filename}' escapes workspace directory.")

    return target_path