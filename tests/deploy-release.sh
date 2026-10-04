#!/usr/bin/env bash
set -euo pipefail
repository=$(cd "$(dirname "$0")/.." && pwd)
temporary_root=$(cd "${TMPDIR:-/tmp}" && pwd)
temporary=$(mktemp -d "$temporary_root/art-project-release.XXXXXX")
[[ "$temporary" == "$temporary_root/"art-project-release.* ]] || exit 1
trap 'rm -rf -- "$temporary"' EXIT
root="$temporary/app"
mkdir -p "$root/incoming" "$root/config" "$temporary/bin"
export MOCK_LOG="$temporary/docker.log"
export API_ENV_FILE="$root/config/api.env"
export GEOIP_DIRECTORY="$root/config/geoip"
unset MOCK_FAIL_CONFIG MOCK_FAIL_ALL_UP
export PATH="$temporary/bin:$PATH"
# Git Bash on Windows lacks flock. This test covers release transitions,
# not OS-level locking; Linux CI exercises the real flock command.
if ! command -v flock > /dev/null; then
    printf '#!/usr/bin/env bash\nexit 0\n' > "$temporary/bin/flock"
    chmod +x "$temporary/bin/flock"
fi
cat > "$temporary/bin/docker" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$MOCK_LOG"
env_file=''
is_up=false
is_config=false
if [[ "${1:-}" == image && "${2:-}" == ls ]]; then
  repository=$3
  for suffix in aaaa bbbb cccc dddd; do
    printf '%s:%s\n' "$repository" "$(printf '%-40s' "$suffix" | tr ' ' "${suffix:0:1}")"
  done
  # Even an unexpected foreign reference must never be removed.
  echo 'another-app:release'
  exit 0
fi
while (( $# )); do
  case "$1" in
    --env-file) env_file=$2; shift ;;
    up) is_up=true ;;
    config) is_config=true ;;
  esac
  shift
done
if $is_config && [[ "${MOCK_FAIL_CONFIG:-0}" == 1 ]]; then exit 1; fi
if $is_up; then
  if grep -q 'APP_IMAGE=art-project:bbbb' "$env_file" || [[ "${MOCK_FAIL_ALL_UP:-0}" == 1 ]]; then exit 1; fi
fi
MOCK
chmod +x "$temporary/bin/docker"

prepare() {
    mkdir -p "$root/incoming/$1"
    touch "$root/incoming/$1/image.tar.gz"
    cp "$repository/deploy/compose.production.yaml" "$root/incoming/$1/"
    sed "s|root=/opt/art-project|root=$root|" "$repository/deploy/release.sh" > "$root/incoming/$1/release.sh"
}
good=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
bad=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
next=cccccccccccccccccccccccccccccccccccccccc
legacy=dddddddddddddddddddddddddddddddddddddddd

# Runtime secrets must exist before loading or starting any image.
prepare "$good"
if bash "$root/incoming/$good/release.sh" "$good"; then echo 'Expected missing API configuration failure' >&2; exit 1; fi
[[ ! -s "$MOCK_LOG" ]]
printf 'LEADS_ENABLED=false\n' > "$root/config/api.env"
chmod 600 "$root/config/api.env"

# A regular file cannot be used as the GeoIP directory; reject before loading images.
touch "$temporary/geoip-file"
if GEOIP_DIRECTORY="$temporary/geoip-file" bash "$root/incoming/$good/release.sh" "$good" > "$temporary/geoip-failure.log" 2>&1; then
    echo 'Expected invalid GeoIP directory failure' >&2
    exit 1
fi
grep -q 'GeoIP directory is unavailable' "$temporary/geoip-failure.log"
[[ ! -s "$MOCK_LOG" ]]

prepare "$bad"
if bash "$root/incoming/$bad/release.sh" "$bad"; then echo 'Expected failure' >&2; exit 1; fi
[[ ! -e "$root/current" ]]
[[ -d "$GEOIP_DIRECTORY" ]]
[[ ! -e "$GEOIP_DIRECTORY/country.mmdb" ]]
grep -q ' down --remove-orphans' "$MOCK_LOG"
if grep -q -- '--volumes' "$MOCK_LOG"; then echo 'Deployment must preserve the SQLite volume' >&2; exit 1; fi

