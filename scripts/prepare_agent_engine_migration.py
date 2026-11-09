"""Read-only static verification of the externally validated official migrations.

The historical command name is retained for compatibility. Generation (--write)
and SQL execution are deliberately unavailable. No application/database imports.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / 'migrations/agent_engine/versions'
ORDER = ('0000_preflight.readonly.sql', '0001_phase_a.up.sql', '0002_phase_b.up.sql')
OFFICIAL = frozenset((*ORDER, 'manifest.json', 'VALIDACION.txt'))


def validate_official_migrations() -> dict:
    if {path.name for path in DIRECTORY.iterdir()} != OFFICIAL:
        raise ValueError('Unexpected or missing official migration files')
    manifest = json.loads((DIRECTORY / 'manifest.json').read_text(encoding='utf-8'))
    if (manifest['execution'] != 'manual_only' or manifest['automatic_execution'] is not False
            or manifest['execution_order'] != list(ORDER) or manifest['migration_order'] != list(ORDER[1:])):
        raise ValueError('Invalid manual execution order')
    if set(manifest['files']) != set(ORDER) | {'VALIDACION.txt'}:
        raise ValueError('Incomplete checksum manifest')
    for name, info in manifest['files'].items():
        data = (DIRECTORY / name).read_bytes()
        if sha256(data).hexdigest() != info['sha256'] or len(data) != info['bytes']:
            raise ValueError('Checksum/size mismatch: ' + name)
    tables = []
    for name in ORDER:
        sql = (DIRECTORY / name).read_text(encoding='utf-8-sig')
        uncommented = re.sub(r'/\*.*?\*/|--[^\n]*', '', sql, flags=re.S)
        statements = [part.strip() for part in uncommented.split(';') if part.strip()]
        allowed = r'SELECT\b' if name == ORDER[0] else r'CREATE\s+(?:TABLE|INDEX)\b'
        if not statements or any(not re.match(allowed, statement, flags=re.I) for statement in statements):
            raise ValueError('Unexpected SQL statement type: ' + name)
        names = re.findall(r'CREATE\s+TABLE\s+(ae_\w+)\s*\(', uncommented, flags=re.I)
        if name != ORDER[0] and len(names) != (19 if name == ORDER[1] else 1):
            raise ValueError('Unexpected table count: ' + name)
        tables.extend(names)
    if len(tables) != 20 or len(set(tables)) != 20:
        raise ValueError('Expected exactly 20 distinct ae_* tables')
    return manifest


def artifacts(version='0001_phase_a') -> dict[str, str]:
    """Compatibility reader for existing static tests; never generates SQL."""
    validate_official_migrations()
    if version not in ('0001_phase_a', '0002_phase_b'):
        raise ValueError('Unknown migration version')
    name = version + '.up.sql'
    return {'versions/' + name: (DIRECTORY / name).read_text(encoding='utf-8')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', choices=['0001_phase_a', '0002_phase_b'],
                        help='Compatibility option; the complete official bundle is always verified.')
    parser.add_argument('--check', action='store_true', required=True)
    parser.parse_args()
    try:
        validate_official_migrations()
    except (ValueError, KeyError, OSError) as error:
        raise SystemExit('Static verification failed: ' + str(error)) from None
    print('Static verification OK: 20 ae_* tables; SQL/validation checksums verified. No SQL executed.')


if __name__ == '__main__':
    main()
