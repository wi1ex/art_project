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
unset MOCK_FAIL_CONFIG MOCK_FAIL_ALL_UP MOCK_FAIL_CURRENT_POINTER
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
is_down=false
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
    down) is_down=true ;;
  esac
  shift
done
if $is_config || $is_up || $is_down; then
  [[ -f "$API_ENV_FILE" ]] || { echo 'Mock Compose needs its runtime env file.' >&2; exit 1; }
  printf 'runtime=%s\n' "$(sha256sum "$API_ENV_FILE" | cut -d' ' -f1)" >> "$MOCK_LOG"
fi
if $is_config && [[ "${MOCK_FAIL_CONFIG:-0}" == 1 ]]; then exit 1; fi
if $is_up; then
  if grep -q 'APP_IMAGE=art-project:bbbb' "$env_file" || [[ "${MOCK_FAIL_ALL_UP:-0}" == 1 ]]; then exit 1; fi
fi
MOCK
chmod +x "$temporary/bin/docker"
real_mv=$(command -v mv)
export REAL_MV="$real_mv" MOCK_POINTER_MARKER="$temporary/pointer-failure"
cat > "$temporary/bin/mv" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${MOCK_FAIL_CURRENT_POINTER:-0}" == 1 && "${@: -1}" == */current && ! -e "$MOCK_POINTER_MARKER" ]]; then
  touch "$MOCK_POINTER_MARKER"
  exit 1
fi
exec "$REAL_MV" "$@"
MOCK
chmod +x "$temporary/bin/mv"

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
old_runtime="$temporary/old-runtime.env"
new_runtime="$temporary/new-runtime.env"
printf "LEADS_ENABLED='false'\nTELEGRAM_BOT_TOKEN=''\nTELEGRAM_ADMIN_PASSWORD='old-password'\nTELEGRAM_RETRY_SECONDS='300'\nLEADS_ALLOWED_ORIGINS=''\n" > "$old_runtime"
printf "LEADS_ENABLED='false'\nTELEGRAM_BOT_TOKEN=''\nTELEGRAM_ADMIN_PASSWORD='new-password'\nTELEGRAM_RETRY_SECONDS='300'\nLEADS_ALLOWED_ORIGINS=''\n" > "$new_runtime"

# Runtime secrets must exist before loading or starting any image.
prepare "$good"
if bash "$root/incoming/$good/release.sh" "$good"; then echo 'Expected missing API configuration failure' >&2; exit 1; fi
[[ ! -s "$MOCK_LOG" ]]
# Malformed stdin cannot modify config or start an image.
if printf "LEADS_ENABLED='false'\n" | bash "$root/incoming/$good/release.sh" "$good" --runtime-config-stdin; then
    echo 'Expected invalid runtime stdin failure' >&2; exit 1
fi
[[ ! -e "$root/config/api.env" && ! -s "$MOCK_LOG" ]]

# A first failed deployment keeps config available for teardown, then removes it.
prepare "$bad"
if bash "$root/incoming/$bad/release.sh" "$bad" --runtime-config-stdin < "$new_runtime"; then
    echo 'Expected first runtime deployment failure' >&2; exit 1
fi
[[ ! -e "$root/config/api.env" && ! -e "$root/current" ]]
grep -q ' down --remove-orphans' "$MOCK_LOG"

cp "$old_runtime" "$root/config/api.env"
chmod 600 "$root/config/api.env"

prepare "$bad"
if bash "$root/incoming/$bad/release.sh" "$bad"; then echo 'Expected failure' >&2; exit 1; fi
[[ ! -e "$root/current" ]]
grep -q ' down --remove-orphans' "$MOCK_LOG"
if grep -q -- '--volumes' "$MOCK_LOG"; then echo 'Deployment must preserve the SQLite volume' >&2; exit 1; fi

prepare "$good"
bash "$root/incoming/$good/release.sh" "$good"
[[ $(readlink "$root/current") == "$root/incoming/$good" ]]
[[ ! -e "$root/current/image.tar.gz" ]]
grep -qx "APP_IMAGE=art-project:$good" "$root/current/release.env"
grep -qx "API_IMAGE=art-project-api:$good" "$root/current/release.env"
[[ $(wc -l < "$root/current/release.env") == 2 ]]

if bash "$root/incoming/$bad/release.sh" "$bad"; then echo 'Expected failure' >&2; exit 1; fi
[[ $(readlink "$root/current") == "$root/incoming/$good" ]]
grep -q "$good.*up.*--remove-orphans" "$MOCK_LOG"

# Failed image startup restores old config before restarting the prior API.
if bash "$root/incoming/$bad/release.sh" "$bad" --runtime-config-stdin < "$new_runtime"; then
    echo 'Expected runtime rollback failure' >&2; exit 1
fi
cmp -s "$root/config/api.env" "$old_runtime"
old_hash=$(sha256sum "$old_runtime" | cut -d' ' -f1)
[[ $(tail -n 1 "$MOCK_LOG") == "runtime=$old_hash" ]]

export MOCK_FAIL_CONFIG=1
prepare "$next"
if bash "$root/incoming/$next/release.sh" "$next" --runtime-config-stdin < "$new_runtime"; then echo 'Expected invalid Compose configuration failure' >&2; exit 1; fi
[[ $(readlink "$root/current") == "$root/incoming/$good" ]]
cmp -s "$root/config/api.env" "$old_runtime"
unset MOCK_FAIL_CONFIG

# Pointer promotion failure restores runtime, old containers and release pointers.
export MOCK_FAIL_CURRENT_POINTER=1
prepare "$next"
if bash "$root/incoming/$next/release.sh" "$next" --runtime-config-stdin < "$new_runtime"; then
    echo 'Expected pointer promotion failure' >&2; exit 1
fi
[[ $(readlink "$root/current") == "$root/incoming/$good" ]]
[[ ! -e "$root/previous" ]]
cmp -s "$root/config/api.env" "$old_runtime"
unset MOCK_FAIL_CURRENT_POINTER

prepare "$next"
: > "$MOCK_LOG"
bash "$root/incoming/$next/release.sh" "$next" --runtime-config-stdin < "$new_runtime"
[[ $(readlink "$root/current") == "$root/incoming/$next" ]]
[[ $(readlink "$root/previous") == "$root/incoming/$good" ]]
cmp -s "$root/config/api.env" "$new_runtime"
[[ $(stat -c '%a' "$root/config/api.env") == 600 ]]
[[ -z $(find "$root/config" -name '.api.env.*' -print) ]]
if grep -qE 'old-password|new-password' "$MOCK_LOG"; then echo 'Runtime secrets leaked to logs.' >&2; exit 1; fi
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
grep -q "$legacy.*up.*--remove-orphans" "$MOCK_LOG"

if bash "$root/incoming/$next/release.sh" '../invalid'; then exit 1; fi
echo 'Release tests passed: stdin runtime config, preflight, secret retention, first deployment, runtime/image/pointer rollback, legacy rollback, failed rollback, image retention, invalid SHA.'
