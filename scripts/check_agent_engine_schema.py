"""Offline model/official-DDL comparison. Does not connect, reflect or execute SQL."""
from pathlib import Path
import re
import sys
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable, CreateIndex

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'src')]
from agent_engine.models import metadata
from scripts.prepare_agent_engine_migration import validate_official_migrations


def compare_schema():
    validate_official_migrations()
    sql = '\n'.join((ROOT/'migrations/agent_engine/versions'/name).read_text(encoding='utf-8')
                    for name in ('0001_phase_a.up.sql', '0002_phase_b.up.sql'))
    tables = dict(re.findall(r'CREATE TABLE (ae_\w+)\s*\((.*?)\)\s*ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;', sql, re.S))
    problems = []
    if set(tables) != set(metadata.tables):
        problems.append('table_set')
    normalize = lambda value: re.sub(r'\s+', '', value).lower()
    lines = lambda body: [line.strip().rstrip(',') for line in body.splitlines() if line.strip()]
    dialect = mysql.dialect()
    for name, table in metadata.tables.items():
        if name not in tables:
            continue
        generated = str(CreateTable(table).compile(dialect=dialect))
        body = re.search(r'CREATE TABLE \w+\s*\((.*)\)', generated, re.S).group(1)
        if sorted(map(normalize, lines(body))) != sorted(map(normalize, lines(tables[name]))):
            problems.append(name+':columns_constraints_defaults')
        indexes = {normalize(str(CreateIndex(index).compile(dialect=dialect))) for index in table.indexes}
        actual = {normalize(value) for value in re.findall(r'CREATE INDEX \w+ ON '+name+r' \([^;]+\)', sql)}
        if indexes != actual:
            problems.append(name+':indexes')
        options = table.dialect_options['mysql']
        if any(options.get(key) != value for key, value in {
                'engine': 'InnoDB', 'charset': 'utf8mb4', 'collate': 'utf8mb4_0900_ai_ci'}.items()):
            problems.append(name+':table_options')
    return problems


if __name__ == '__main__':
    problems = compare_schema()
    if problems:
        raise SystemExit('Model/official-DDL differences: '+', '.join(problems))
    print('20 models match official SQL: columns, types, defaults, constraints, indexes and MySQL options. No SQL executed.')
