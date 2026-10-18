"""Publish existing-tag assets without replacing an already uploaded file."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifacts', type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.artifacts / 'release-manifest.json').read_text(encoding='utf-8'))
    tag = manifest['tag']
    repository = os.environ['GITHUB_REPOSITORY']
    files = [*sorted(args.artifacts / name for name in manifest['files']),
             args.artifacts / 'release-manifest.json']
    actual = {path.name for path in args.artifacts.iterdir() if path.is_file()}
    if actual != {path.name for path in files}:
        raise ValueError('Artifact files differ from the release manifest')
    digests = {}
    for path in files:
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if path.name != 'release-manifest.json' and manifest['files'][path.name] != {'sha256': digest, 'bytes': path.stat().st_size}:
            raise ValueError(f'Artifact differs from the release manifest: {path.name}')
        digests[path.name] = 'sha256:' + digest
    pages = subprocess.run(['gh', 'api', '--paginate', '--slurp', f'repos/{repository}/releases'],
                           capture_output=True, text=True, check=True)
    matching = [release for page in json.loads(pages.stdout) for release in page if release['tag_name'] == tag]
    if matching:
        release, = matching
        if release['prerelease'] != manifest['prerelease'] or release['draft']:
            raise ValueError('Existing Release channel differs; do not rewrite it')
    else:
        release = None
    assets = {} if release is None else {item['name']: item for item in release['assets']}
    # Check the whole retained batch before uploading any missing attachment.
    for name, asset in assets.items():
        if name not in digests or asset['digest'] != digests[name]:
            raise ValueError(f'Existing Release asset differs: {name}; publish a new version')
    if release is None:
        command = ['gh', 'release', 'create', tag, '--verify-tag', '--title', 'LenBot ' + manifest['version'],
                   '--notes-file', str(args.artifacts / 'release-notes.md')]
        if manifest['prerelease']:
            command.append('--prerelease')
        subprocess.run(command, check=True)
    for path in files:
        if path.name in assets:
            print(f'Retaining matching Release asset: {path.name}')
        else:
            subprocess.run(['gh', 'release', 'upload', tag, str(path)], check=True)


if __name__ == '__main__':
    main()
