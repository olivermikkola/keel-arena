import json
import re
import sys


def valid(data):
    return (isinstance(data, dict) and set(data) == {'workers', 'label'}
            and isinstance(data['workers'], int) and 0 <= data['workers'] <= 16
            and isinstance(data['label'], str)
            and re.fullmatch(r'[A-Za-z0-9-]{1,12}', data['label']) is not None)


try:
    print(json.dumps({'ok': valid(json.load(sys.stdin))}))
except (ValueError, TypeError):
    print(json.dumps({'ok': False}))
