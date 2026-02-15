"""
Minimal template engine.

Loads .html files from the templates directory and substitutes {{key}} placeholders.
Avoids Jinja2 dependency while keeping HTML out of Python f-strings.
"""

import os
from pathlib import Path
from typing import Dict


TEMPLATE_DIR = Path(__file__).parent / "templates"


def render(template_name: str, context: Dict[str, str] = None) -> str:
    """
    Load *template_name* from the templates directory and replace ``{{key}}``
    placeholders with values from *context*.
    """
    path = TEMPLATE_DIR / template_name
    if not path.exists():
        return f"<h1>Template not found: {template_name}</h1>"

    html = path.read_text(encoding="utf-8")

    if context:
        for key, value in context.items():
            html = html.replace("{{" + key + "}}", str(value))

    return html
