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
api_env_file=${API_ENV_FILE:-$root/config/api.env}
[[ -f "$api_env_file" && -r "$api_env_file" ]] || {
    echo 'Create the server runtime configuration at /opt/art-project/config/api.env before deployment.' >&2
    exit 1
}
export API_ENV_FILE="$api_env_file"
geoip_directory=${GEOIP_DIRECTORY:-$root/config/geoip}
if [[ ! -e "$geoip_directory" && ! -L "$geoip_directory" ]]; then
    if ! mkdir -p -- "$geoip_directory" || ! chmod 755 -- "$geoip_directory"; then
        printf 'Cannot create the GeoIP directory: %s. Prepare it with read/search access for deploy.\n' "$geoip_directory" >&2
        exit 1
    fi
fi
[[ -d "$geoip_directory" && -r "$geoip_directory" && -x "$geoip_directory" ]] || {
    printf 'GeoIP directory is unavailable: %s. Grant deploy read and search access.\n' "$geoip_directory" >&2
    exit 1
}
export GEOIP_DIRECTORY="$geoip_directory"
docker load --input "$incoming/image.tar.gz"
printf 'APP_IMAGE=art-project:%s\nAPI_IMAGE=art-project-api:%s\n' "$release" "$release" > "$incoming/release.env"

compose() {
    local directory=$1
    shift
    docker compose --project-name art-project --env-file "$directory/release.env" \
        -f "$directory/compose.production.yaml" "$@"
}

compose "$incoming" config --quiet
previous=''
if [[ -L "$root/current" ]]; then previous=$(readlink -f "$root/current"); fi

if ! compose "$incoming" up -d --no-build --pull never --remove-orphans --wait --wait-timeout 90; then
    echo 'Release failed. Attempting rollback.' >&2
    if [[ -n "$previous" ]]; then
        compose "$previous" up -d --no-build --pull never --remove-orphans --wait --wait-timeout 90 || {
            echo 'ROLLBACK FAILED: manual intervention required.' >&2
            exit 1
        }
    else
        compose "$incoming" down --remove-orphans || true
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
previous_api_image=''
if [[ -L "$root/previous" ]]; then
    previous_image=$(sed -n 's/^APP_IMAGE=//p' "$root/previous/release.env")
    previous_api_image=$(sed -n 's/^API_IMAGE=//p' "$root/previous/release.env")
fi
prune_release_images() {
    local repository=$1 current_image=$2 retained_image=$3 image
    while IFS= read -r image; do
        if [[ "$image" == "$repository:"* && "$image" != "$current_image" && "$image" != "$retained_image" ]]; then
            docker image rm "$image" || true
        fi
    done < <(docker image ls "$repository" --format '{{.Repository}}:{{.Tag}}')
}
prune_release_images art-project "art-project:$release" "$previous_image"
prune_release_images art-project-api "art-project-api:$release" "$previous_api_image"
echo "Deployed $release"
