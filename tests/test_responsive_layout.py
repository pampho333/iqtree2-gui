import unittest
from responsive_layout import recommended_geometry, choose_layout


class ResponsiveLayoutTests(unittest.TestCase):
    def test_1366_laptop_excludes_taskbar(self):
        x, y, w, h = recommended_geometry((0, 0, 1366, 720))
        self.assertLessEqual(x + w, 1366)
        self.assertLessEqual(y + h, 720)

    def test_125_percent_logical_resolution(self):
        _, _, w, h = recommended_geometry((0, 0, 1092, 580))
        self.assertLessEqual(w, 1092)
        self.assertLessEqual(h, 580)
        self.assertEqual(choose_layout(w), 'medium')

    def test_negative_monitor_origin(self):
        x, y, w, h = recommended_geometry((-1600, 0, 0, 860))
        self.assertGreaterEqual(x, -1600)
        self.assertLessEqual(x + w, 0)

    def test_small_screen_does_not_force_minimum(self):
        _, _, w, h = recommended_geometry((0, 0, 640, 480))
        self.assertLessEqual(w, 640)
        self.assertLessEqual(h, 480)
        self.assertEqual(choose_layout(w), 'extra_narrow')

    def test_width_switches(self):
        self.assertEqual(choose_layout(1280), 'wide')
        self.assertEqual(choose_layout(1050), 'medium')
        self.assertEqual(choose_layout(780), 'narrow')
        self.assertEqual(choose_layout(700), 'extra_narrow')


if __name__ == '__main__':
    unittest.main()
