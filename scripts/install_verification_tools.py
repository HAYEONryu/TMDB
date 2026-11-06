"""Install checksum-pinned upstream tools into an explicit project directory."""
import argparse
import hashlib
import io
from pathlib import Path
import platform
import tarfile
import urllib.request

AGE_VERSION = '1.3.2'
AGE_HASHES = {
    ('Darwin', 'arm64'): 'e2020b073c44f692685a24d6abc378817eb81ffaaf49fd0531ef8565f767f2f5',
    ('Linux', 'x86_64'): 'cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10',
    ('Linux', 'aarch64'): '6b8dc4333c53a5a57c9e5834e3a48f92605d7154014cd07269ff3327db5d37f4',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool', choices=['age', 'caddy'], required=True)
    parser.add_argument('--directory', type=Path, default=Path(__file__).resolve().parents[1] / '.local/bin')
    args = parser.parse_args()
    target = platform.system(), platform.machine()
    if args.tool == 'age':
        if target not in AGE_HASHES:
            raise SystemExit('Unsupported platform; obtain and verify age from its official release.')
        os_name = 'darwin' if target[0] == 'Darwin' else 'linux'
        arch = 'amd64' if target[1] == 'x86_64' else 'arm64'
        url = f'https://github.com/FiloSottile/age/releases/download/v{AGE_VERSION}/age-v{AGE_VERSION}-{os_name}-{arch}.tar.gz'
        expected = AGE_HASHES[target]
        members = {'age/age': 'age', 'age/age-keygen': 'age-keygen'}
    else:
        if target != ('Darwin', 'arm64'):
            raise SystemExit('This Caddy verifier is pinned for the current Mac only.')
        url = 'https://github.com/caddyserver/caddy/releases/download/v2.10.2/caddy_2.10.2_mac_arm64.tar.gz'
        expected = 'cc9ad20742ea7bfee5dd1d435d42ab7fcf8592294f9ec43bf08fd21cbe448bc4'
        members = {'caddy': 'caddy'}
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read(100 * 1024 * 1024 + 1)
    if len(data) > 100 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit('UPSTREAM_CHECKSUM_MISMATCH')
    args.directory.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        for name, output in members.items():
            member = archive.getmember(name)
            if not member.isfile():
                raise SystemExit('UPSTREAM_ARCHIVE_MEMBER_INVALID')
            destination = args.directory / output
            if destination.exists():
                raise SystemExit(f'{output} already exists; no overwrite performed.')
            with destination.open('xb') as handle:
                handle.write(archive.extractfile(member).read())
            destination.chmod(0o755)
    print(f'{args.tool}: verified SHA-256 and installed')


if __name__ == '__main__':
    main()
