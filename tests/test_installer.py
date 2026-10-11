from __future__ import annotations

import os
import subprocess
import tarfile
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[1] / "install.sh"


@pytest.fixture
def installer_environment(tmp_path: Path) -> dict[str, str]:
    """Run the installer offline without touching the user's install or AutoLaunch."""
    commands = tmp_path / "commands"
    commands.mkdir()
    source = tmp_path / "source with 'quotes'"
    (source / "src/iterm_agents").mkdir(parents=True)
    for name in ("pyproject.toml", "uv.lock", "src/iterm_agents/__main__.py"):
        (source / name).touch()
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as package:
        package.add(source, arcname="iterm-agents-main")

    scripts = {
        "uname": 'printf "%s\\n" "${ITERM_TEST_OS:-Darwin}"',
        "git": 'exit "${ITERM_TEST_GIT_EXIT:-0}"',
        "uv": """
printf 'uv\\n%s\\n' "$@" >> "$ITERM_TEST_LOG"
mkdir -p "$UV_PROJECT_ENVIRONMENT/bin"
cat > "$UV_PROJECT_ENVIRONMENT/bin/iterm-agents" <<'BINARY'
#!/bin/bash
printf 'binary\\n%s\\n' "$@" >> "$ITERM_TEST_LOG"
if [[ "$*" == *--install-autolaunch* ]]; then
    exit "${ITERM_TEST_WRAPPER_EXIT:-0}"
fi
BINARY
chmod +x "$UV_PROJECT_ENVIRONMENT/bin/iterm-agents"
""",
        "curl": """
printf 'curl\\n%s\\n' "$@" >> "$ITERM_TEST_LOG"
[[ "${ITERM_TEST_CURL_FAIL:-0}" == 0 ]] || exit 22
output=""
bootstrap=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --output) output="$2"; shift 2 ;;
        https://astral.sh/uv/install.sh) bootstrap=true; shift ;;
        *) shift ;;
    esac
done
if [[ "$bootstrap" == true ]]; then
    cat > "$output" <<'BOOTSTRAP'
mkdir -p "$UV_UNMANAGED_INSTALL"
cp "$ITERM_TEST_UV_TEMPLATE" "$UV_UNMANAGED_INSTALL/uv"
chmod +x "$UV_UNMANAGED_INSTALL/uv"
BOOTSTRAP
else
    cp "$ITERM_TEST_ARCHIVE" "$output"
fi
""",
    }
    for name, body in scripts.items():
        path = commands / name
        path.write_text("#!/bin/bash\nset -eu\n" + body + "\n")
        path.chmod(0o755)
    uv_template = tmp_path / "uv-template"
    uv_template.write_text((commands / "uv").read_text())

    return {
        **os.environ,
        "PATH": f"{commands}:/usr/bin:/bin",
        "ITERM_TEST_SOURCE": str(source),
        "ITERM_TEST_INSTALL": str(tmp_path / "install with 'quotes'"),
        "ITERM_TEST_LOG": str(tmp_path / "commands.log"),
        "ITERM_TEST_ARCHIVE": str(archive),
        "ITERM_TEST_UV_TEMPLATE": str(uv_template),
    }


def run_installer(environment: dict[str, str], *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(INSTALLER), "--install-dir", environment["ITERM_TEST_INSTALL"], *arguments],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )


def command_log(environment: dict[str, str]) -> str:
    return Path(environment["ITERM_TEST_LOG"]).read_text()


def test_local_install_is_repeatable_without_autolaunch(
    installer_environment: dict[str, str],
) -> None:
    for _ in range(2):
        result = run_installer(
            installer_environment,
            "--source",
            installer_environment["ITERM_TEST_SOURCE"],
            "--no-autolaunch",
        )
        assert result.returncode == 0, result.stderr
        assert "Installed!" in result.stdout
    log = command_log(installer_environment)
    assert "--no-editable\n" in log
    assert "--frozen\n" in log
    assert "--no-dev\n" in log
    assert "--install-autolaunch" not in log
    assert "curl\n" not in log


def test_download_install_bootstraps_uv_and_installs_autolaunch(
    installer_environment: dict[str, str],
) -> None:
    commands = Path(installer_environment["PATH"].split(":")[0])
    (commands / "uv").unlink()
    result = run_installer(installer_environment)
    assert result.returncode == 0, result.stderr
    log = command_log(installer_environment)
    assert "https://astral.sh/uv/install.sh\n" in log
    assert "https://codeload.github.com/faithk7/iterm-agents/tar.gz/refs/heads/main\n" in log
    assert "--install-autolaunch\n" in log
    assert "--force\n" not in log
    assert (Path(installer_environment["ITERM_TEST_INSTALL"]) / "tools/uv").is_file()


@pytest.mark.parametrize("force", [False, True])
def test_wrapper_conflicts_fail_without_implicit_overwrite(
    installer_environment: dict[str, str],
    force: bool,
) -> None:
    installer_environment["ITERM_TEST_WRAPPER_EXIT"] = "9"
    result = run_installer(installer_environment, *(["--force-autolaunch"] if force else []))
    assert result.returncode == 9
    assert "Installed!" not in result.stdout
    assert ("--force\n" in command_log(installer_environment)) == force


def test_failed_download_does_not_run_installation(
    installer_environment: dict[str, str],
) -> None:
    installer_environment["ITERM_TEST_CURL_FAIL"] = "1"
    result = run_installer(installer_environment)
    assert result.returncode == 22
    assert "uv\n" not in command_log(installer_environment)
    assert "Installed!" not in result.stdout


@pytest.mark.parametrize(
    ("setting", "value", "message"),
    [("ITERM_TEST_OS", "Linux", "macOS only"), ("ITERM_TEST_GIT_EXIT", "1", "Git is not ready")],
)
def test_failed_prerequisites_do_not_create_install_directory(
    installer_environment: dict[str, str],
    setting: str,
    value: str,
    message: str,
) -> None:
    installer_environment[setting] = value
    result = run_installer(installer_environment)
    assert result.returncode != 0
    assert message in result.stderr
    assert not Path(installer_environment["ITERM_TEST_INSTALL"]).exists()


def test_unmanaged_install_directory_is_preserved(installer_environment: dict[str, str]) -> None:
    install_dir = Path(installer_environment["ITERM_TEST_INSTALL"])
    install_dir.mkdir()
    important_file = install_dir / "keep.txt"
    important_file.write_text("keep me")
    result = run_installer(installer_environment)
    assert result.returncode != 0
    assert "unmanaged directory" in result.stderr
    assert important_file.read_text() == "keep me"
