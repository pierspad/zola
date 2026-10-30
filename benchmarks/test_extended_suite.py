import unittest
from extended_suite import COMMON, selected_cases


class ExtendedSuiteTests(unittest.TestCase):
    def test_common_and_opt_in(self):
        self.assertEqual(selected_cases(COMMON, False), COMMON)
        for count in (50000, 100000):
            with self.assertRaises(ValueError):
                selected_cases(f'{count}x1', False)
            self.assertEqual(selected_cases(f'{count}x1', True), f'{count}x1')
        with self.assertRaises(ValueError):
            selected_cases('4000x15', False)

    def test_invalid_cases(self):
        for value in ('no', '100x0', '100x16', '1x1', ''):
            with self.assertRaises(ValueError):
                selected_cases(value, True)


if __name__ == '__main__':
    unittest.main()
