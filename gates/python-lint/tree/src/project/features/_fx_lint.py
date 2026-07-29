import json
import os


def sloppy(value):
    unused = 1
    try:
        return json.loads(value)
    except Exception:
        print("boom")
        return None
