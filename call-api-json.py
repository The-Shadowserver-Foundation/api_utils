import sys
import json
import importlib
api = importlib.import_module('call-api')

if __name__ == '__main__':
    if len(sys.argv) < 3:
        sys.exit("Usage: call-api-json.py method /path/to/file.json")
    with open(sys.argv[2]) as fh:
        data = json.load(fh)
    result = api.api_call(sys.argv[1], data)
    if len(sys.argv) > 3 and sys.argv[3] == 'pretty':
        print(json.dumps(json.loads(result), indent=4))
    else:
        print(result.decode('utf-8'))