# Simulate a GeoIP directory installed by root: deploy can read it, but cannot chmod it.
export REAL_CHMOD=$(command -v chmod)
cat > "$temporary/bin/chmod" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${@: -1}" == "$GEOIP_DIRECTORY" ]]; then
  echo 'Cannot chmod a root-owned GeoIP directory' >&2
  exit 1
fi
exec "$REAL_CHMOD" "$@"
MOCK
"$REAL_CHMOD" +x "$temporary/bin/chmod"

prepare "$good"
bash "$root/incoming/$good/release.sh" "$good"
[[ $(readlink "$root/current") == "$root/incoming/$good" ]]
[[ ! -e "$root/current/image.tar.gz" ]]
grep -qx "APP_IMAGE=art-project:$good" "$root/current/release.env"
grep -qx "API_IMAGE=art-project-api:$good" "$root/current/release.env"
[[ $(wc -l < "$root/current/release.env") == 2 ]]

if bash "$root/incoming/$bad/release.sh" "$bad"; then echo 'Expected failure' >&2; exit 1; fi
[[ $(readlink "$root/current") == "$root/incoming/$good" ]]
tail -n 1 "$MOCK_LOG" | grep -q "$good.*up.*--remove-orphans"

export MOCK_FAIL_CONFIG=1
prepare "$next"
if bash "$root/incoming/$next/release.sh" "$next"; then echo 'Expected invalid Compose configuration failure' >&2; exit 1; fi
[[ $(readlink "$root/current") == "$root/incoming/$good" ]]
unset MOCK_FAIL_CONFIG

prepare "$next"
: > "$MOCK_LOG"
bash "$root/incoming/$next/release.sh" "$next"
[[ $(readlink "$root/current") == "$root/incoming/$next" ]]
[[ $(readlink "$root/previous") == "$root/incoming/$good" ]]
for repository in art-project art-project-api; do
  grep -qx "image rm $repository:$bad" "$MOCK_LOG"
  grep -qx "image rm $repository:$legacy" "$MOCK_LOG"
  if grep -Eq "image rm $repository:($good|$next)$" "$MOCK_LOG"; then echo 'Current or previous image was removed' >&2; exit 1; fi
done
if grep -q 'image rm another-app' "$MOCK_LOG"; then echo 'A foreign image was removed' >&2; exit 1; fi

# A failed rollback leaves the last successful release pointers unchanged.
export MOCK_FAIL_ALL_UP=1
if bash "$root/incoming/$bad/release.sh" "$bad" > "$temporary/failure.log" 2>&1; then echo 'Expected rollback failure' >&2; exit 1; fi
grep -q 'ROLLBACK FAILED' "$temporary/failure.log"
[[ $(readlink "$root/current") == "$root/incoming/$next" ]]
unset MOCK_FAIL_ALL_UP

# Rollback also supports the existing release format without an API image.
mkdir -p "$root/incoming/$legacy"
printf 'APP_IMAGE=art-project:%s\n' "$legacy" > "$root/incoming/$legacy/release.env"
printf 'services:\n  web:\n    image: ${APP_IMAGE}\n' > "$root/incoming/$legacy/compose.production.yaml"
ln -sfn "$root/incoming/$legacy" "$root/current"
if bash "$root/incoming/$bad/release.sh" "$bad"; then echo 'Expected failure before legacy rollback' >&2; exit 1; fi
[[ $(readlink "$root/current") == "$root/incoming/$legacy" ]]
tail -n 1 "$MOCK_LOG" | grep -q "$legacy.*up.*--remove-orphans"

if bash "$root/incoming/$next/release.sh" '../invalid'; then exit 1; fi
echo 'Release tests passed: runtime configuration, GeoIP directory, both images, first deployment, rollback, legacy rollback, failed rollback, retention, invalid SHA.'
