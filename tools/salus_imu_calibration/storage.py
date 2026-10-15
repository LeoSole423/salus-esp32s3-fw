"""Versioned JSON and atomic create-only storage: existing profiles are preserved."""
import json
import os
from pathlib import Path
import tempfile


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: '+key)
        result[key] = value
    return result


def load_json(path):
    with open(path, encoding='utf-8') as stream:
        value = json.load(stream, object_pairs_hook=_unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON: '+value)))
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object')
    return value


def save_new(path, data):
    target = Path(path)
    text = json.dumps(data, indent=2, allow_nan=False)+'\n'
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.'+target.name+'-', dir=target.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        # Atomic publication that refuses replacement, even in a concurrent race.
        os.link(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(temporary)
