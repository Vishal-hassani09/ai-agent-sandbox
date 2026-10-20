import re
from pathlib import Path


def expand_file_mentions(user_prompt: str, workspace_dir: str) -> str:
    """Finds @filename mentions, reads their contents from the workspace,

    and appends them to the prompt context.
    """
    matches = re.findall(r"@([\w\./\\-]+)", user_prompt)
    if not matches:
        return user_prompt

    workspace = Path(workspace_dir).resolve()
    unique_mentions = set(matches)
    content_blocks = []

    for rel_path in unique_mentions:
        target_file = (workspace / rel_path).resolve()

        # Security check: prevent escaping workspace boundaries
        if not str(target_file).startswith(str(workspace)):
            content_blocks.append(
                f"\n[Warning: Path @{rel_path} escapes workspace - skipped]"
            )
            continue

        if target_file.is_file():
            try:
                content = target_file.read_text(encoding="utf-8")
                content_blocks.append(
                    f"\n\n--- Content of @{rel_path} ---\n```\n{content}\n```"
                )
            except Exception as e:
                content_blocks.append(f"\n[Error reading @{rel_path}: {e}]")
        else:
            content_blocks.append(f"\n[File not found: @{rel_path}]")

    return user_prompt + "".join(content_blocks)