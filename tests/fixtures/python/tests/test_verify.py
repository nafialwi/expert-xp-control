import unittest

class VerifyFixture(unittest.TestCase):
    def test_clear(self):
        self.assertEqual(2 + 2, 4)

if __name__ == '__main__':
    unittest.main()
