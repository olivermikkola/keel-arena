import json
import sys


def total(data):
    if not isinstance(data, dict) or set(data) != {'csv'} or not isinstance(data['csv'], str):
        raise ValueError('invalid input')
    lines = data['csv'].splitlines()
    if not lines or lines[0] != 'item,quantity,unit_cents':
        raise ValueError('invalid header')
    amount = 0
    for line in lines[1:]:
        item, quantity, cents = line.split(',')
        if not quantity.isdigit() or not cents.isdigit():
            raise ValueError('invalid number')
        amount += int(quantity) * int(cents)
    return amount


try:
    print(json.dumps({'ok': True, 'total_cents': total(json.load(sys.stdin))}))
except (ValueError, TypeError):
    print(json.dumps({'ok': False}))
