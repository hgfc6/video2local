from pathlib import Path

from video2local.downloader import DownloadRequest, YtDlpService


def test_build_command_requests_best_quality_and_output_template(tmp_path: Path) -> None:
    service = YtDlpService(binary_name="yt-dlp")
    request = DownloadRequest(
        url="https://www.douyin.com/video/735001",
        download_dir=tmp_path,
        filename_stem="晚霞%散步 [735001]",
        cookies_from_browser="chrome",
    )

    command = service.build_command(request)

    assert command == [
        "yt-dlp",
        "--ignore-config",
        "-f",
        "bv*+ba/b",
        "--merge-output-format",
        "mp4",
        "--print",
        "after_move:filepath",
        "-o",
        str(tmp_path / "晚霞%%散步 [735001].%(ext)s"),
        "--cookies-from-browser",
        "chrome",
        "https://www.douyin.com/video/735001",
    ]


def test_build_command_omits_browser_cookies_when_not_requested(tmp_path: Path) -> None:
    service = YtDlpService(binary_name="yt-dlp")
    request = DownloadRequest(
        url="https://www.youtube.com/watch?v=abc123",
        download_dir=tmp_path,
        filename_stem="demo [abc123]",
        cookies_from_browser=None,
    )

    command = service.build_command(request)

    assert command == [
        "yt-dlp",
        "--ignore-config",
        "-f",
        "bv*+ba/b",
        "--merge-output-format",
        "mp4",
        "--print",
        "after_move:filepath",
        "-o",
        str(tmp_path / "demo [abc123].%(ext)s"),
        "https://www.youtube.com/watch?v=abc123",
    ]


def test_infer_extension_returns_last_suffix_without_dot() -> None:
    service = YtDlpService(binary_name="yt-dlp")

    assert service.infer_extension("D:/downloads/晚霞散步 [735001].mp4") == "mp4"
    assert service.infer_extension("D:/downloads/archive.tar.gz") == "gz"
    assert service.infer_extension("D:/downloads/no_extension") == ""
    assert service.infer_extension("D:/downloads/.hiddenfile") == ""
