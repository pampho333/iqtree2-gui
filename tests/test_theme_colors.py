import unittest
from theme_colors import DEFAULT_THEME, normalize_hex, mix, resolve_theme


class ThemeColorsTests(unittest.TestCase):
    def test_hex_accepts_only_six_digit_codes(self):
        self.assertEqual(normalize_hex(' #09eEAf '), '#09EEAF')
        self.assertEqual(normalize_hex('00ff00'), '#00FF00')
        for invalid in ('red', '#FA3', '#1234567', '#FFGGFF', '', None):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                normalize_hex(invalid)

    def test_color_mixing(self):
        self.assertEqual(mix('#000000', '#FFFFFF', 0), '#000000')
        self.assertEqual(mix('#000000', '#FFFFFF', 1), '#FFFFFF')
        self.assertEqual(mix('#000000', '#FFFFFF', 0.5), '#808080')

    def test_palette(self):
        p = resolve_theme(DEFAULT_THEME)
        self.assertEqual(p['foreground'], '#6CCF83')
        self.assertEqual(p['background'], '#000000')
        self.assertEqual(p['accent'], '#7ADF95')
        self.assertIn('select', p)
        self.assertIn('edge', p)

    def test_bad_palette(self):
        with self.assertRaises((ValueError, KeyError)):
            resolve_theme({'background': 'nope'})
