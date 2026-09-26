#!/usr/bin/env bash
set -euo pipefail
repository=$(cd "$(dirname "$0")/.." && pwd)
temporary=$(mktemp -d)
trap 'rm -rf -- "$temporary"' EXIT
root="$temporary/app"
mkdir -p "$root/incoming" "$temporary/bin"
export MOCK_LOG="$temporary/docker.log"
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
while (( $# )); do
  case "$1" in
    --env-file) env_file=$2; shift ;;
    up) is_up=true ;;
  esac
  shift
done
if $is_up && grep -q 'APP_IMAGE=art-project:bbbb' "$env_file"; then exit 1; fi
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
prepare "$bad"
if bash "$root/incoming/$bad/release.sh" "$bad"; then echo 'Expected failure' >&2; exit 1; fi
[[ ! -e "$root/current" ]]
grep -q ' down' "$MOCK_LOG"

prepare "$good"
bash "$root/incoming/$good/release.sh" "$good"
[[ $(readlink "$root/current") == "$root/incoming/$good" ]]
[[ ! -e "$root/current/image.tar.gz" ]]

if bash "$root/incoming/$bad/release.sh" "$bad"; then echo 'Expected failure' >&2; exit 1; fi
[[ $(readlink "$root/current") == "$root/incoming/$good" ]]
tail -n 1 "$MOCK_LOG" | grep -q "$good.*up"

prepare "$next"
bash "$root/incoming/$next/release.sh" "$next"
[[ $(readlink "$root/current") == "$root/incoming/$next" ]]
[[ $(readlink "$root/previous") == "$root/incoming/$good" ]]
if bash "$root/incoming/$next/release.sh" '../invalid'; then exit 1; fi
echo 'Release tests passed: first deployment, failed initial release, rollback, next release, invalid SHA.'
