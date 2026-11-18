"""Deterministic comparisons. SQL ENUM never receives SIN_CAMBIOS."""
from decimal import Decimal
FIELDS=('title','seller','location','url','currency','price')

def compare(previous,current):
    details={'anterior':{k:previous.get(k) for k in FIELDS} if previous else None,
             'actual':{k:current.get(k) for k in FIELDS}}
    if previous is None:return 'NUEVO',details
    old,new=previous.get('price'),current.get('price')
    comparable=old is not None and new is not None and previous.get('currency') is not None and previous.get('currency')==current.get('currency')
    if comparable:
        if Decimal(str(new))<Decimal(str(old)):return 'PRECIO_BAJO',details
        if Decimal(str(new))>Decimal(str(old)):return 'PRECIO_SUBIO',details
    if any(previous.get(k)!=current.get(k) for k in FIELDS):return 'DATOS_CAMBIARON',details
    return 'SIN_CAMBIOS',details
