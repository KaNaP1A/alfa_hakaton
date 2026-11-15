"""Create a private local snapshot environment without overwriting existing settings."""

import os
import secrets
from pathlib import Path


def main() -> None:
    backend = Path(__file__).resolve().parents[1]
    destination = backend / ".env.snapshot"
    template = (backend / ".env.snapshot.example").read_text(encoding="utf-8")
    content = template.replace("__GENERATED_PASSWORD__", secrets.token_hex(24))
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print("Existing .env.snapshot retained")
        return
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(content)
    print("Created private .env.snapshot with a generated password")


if __name__ == "__main__":
    main()
