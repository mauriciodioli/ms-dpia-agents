"""Run existing tests, permitting local fixtures and rejecting external connections."""
from pathlib import Path
import argparse
import ast
import socket
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src'), str(ROOT / 'tests')]
original_connect = socket.socket.connect
original_connect_ex = socket.socket.connect_ex


def local_only(method):
    def guarded(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            raise AssertionError('External network forbidden during isolated tests')
        return method(sock, address)
    return guarded


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unit-only', action='store_true', help='Exclude browser UI modules')
    parser.add_argument('--module', action='append', help='Run a specific test module; repeat to select several')
    args = parser.parse_args()
    import pymysql
    with patch('socket.socket.connect', local_only(original_connect)), \
            patch('socket.socket.connect_ex', local_only(original_connect_ex)), \
            patch.object(pymysql, 'connect', side_effect=AssertionError('Live MySQL forbidden')), \
            patch('pymysql.connections.Connection.connect', side_effect=AssertionError('Live MySQL forbidden')):
        if args.module:
            suite = unittest.defaultTestLoader.loadTestsFromNames(args.module)
        elif args.unit_only:
            suite = unittest.TestSuite()
            for path in sorted((ROOT / 'tests').glob('test_*.py')):
                tree = ast.parse(path.read_text(encoding='utf-8'))
                imports = [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
                imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
                browser = path.stem.endswith('_ui') or any(
                    name.startswith('playwright') or name.endswith('_ui') for name in imports)
                if not browser:
                    suite.addTests(unittest.defaultTestLoader.loadTestsFromName(path.stem))
        else:
            suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    sys.exit(not result.wasSuccessful())
