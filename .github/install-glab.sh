#!/usr/bin/env bash
# Install the tested CLI into the current Actions job, never the user's system.
set -euo pipefail
: "${RUNNER_TEMP:?GitHub Actions RUNNER_TEMP is required}"
: "${GITHUB_PATH:?GitHub Actions GITHUB_PATH is required}"
version=1.124.0
case "${RUNNER_OS:?}/${RUNNER_ARCH:?}" in
  Linux/X64) platform=linux_amd64 ;;
  Linux/ARM64) platform=linux_arm64 ;;
  macOS/X64) platform=darwin_amd64 ;;
  macOS/ARM64) platform=darwin_arm64 ;;
  *) printf 'Unsupported glab CI platform: %s/%s\n' "$RUNNER_OS" "$RUNNER_ARCH" >&2; exit 1 ;;
esac
run=$(mktemp -d "$RUNNER_TEMP/glab.XXXXXX")
archive="glab_${version}_${platform}.tar.gz"
base="https://gitlab.com/gitlab-org/cli/-/releases/v${version}/downloads"
curl --fail --silent --show-error --location --retry 3 "$base/$archive" -o "$run/$archive"
curl --fail --silent --show-error --location --retry 3 "$base/checksums.txt" -o "$run/checksums.txt"
python3 - "$run" "$archive" <<'PY'
import hashlib
from pathlib import Path
import sys
import tarfile

run, name = Path(sys.argv[1]), sys.argv[2]
matches = [line.split()[0] for line in (run / 'checksums.txt').read_text().splitlines()
           if len(line.split()) == 2 and line.split()[1].lstrip('*') == name]
if len(matches) != 1 or hashlib.sha256((run / name).read_bytes()).hexdigest() != matches[0]:
    raise SystemExit('glab release checksum verification failed')
destination = run / 'bin'
destination.mkdir()
with tarfile.open(run / name, 'r:gz') as archive:
    candidates = [m for m in archive.getmembers() if m.name.removeprefix('./') in ('bin/glab', 'glab') and m.isfile()]
    if len(candidates) != 1:
        raise SystemExit('expected exactly one regular glab binary in release archive')
    with archive.extractfile(candidates[0]) as source, (destination / 'glab').open('xb') as target:
        target.write(source.read())
(destination / 'glab').chmod(0o755)
PY
"$run/bin/glab" --version
printf '%s\n' "$run/bin" >> "$GITHUB_PATH"
