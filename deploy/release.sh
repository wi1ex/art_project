#!/usr/bin/env bash
set -Eeuo pipefail
set +x

# This script is uploaded with the image, not downloaded from a mutable branch.
release=${1:?Expected Git commit SHA}
[[ "$release" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid release SHA' >&2; exit 1; }
runtime_from_stdin=false
if [[ "${2:-}" == --runtime-config-stdin && $# == 2 ]]; then
    runtime_from_stdin=true
elif [[ $# != 1 ]]; then
    echo 'Invalid release arguments' >&2
    exit 1
fi
root=/opt/art-project
incoming="$root/incoming/$release"
cd "$root"
exec 9>"$root/deploy.lock"
flock -w 180 9 || { echo 'Another deployment is running' >&2; exit 1; }

[[ -f "$incoming/image.tar.gz" && -f "$incoming/compose.production.yaml" ]]
api_env_file=${API_ENV_FILE:-$root/config/api.env}
previous=''
if [[ -L "$root/current" ]]; then previous=$(readlink -f "$root/current"); fi
for pointer in current previous; do
    [[ ! -e "$root/$pointer" || -L "$root/$pointer" ]] || {
        echo 'Release pointers must be symlinks.' >&2
        exit 1
    }
done
previous_pointer=''
if [[ -L "$root/previous" ]]; then previous_pointer=$(readlink "$root/previous"); fi
runtime_stage=''
runtime_backup=''
runtime_installed=false
runtime_existed=false
startup_attempted=false
release_succeeded=false
pointer_change_started=false

compose() {
    local directory=$1
    shift
    docker compose --project-name art-project --env-file "$directory/release.env" \
        -f "$directory/compose.production.yaml" "$@"
}

restore_runtime() {
    if $runtime_installed; then
        if $runtime_existed; then
            mv -f -- "$runtime_backup" "$api_env_file" || return 1
            runtime_backup=''
        else
            rm -f -- "$api_env_file" || return 1
        fi
        runtime_installed=false
    fi
    export API_ENV_FILE="$api_env_file"
}

finish_release() {
    local status=$?
    trap - EXIT
    if ! $release_succeeded; then
        # The first failed release needs its new env file for Compose teardown.
        if $startup_attempted && [[ -z "$previous" ]]; then
            compose "$incoming" down --remove-orphans || {
                echo 'FIRST RELEASE CLEANUP FAILED: manual intervention required.' >&2
                status=1
            }
        fi
        # Restore the old token/origins before starting the old API image.
        if ! restore_runtime; then
            echo 'RUNTIME CONFIG RESTORE FAILED: manual intervention required.' >&2
            # Keep the backup available for manual recovery.
            runtime_backup=''
            status=1
        elif $startup_attempted && [[ -n "$previous" ]]; then
            echo 'Release failed. Attempting rollback.' >&2
            compose "$previous" up -d --no-build --pull never --remove-orphans --wait --wait-timeout 90 || {
                echo 'ROLLBACK FAILED: manual intervention required.' >&2
                status=1
            }
        fi
        if $pointer_change_started; then
            if [[ -n "$previous" ]]; then
                ln -sfn "$previous" "$root/current.next" && mv -Tf "$root/current.next" "$root/current" || status=1
            else
                rm -f -- "$root/current" || status=1
            fi
            if [[ -n "$previous_pointer" ]]; then
                ln -sfn "$previous_pointer" "$root/previous.next" && mv -Tf "$root/previous.next" "$root/previous" || status=1
            else
                rm -f -- "$root/previous" || status=1
            fi
        fi
    fi
    [[ -z "$runtime_stage" ]] || rm -f -- "$runtime_stage"
    [[ -z "$runtime_backup" ]] || rm -f -- "$runtime_backup"
    rm -f -- "$root/current.next" "$root/previous.next"
    exit "$status"
}
trap finish_release EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if $runtime_from_stdin; then
    # Stdin is encrypted by verified SSH. Secrets stay outside release dirs.
    [[ ! -L "$api_env_file" ]] || { echo 'Runtime configuration must not be a symlink.' >&2; exit 1; }
    runtime_directory=$(dirname "$api_env_file")
    [[ ! -L "$runtime_directory" ]] || { echo 'Runtime configuration directory must not be a symlink.' >&2; exit 1; }
    (umask 077; mkdir -p -- "$runtime_directory")
    runtime_stage=$(mktemp "$runtime_directory/.api.env.next.XXXXXX")
    chmod 600 "$runtime_stage"
    cat > "$runtime_stage"
    runtime_size=$(wc -c < "$runtime_stage")
    if (( runtime_size == 0 || runtime_size > 16384 )); then
        echo 'Invalid runtime configuration size.' >&2
        exit 1
    fi
    # Only the five generated runtime keys are accepted. The file is never sourced.
    if [[ $(wc -l < "$runtime_stage") != 5 ]] ||
       [[ $(cut -d= -f1 "$runtime_stage" | sort | uniq | wc -l) != 5 ]] ||
       grep -qvE "^(LEADS_ENABLED|TELEGRAM_BOT_TOKEN|TELEGRAM_ADMIN_PASSWORD|TELEGRAM_RETRY_SECONDS|LEADS_ALLOWED_ORIGINS)='[^']*'$" "$runtime_stage"; then
        echo 'Invalid runtime configuration keys or encoding.' >&2
        exit 1
    fi
    export API_ENV_FILE="$runtime_stage"
else
    [[ -f "$api_env_file" && -r "$api_env_file" ]] || {
        echo 'Provide runtime configuration on stdin or an existing readable api.env.' >&2
        exit 1
    }
    export API_ENV_FILE="$api_env_file"
fi

docker load --input "$incoming/image.tar.gz"
printf 'APP_IMAGE=art-project:%s\nAPI_IMAGE=art-project-api:%s\n' "$release" "$release" > "$incoming/release.env"
if ! compose "$incoming" config --quiet 2>/dev/null; then
    echo 'Invalid Compose or runtime configuration.' >&2
    exit 1
fi

if $runtime_from_stdin; then
    if [[ -e "$api_env_file" ]]; then
        [[ -f "$api_env_file" && -r "$api_env_file" ]] || { echo 'Existing runtime configuration is not readable.' >&2; exit 1; }
        runtime_backup=$(mktemp "$runtime_directory/.api.env.previous.XXXXXX")
        cp -- "$api_env_file" "$runtime_backup"
        chmod 600 "$runtime_backup"
        runtime_existed=true
    fi
    runtime_installed=true
    mv -f -- "$runtime_stage" "$api_env_file"
    runtime_stage=''
    export API_ENV_FILE="$api_env_file"
fi

startup_attempted=true
compose "$incoming" up -d --no-build --pull never --remove-orphans --wait --wait-timeout 90

ln -sfn "$incoming" "$root/current.next"
if [[ -n "$previous" && "$previous" != "$incoming" ]]; then
    ln -sfn "$previous" "$root/previous.next"
    pointer_change_started=true
    mv -Tf "$root/previous.next" "$root/previous"
fi
pointer_change_started=true
mv -Tf "$root/current.next" "$root/current"
release_succeeded=true
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
