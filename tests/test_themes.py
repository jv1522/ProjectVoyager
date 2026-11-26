import unittest

from voyager.themes import DEFAULT_THEME, INSTRUMENT_THEMES, THEMES, build_stylesheet


class ThemeTests(unittest.TestCase):
    def test_instrument_themes_exist(self):
        self.assertIn(DEFAULT_THEME, THEMES)
        for key in INSTRUMENT_THEMES.values():
            self.assertIn(key, THEMES)

    def test_every_theme_builds_a_stylesheet_with_its_colours(self):
        for theme in THEMES.values():
            sheet = build_stylesheet(theme)
            self.assertIn(theme.background, sheet)
            self.assertIn(theme.accent, sheet)


if __name__ == "__main__":
    unittest.main()
