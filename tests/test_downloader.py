from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch
import json

from video2local.domain import SourceType, VideoMetadata
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


def test_build_request_uses_metadata_title_and_id_for_target_name(tmp_path: Path) -> None:
    service = YtDlpService(binary_name="yt-dlp")
    metadata = VideoMetadata(
        platform="douyin",
        source_type=SourceType.FAVORITES,
        video_id="735003",
        title="海边落日",
        author_name="王五",
        page_url="https://www.douyin.com/video/735003",
        download_url="https://www.douyin.com/video/735003",
    )

    request = service.build_request(metadata=metadata, download_dir=tmp_path, cookies_from_browser="chrome")

    assert request.filename_stem == "海边落日 [735003]"


def test_download_returns_extension_and_output_path_from_completed_process(tmp_path: Path) -> None:
    service = YtDlpService(binary_name="yt-dlp")
    metadata = VideoMetadata(
        platform="douyin",
        source_type=SourceType.FAVORITES,
        video_id="735004",
        title="晴天",
        author_name="赵六",
        page_url="https://www.douyin.com/video/735004",
        download_url="https://www.douyin.com/video/735004",
    )
    output_path = str(tmp_path / "晴天 [735004].mp4")
    completed = CompletedProcess(args=["yt-dlp"], returncode=0, stdout=f"note\n{output_path}\n", stderr="")

    with patch("video2local.downloader.subprocess.run", return_value=completed) as run_mock:
        file_ext, local_path = service.download(metadata=metadata, target_dir=tmp_path)

    assert file_ext == "mp4"
    assert local_path == output_path
    assert run_mock.called is True


def test_probe_metadata_returns_video_metadata_from_yt_dlp_json() -> None:
    service = YtDlpService(binary_name="yt-dlp")
    payload = json.dumps(
        {
            "id": "735005",
            "title": "夜景",
            "uploader": "小明",
            "webpage_url": "https://www.douyin.com/video/735005",
        }
    )
    completed = CompletedProcess(args=["yt-dlp"], returncode=0, stdout=payload, stderr="")

    with patch("video2local.downloader.subprocess.run", return_value=completed):
        metadata = service.probe_metadata(
            url="https://www.douyin.com/video/735005",
            platform="douyin",
            source_type=SourceType.FAVORITES,
            cookies_from_browser="chrome",
        )

    assert metadata.platform == "douyin"
    assert metadata.source_type == SourceType.FAVORITES
    assert metadata.video_id == "735005"
    assert metadata.title == "夜景"
    assert metadata.author_name == "小明"
    assert metadata.page_url == "https://www.douyin.com/video/735005"
