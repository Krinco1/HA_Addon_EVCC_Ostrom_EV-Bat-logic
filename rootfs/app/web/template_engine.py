"""Minimal template engine for EVCC-Smartload dashboard."""

from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent / "templates"


def render(template_name: str, context: dict = None) -> str:
    """Load a template file and substitute {{ key }} placeholders."""
    path = TEMPLATE_DIR / template_name
    try:
        html = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"<h1>Template not found: {template_name}</h1>"

    if context:
        for key, value in context.items():
            html = html.replace("{{ " + key + " }}", str(value))
            html = html.replace("{{" + key + "}}", str(value))

    return html
