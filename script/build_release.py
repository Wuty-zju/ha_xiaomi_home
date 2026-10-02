# -*- coding: utf-8 -*-
"""Build a deterministic HACS archive from a fixed Git commit."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

COMPONENT_PATH = 'custom_components/xiaomi_home/'
NOTICE_FILES = ('LICENSE.md', 'LegalNotice.md')


def git_bytes(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(['git', '-C', str(repo), *args])


def build_archive(repo: Path, ref: str, tag: str, output: Path) -> dict:
    """Read tracked blobs only; never overwrite an existing output file."""
    sha = git_bytes(repo, 'rev-parse', '--verify', '--end-of-options',
                    f'{ref}^{{commit}}').decode().strip()
    manifest = json.loads(git_bytes(repo, 'show',
                                   f'{sha}:{COMPONENT_PATH}manifest.json'))
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+(?:[a-z0-9.-]+)?', tag):
        raise ValueError('invalid release tag')
    if (manifest.get('version') != tag
            or manifest.get('domain') != 'xiaomi_home'):
        raise ValueError('tag and component manifest do not match')
    tree = git_bytes(repo, 'ls-tree', '-rz', sha, '--', COMPONENT_PATH,
                     *NOTICE_FILES)
    files = {}
    for item in tree.split(b'\0'):
        if not item:
            continue
        metadata, raw_path = item.split(b'\t', 1)
        mode, kind, blob = metadata.decode().split()
        source = raw_path.decode()
        if mode not in ('100644', '100755') or kind != 'blob':
            raise ValueError('release input must contain regular tracked files')
        archive_path = (source[len(COMPONENT_PATH):]
                        if source.startswith(COMPONENT_PATH) else source)
        parts = Path(archive_path).parts
        if (Path(archive_path).is_absolute()
                or any(part in ('..', '__pycache__', '.storage', '.git',
                                '.DS_Store')
                for part in parts)
                or archive_path.endswith(
                    ('.pyc', '.pyo', '.key', '.cert', '.zip'))):
            raise ValueError('runtime data or build output in release input')
        content = git_bytes(repo, 'cat-file', 'blob', blob)
        if archive_path in files and files[archive_path] != content:
            raise ValueError('conflicting license/notice files')
        files[archive_path] = content
    if any(name not in files for name in (*NOTICE_FILES, 'manifest.json')):
        raise ValueError('release is missing manifest or required notices')
    # Stored entries avoid zlib-version differences between build machines.
    # Fixed order, time and permissions make identical Git blobs reproducible.
    with output.open('xb') as file:
        with zipfile.ZipFile(
            file, 'w', compression=zipfile.ZIP_STORED
        ) as archive:
            for name, content in sorted(files.items()):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_STORED
                archive.writestr(info, content)
    return {'sha': sha, 'tag': tag, 'files': len(files),
            'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--ref', required=True)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_archive(args.repo, args.ref, args.tag, args.output)))


if __name__ == '__main__':
    main()
