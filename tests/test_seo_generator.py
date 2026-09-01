import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("assemblymaker_seo", ROOT / "seo" / "generate_article.py")
SEO = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = SEO
SPEC.loader.exec_module(SEO)


class SeoGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / "seo" / "config.json").read_text(encoding="utf-8"))
        cls.keywords = json.loads((ROOT / "keywords.json").read_text(encoding="utf-8"))
        cls.images = json.loads((ROOT / "seo" / "image-library.json").read_text(encoding="utf-8"))

    def test_keyword_rotation_returns_eligible_topic(self):
        choice = SEO.choose_keyword(self.keywords, self.config, {"last_cluster": "", "generated": []})
        self.assertEqual(choice.cluster, "assembly_and_product_instructions")
        self.assertTrue(choice.keyword)
        self.assertTrue(choice.angle)

    def test_all_library_images_exist(self):
        for image in self.images:
            self.assertTrue((ROOT / image["path"]).is_file(), image["path"])

    def test_fixture_passes_content_guards(self):
        choice = SEO.KeywordChoice(
            keyword="assembly instructions",
            cluster="assembly_and_product_instructions",
            searches=50000,
            competition="Low",
            competition_index=0,
            angle="practical guide",
        )
        fixture = json.loads((ROOT / "seo" / "sample-article.json").read_text(encoding="utf-8"))
        image = {"path": "examples/drone.png", "alt": "Drone assembly example"}
        article = SEO.clean_article(fixture, choice, image, self.config)
        self.assertGreaterEqual(SEO.word_count(article["lead"] + article["html"]), self.config["minimum_word_count"])
        self.assertNotIn("<script", article["html"].lower())
        self.assertIn('href="/manual.html"', article["html"])

    def test_static_pages_have_update_markers(self):
        blog = (ROOT / "blog.html").read_text(encoding="utf-8")
        sitemap = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
        SEO.require_markers(blog, SEO.BLOG_START, SEO.BLOG_END, ROOT / "blog.html")
        SEO.require_markers(sitemap, SEO.SITEMAP_START, SEO.SITEMAP_END, ROOT / "sitemap.xml")

    def test_only_approved_authoritative_outbound_links_survive(self):
        allowed = {
            source["url"]
            for source in self.config["approved_external_sources"]
        }
        html = (
            '<p>Read the <a href="https://www.khronos.org/gltf/">official glTF overview</a> '
            'and <a href="https://example.com/unsupported">an unsupported source</a>.</p>'
        )
        cleaned = SEO.sanitize_html(html, {"/manual.html"}, allowed)
        self.assertIn('href="https://www.khronos.org/gltf/"', cleaned)
        self.assertNotIn("example.com", cleaned)


if __name__ == "__main__":
    unittest.main()
