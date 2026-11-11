"""Print the additive audit-table migration. Never connects to or modifies a database.

Run before deploying deletion endpoints: python scripts/prepare_agent_deletion_migration.py
Review and apply the printed DDL manually. Existing history and constraints are preserved.
"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from sqlalchemy.schema import CreateTable,CreateIndex
from sqlalchemy.dialects import mysql
from agent_engine.models import agent_deletions
if __name__=='__main__':
 print('-- Additive migration; no table or column is dropped. Apply once after review.')
 print(str(CreateTable(agent_deletions).compile(dialect=mysql.dialect())).strip()+';')
 for index in sorted(agent_deletions.indexes,key=lambda i:i.name):print(str(CreateIndex(index).compile(dialect=mysql.dialect()))+';')
