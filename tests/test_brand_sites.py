from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANDS = json.loads((ROOT / "brand-sites" / "brands.json").read_text(encoding="utf-8"))


class BrandSiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import runpy

        runpy.run_path(str(ROOT / "brand-sites" / "build.py"), run_name="__main__")

    def test_twelve_brands_keep_their_addresses(self) -> None:
        slugs = [b["slug"] for b in BRANDS]
        self.assertEqual(len(slugs), 12)
        self.assertIn("vaultifypro", slugs)
        self.assertIn("lendinganchor", slugs)
        for brand in BRANDS:
            index = (ROOT / "brand-sites" / "dist" / brand["slug"] / "index.html").read_text(encoding="utf-8")
            self.assertIn(brand["name"], index)
            self.assertIn(brand["domain"], index)
            self.assertNotIn("pineova", index.lower())
            self.assertNotIn("agateara", index.lower())
            self.assertNotIn("Woodmont", index)

    def test_three_distinct_themes(self) -> None:
        themes = {b["theme"] for b in BRANDS}
        self.assertEqual(themes, {"dawn", "harbor", "grove"})
        dawn = (ROOT / "brand-sites" / "dist" / "vaultifypro" / "theme.css").read_text(encoding="utf-8")
        harbor = (ROOT / "brand-sites" / "dist" / "trustpathlending" / "theme.css").read_text(encoding="utf-8")
        self.assertIn("#c2410c", dawn)
        self.assertIn("#1d4ed8", harbor)
        self.assertNotEqual(dawn, harbor)


if __name__ == "__main__":
    unittest.main()
