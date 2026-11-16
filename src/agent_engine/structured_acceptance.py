"""Conservative exact-identity acceptance. No semantic keyword matching.

A free-text/category request still needs interpretation. Existing canonical
contracts do not carry verified product taxonomy, so do not invent it. This fast
path is limited to an explicit product URL and observable price constraints.
"""
import re
from .adaptive_steps import product_records


def sufficient(job,task,output):
    objective=job['request_snapshot'].get('objective') or job['request_snapshot'].get('instructions','')
    # Only a request consisting of a specific product reference is unambiguous
    # without interpreting its prose. More complex requirements go to reasoning.
    if not re.fullmatch(r'https?://[^\s]+',objective.strip()):return False
    products=product_records([output])
    return any(row['url']==objective.strip() for row in products)
