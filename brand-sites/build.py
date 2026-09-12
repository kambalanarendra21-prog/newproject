#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent
TEMPLATES = ROOT / "templates"
DIST = ROOT / "dist"
PAGES = ("index.html", "thanks.html", "privacy.html", "terms.html", "disclosures.html")


def main() -> None:
    brands = json.loads((ROOT / "brands.json").read_text(encoding="utf-8"))
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html"]),
    )
    DIST.mkdir(parents=True, exist_ok=True)
    shared = (TEMPLATES / "shared.css").read_text(encoding="utf-8")

    for brand in brands:
        out = DIST / brand["slug"]
        out.mkdir(parents=True, exist_ok=True)
        theme = (TEMPLATES / f"theme-{brand['theme']}.css").read_text(encoding="utf-8")
        (out / "theme.css").write_text(theme + "\n" + shared, encoding="utf-8")
        for page in PAGES:
            html = env.get_template(page).render(
                brand=brand,
                title=brand["name"] if page == "index.html" else page.replace(".html", "").title(),
            )
            (out / page).write_text(html, encoding="utf-8")
        print(f"built {brand['domain']} -> {out}")


if __name__ == "__main__":
    main()
