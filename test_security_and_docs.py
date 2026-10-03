"""Compatibility entry point for the isolated regression suite.

The former script used the application database, seeded published passwords,
and could contact live gateways. Test fixtures now create disposable databases.
"""
import sys
import unittest


def run_test_suite():
    suite = unittest.defaultTestLoader.discover('tests', pattern='test_*.py')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return result.wasSuccessful()


if __name__ == '__main__':
    sys.exit(0 if run_test_suite() else 1)
