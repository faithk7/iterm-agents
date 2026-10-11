#!/bin/bash
# Install iterm-agents on macOS without Homebrew or a preinstalled Python.
set -euo pipefail

install_dir="$HOME/.local/share/iterm-agents"
source_dir=""
autolaunch=true
force_autolaunch=false
work_dir=""

usage() {
    cat <<'EOF'
Usage: bash install.sh [options]

Install iterm-agents and its iTerm2 AutoLaunch wrapper on macOS.
Downloads the main branch unless --source is supplied. Requires working Git.

Options:
  --source DIR          Install from a local checkout instead of downloading
  --install-dir DIR     Use a dedicated install directory (default: ~/.local/share/iterm-agents)
  --no-autolaunch       Install the monitor without automatic startup
  --force-autolaunch    Replace an existing AutoLaunch wrapper
  -h, --help            Show this help
EOF
}

die() {
    printf 'iterm-agents installer: %s\n' "$*" >&2
    exit 1
}

cleanup() {
    if [[ -n "$work_dir" ]]; then
        rm -rf -- "$work_dir"
    fi
}

main() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --source|--install-dir)
                [[ $# -ge 2 && -n "$2" ]] || die "$1 requires a directory."
                if [[ "$1" == --source ]]; then
                    source_dir="$2"
                else
                    install_dir="$2"
                fi
                shift 2
                ;;
            --no-autolaunch) autolaunch=false; shift ;;
            --force-autolaunch) force_autolaunch=true; shift ;;
            -h|--help) usage; return ;;
            *) die "Unknown option: $1. Use --help for options." ;;
        esac
    done

    [[ "$(uname -s)" == Darwin ]] || die "This installer supports macOS only."
    if [[ "$autolaunch" == false && "$force_autolaunch" == true ]]; then
        die "--force-autolaunch cannot be combined with --no-autolaunch."
    fi
    for dependency in curl tar git; do
        command -v "$dependency" >/dev/null 2>&1 || die "Required command not found: $dependency."
    done
    git --version >/dev/null 2>&1 || die \
        "Git is not ready. Run xcode-select --install, finish Apple's installation, then retry."

    if [[ -n "$source_dir" ]]; then
        [[ -d "$source_dir" ]] || die "Source directory does not exist: $source_dir."
        source_dir="$(cd "$source_dir" && pwd -P)"
        [[ -f "$source_dir/pyproject.toml" && -f "$source_dir/uv.lock" && \
           -f "$source_dir/src/iterm_agents/__main__.py" ]] || die \
            "Source must be an iterm-agents checkout with pyproject.toml and uv.lock."
    fi

    [[ "$install_dir" == /* ]] || install_dir="$PWD/$install_dir"
    if [[ -e "$install_dir" && ! -f "$install_dir/.iterm-agents-install" ]]; then
        die "Refusing to use an existing unmanaged directory: $install_dir. Choose another --install-dir."
    fi
    mkdir -p "$install_dir"
    install_dir="$(cd "$install_dir" && pwd -P)"
    touch "$install_dir/.iterm-agents-install"

    work_dir="$(mktemp -d "${TMPDIR:-/tmp}/iterm-agents-install.XXXXXX")"
    trap cleanup EXIT
    trap 'printf "iterm-agents installer: Installation failed; check the error above and rerun.\n" >&2' ERR

    local uv_bin
    if command -v uv >/dev/null 2>&1; then
        uv_bin="$(command -v uv)"
    elif [[ -x "$install_dir/tools/uv" ]]; then
        uv_bin="$install_dir/tools/uv"
    else
        printf 'Installing uv...\n'
        curl --fail --show-error --location --retry 3 \
            https://astral.sh/uv/install.sh --output "$work_dir/uv-install.sh"
        UV_UNMANAGED_INSTALL="$install_dir/tools" sh "$work_dir/uv-install.sh"
        uv_bin="$install_dir/tools/uv"
    fi

    if [[ -z "$source_dir" ]]; then
        printf 'Downloading iterm-agents...\n'
        curl --fail --show-error --location --retry 3 \
            https://codeload.github.com/faithk7/iterm-agents/tar.gz/refs/heads/main \
            --output "$work_dir/source.tar.gz"
        mkdir "$work_dir/source"
        tar -xzf "$work_dir/source.tar.gz" --strip-components=1 -C "$work_dir/source"
        source_dir="$work_dir/source"
    fi

    printf 'Installing the monitor and its dependencies...\n'
    UV_PROJECT_ENVIRONMENT="$install_dir/venv" "$uv_bin" sync \
        --project "$source_dir" --python 3.12 --frozen --no-dev --no-editable \
        --reinstall-package iterm-agents

    local binary="$install_dir/venv/bin/iterm-agents"
    "$binary" --version
    if [[ "$autolaunch" == true ]]; then
        if [[ "$force_autolaunch" == true ]]; then
            "$binary" --install-autolaunch --force
        else
            "$binary" --install-autolaunch
        fi
    fi

    printf '\nInstalled! Finish these settings in iTerm2:\n'
    printf '  1. Open iTerm2 with Cmd+Space, type iTerm, then press Enter.\n'
    printf '  2. Press Cmd+,; enable General > Magic > Enable Python API.\n'
    printf '  3. Choose iTerm2 > Install Shell Integration, then open a new tab.\n'
    if [[ "$autolaunch" == true ]]; then
        printf '  4. Quit and reopen iTerm2 to start the Agents panel automatically.\n'
    else
        printf '  4. Start the monitor with the command below.\n'
    fi
    printf '\nManual start: %q\n' "$binary"
    printf 'Keep %s in place. Rerun the installer to update.\n' "$install_dir"
}

main "$@"
