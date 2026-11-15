import unittest

from scripts.extract_public_nav_counts import extract_counts


def menu(label, count):
    return (f'<a class="header-menu-dropdown__format">'
            f'<span class="header-menu-dropdown__format-label">{label}</span>'
            f'<span class="header-menu-dropdown__format-count">{count}</span></a>')


def complete_menu():
    return ''.join(menu(label, count) for label, count in [
        ('Курсы', '107 материалов'), ('Статьи', '1 002 материала'),
        ('Вебинары', '12 материалов'), ('Подкасты', '59 материалов'),
        ('Шаблоны', '247 материалов'),
    ])


class NavCountsTests(unittest.TestCase):
    def test_extracts_displayed_counts_with_thousands_separator(self):
        self.assertEqual(extract_counts(complete_menu()), {
            'course': 107, 'article': 1002, 'webinar': 12, 'podcast': 59, 'document': 247,
        })

    def test_refuses_missing_or_conflicting_counts(self):
        with self.assertRaisesRegex(ValueError, 'Missing'):
            extract_counts(menu('Курсы', '107 материалов'))
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            extract_counts(complete_menu() + menu('Курсы', '108 материалов'))
