#!/usr/bin/env bash
set -Eeuo pipefail

# This script is uploaded with the image, not downloaded from a mutable branch.
release=${1:?Expected Git commit SHA}
[[ "$release" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid release SHA' >&2; exit 1; }
root=/opt/art-project
incoming="$root/incoming/$release"
cd "$root"
exec 9>"$root/deploy.lock"
flock -w 180 9 || { echo 'Another deployment is running' >&2; exit 1; }

[[ -f "$incoming/image.tar.gz" && -f "$incoming/compose.production.yaml" ]]
docker load --input "$incoming/image.tar.gz"
printf 'APP_IMAGE=art-project:%s\n' "$release" > "$incoming/release.env"

compose() {
    local directory=$1
    shift
    docker compose --project-name art-project --env-file "$directory/release.env" \
        -f "$directory/compose.production.yaml" "$@"
}

compose "$incoming" config --quiet
previous=''
if [[ -L "$root/current" ]]; then previous=$(readlink -f "$root/current"); fi

if ! compose "$incoming" up -d --no-build --pull never --wait --wait-timeout 90; then
    echo 'Release failed. Attempting rollback.' >&2
    if [[ -n "$previous" ]]; then
        compose "$previous" up -d --no-build --pull never --wait --wait-timeout 90 || {
            echo 'ROLLBACK FAILED: manual intervention required.' >&2
            exit 1
        }
    else
        compose "$incoming" down || true
    fi
    exit 1
fi

ln -sfn "$incoming" "$root/current.next"
mv -Tf "$root/current.next" "$root/current"
if [[ -n "$previous" && "$previous" != "$incoming" ]]; then
    ln -sfn "$previous" "$root/previous"
fi
rm -f -- "$incoming/image.tar.gz"

# Keep only this app's current and previous images, without pruning other apps.
previous_image=''
if [[ -L "$root/previous" ]]; then
    previous_image=$(sed -n 's/^APP_IMAGE=//p' "$root/previous/release.env")
fi
while IFS= read -r image; do
    if [[ "$image" != "art-project:$release" && "$image" != "$previous_image" ]]; then
        docker image rm "$image" || true
    fi
done < <(docker image ls art-project --format '{{.Repository}}:{{.Tag}}')
echo "Deployed $release"
