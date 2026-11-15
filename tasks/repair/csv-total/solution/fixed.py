import csv
import io
import json
import re
import sys


def total(data):
    if not isinstance(data, dict) or set(data) != {'csv'} or not isinstance(data['csv'], str):
        raise ValueError('invalid input')
    rows = iter(csv.reader(io.StringIO(data['csv'], newline=''), strict=True))
    if next(rows, None) != ['item', 'quantity', 'unit_cents']:
        raise ValueError('invalid header')
    amount = 0
    for row in rows:
        if len(row) != 3 or not re.fullmatch(r'[0-9]+', row[1]) or not re.fullmatch(r'[0-9]+', row[2]):
            raise ValueError('invalid row')
        amount += int(row[1]) * int(row[2])
    return amount


try:
    print(json.dumps({'ok': True, 'total_cents': total(json.load(sys.stdin))}))
except (ValueError, TypeError, csv.Error):
    print(json.dumps({'ok': False}))
