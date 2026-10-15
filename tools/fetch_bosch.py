#!/usr/bin/env python3
"""Materialize the pinned Bosch API only in a generated build directory."""
import hashlib
import io
from pathlib import Path
import sys
import tarfile
import urllib.request

COMMIT = 'c1ed227e7bb7da1fa600bbd4e5c82d0da1eb416a'
SHA256 = '80e315094b3b057f2b43f145f87bb20810c54be92cb3786b8abdcd3007596b1b'
FILES = ('bmi08.h', 'bmi08x.h', 'bmi08_defs.h', 'bmi08a.c', 'bmi08g.c', 'bmi08xa.c', 'LICENSE')


def main():
    dest = Path(sys.argv[1])
    archive = dest.parent / ('bosch-' + COMMIT + '.tar.gz')
    dest.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        data = archive.read_bytes()
    else:
        data = urllib.request.urlopen(
            f'https://codeload.github.com/boschsensortec/BMI08x_SensorAPI/tar.gz/{COMMIT}',
            timeout=30).read()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise SystemExit('Bosch archive SHA256 mismatch')
    if not archive.exists():
        archive.write_bytes(data)
    # Extract only explicit regular files; never trust archive paths.
    with tarfile.open(fileobj=io.BytesIO(data)) as bundle:
        for name in FILES:
            member = bundle.getmember(f'BMI08x_SensorAPI-{COMMIT}/{name}')
            if not member.isfile():
                raise SystemExit('Unexpected archive member: ' + name)
            content = bundle.extractfile(member).read()
            target = dest / name
            if not target.exists() or target.read_bytes() != content:
                target.write_bytes(content)


if __name__ == '__main__':
    main()
