from pathlib import Path

from video2local.browser import ChromeLaunchSpec


def test_chrome_launch_args_use_dedicated_profile_and_remote_debugging_port(tmp_path: Path) -> None:
    spec = ChromeLaunchSpec(
        executable_path=Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        user_data_dir=tmp_path / "chrome-profile",
        remote_debugging_port=9222,
    )

    args = spec.to_argv()

    assert args == [
        str(spec.executable_path),
        f"--user-data-dir={spec.user_data_dir}",
        "--remote-debugging-port=9222",
        "--new-window",
        "about:blank",
    ]
