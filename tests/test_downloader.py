from pathlib import Path
from subprocess import CompletedProcess
import sys
from unittest.mock import patch
import json
from urllib.error import HTTPError

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

    with patch("video2local.downloader.shutil.which", return_value=None):
        with patch.object(service, "_windows_path_entries", return_value=[]):
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

    with patch("video2local.downloader.shutil.which", return_value=None):
        with patch.object(service, "_windows_path_entries", return_value=[]):
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


def test_build_command_uses_selected_format_selector_for_bilibili_variant(tmp_path: Path) -> None:
    service = YtDlpService(binary_name="yt-dlp")
    request = DownloadRequest(
        url="https://www.bilibili.com/video/BV1xx411c7mD",
        download_dir=tmp_path,
        filename_stem="测试视频-BV1xx411c7mD-1080p",
        cookies_from_browser=None,
        format_selector="80+30280",
    )

    command = service.build_command(request)

    assert command[command.index("-f") + 1] == "80+30280"
    assert command[-1] == "https://www.bilibili.com/video/BV1xx411c7mD"


def test_build_command_finds_ffmpeg_from_refreshed_windows_path(tmp_path: Path) -> None:
    ffmpeg_path = tmp_path / "tools" / "ffmpeg.exe"
    ffmpeg_path.parent.mkdir()
    ffmpeg_path.touch()
    service = YtDlpService(binary_name="yt-dlp")
    request = DownloadRequest(
        url="https://www.bilibili.com/video/BV1xx411c7mD",
        download_dir=tmp_path,
        filename_stem="测试视频-BV1xx411c7mD-1080p",
        cookies_from_browser=None,
        format_selector="80+30280",
    )

    with patch("video2local.downloader.shutil.which", side_effect=[None, str(ffmpeg_path)]):
        with patch.object(service, "_windows_path_entries", return_value=[str(ffmpeg_path.parent)]):
            command = service.build_command(request)

    assert command[command.index("--ffmpeg-location") + 1] == str(ffmpeg_path.parent)


def test_default_command_uses_current_python_module_invocation(tmp_path: Path) -> None:
    service = YtDlpService()
    request = DownloadRequest(
        url="https://www.youtube.com/watch?v=abc123",
        download_dir=tmp_path,
        filename_stem="demo [abc123]",
        cookies_from_browser=None,
    )

    command = service.build_command(request)

    assert command[:3] == [sys.executable, "-m", "yt_dlp"]


def test_build_command_prefers_cookie_file_over_browser_source(tmp_path: Path) -> None:
    service = YtDlpService(binary_name="yt-dlp")
    cookie_file = tmp_path / "cookies.txt"
    request = DownloadRequest(
        url="https://www.douyin.com/video/735001",
        download_dir=tmp_path,
        filename_stem="晴天 [735001]",
        cookies_from_browser="chrome",
        cookies_file=cookie_file,
    )

    command = service.build_command(request)

    assert "--cookies" in command
    assert str(cookie_file) in command
    assert "--cookies-from-browser" not in command


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
        title="#海边落日",
        author_name="王五",
        page_url="https://www.douyin.com/video/735003",
        download_url="https://www.douyin.com/video/735003",
    )

    request = service.build_request(metadata=metadata, download_dir=tmp_path, cookies_from_browser="chrome")

    assert request.filename_stem == "海边落日-735003"


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


def test_download_selected_audio_video_format_requires_ffmpeg(tmp_path: Path) -> None:
    service = YtDlpService(binary_name="yt-dlp")
    metadata = VideoMetadata(
        platform="bilibili",
        source_type=SourceType.SHARE_LINK,
        video_id="BV1xx411c7mD",
        title="测试视频",
        author_name="测试UP",
        page_url="https://www.bilibili.com/video/BV1xx411c7mD",
        download_url="https://www.bilibili.com/video/BV1xx411c7mD",
    )

    with patch("video2local.downloader.shutil.which", return_value=None):
        try:
            service.download(metadata=metadata, target_dir=tmp_path, format_selector="80+30280")
        except RuntimeError as exc:
            assert "ffmpeg" in str(exc)
        else:
            raise AssertionError("expected an ffmpeg requirement error")


def test_download_selected_audio_video_format_uses_refreshed_windows_path(tmp_path: Path) -> None:
    ffmpeg_path = tmp_path / "tools" / "ffmpeg.exe"
    ffmpeg_path.parent.mkdir()
    ffmpeg_path.touch()
    service = YtDlpService(binary_name="yt-dlp")
    metadata = VideoMetadata(
        platform="bilibili",
        source_type=SourceType.SHARE_LINK,
        video_id="BV1xx411c7mD",
        title="测试视频",
        author_name="测试UP",
        page_url="https://www.bilibili.com/video/BV1xx411c7mD",
        download_url="https://www.bilibili.com/video/BV1xx411c7mD",
    )
    completed = CompletedProcess(args=["yt-dlp"], returncode=0, stdout=str(tmp_path / "output.mp4"), stderr="")

    with patch("video2local.downloader.shutil.which", side_effect=[None, str(ffmpeg_path), None, str(ffmpeg_path)]):
        with patch.object(service, "_windows_path_entries", return_value=[str(ffmpeg_path.parent)]):
            with patch("video2local.downloader.subprocess.run", return_value=completed) as run_mock:
                service.download(metadata=metadata, target_dir=tmp_path, format_selector="80+30280")

    assert "--ffmpeg-location" in run_mock.call_args.args[0]


def test_download_direct_media_url_writes_mp4_file_without_yt_dlp(tmp_path: Path) -> None:
    service = YtDlpService(binary_name="yt-dlp")
    metadata = VideoMetadata(
        platform="douyin",
        source_type=SourceType.FAVORITES,
        video_id="735004",
        title="晴天",
        author_name="赵六",
        page_url="https://www.douyin.com/video/735004",
        download_url="https://cdn.example.com/video.mp4?mime_type=video_mp4",
    )

    class FakeResponse:
        def __init__(self) -> None:
            self._chunks = [b"video-bytes", b""]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size: int = -1) -> bytes:
            return self._chunks.pop(0)

    with patch("video2local.downloader.urlopen", return_value=FakeResponse()) as open_mock:
        with patch("video2local.downloader.subprocess.run") as run_mock:
            file_ext, local_path = service.download(metadata=metadata, target_dir=tmp_path)

    assert file_ext == "mp4"
    assert Path(local_path).read_bytes() == b"video-bytes"
    assert open_mock.called is True
    run_mock.assert_not_called()


def test_download_direct_media_streams_large_response_in_chunks(tmp_path: Path) -> None:
    service = YtDlpService(binary_name="yt-dlp")
    metadata = VideoMetadata(
        platform="douyin",
        source_type=SourceType.FAVORITES,
        video_id="7659624806903675328",
        title="大文件样本",
        author_name="汪文",
        page_url="https://www.douyin.com/video/7659624806903675328",
        download_url="https://cdn.example.com/video.mp4?mime_type=video_mp4",
    )

    class FakeResponse:
        def __init__(self) -> None:
            self._chunks = [b"abc", b"def", b""]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size: int = -1) -> bytes:
            if size == -1:
                raise TimeoutError("single-shot read should not be used for large files")
            return self._chunks.pop(0)

    with patch("video2local.downloader.urlopen", return_value=FakeResponse()):
        file_ext, local_path = service.download(metadata=metadata, target_dir=tmp_path)

    assert file_ext == "mp4"
    assert Path(local_path).read_bytes() == b"abcdef"


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


def test_probe_video_info_explains_youtube_bot_verification_instead_of_json_error() -> None:
    service = YtDlpService(binary_name="yt-dlp")
    completed = CompletedProcess(
        args=["yt-dlp"],
        returncode=1,
        stdout="null\n",
        stderr="ERROR: [youtube] abc123: Sign in to confirm you’re not a bot.",
    )

    with patch("video2local.downloader.subprocess.run", return_value=completed):
        try:
            service.probe_video_info(url="https://youtu.be/abc123")
        except RuntimeError as exc:
            assert "登录确认不是机器人" in str(exc)
            assert "启动 Chrome" in str(exc)
        else:
            raise AssertionError("Expected a friendly YouTube verification error")


def test_build_command_enables_node_runtime_for_youtube(tmp_path: Path) -> None:
    service = YtDlpService(binary_name="yt-dlp")
    request = DownloadRequest(
        url="https://youtu.be/abc123",
        download_dir=tmp_path,
        filename_stem="demo-abc123",
        cookies_from_browser=None,
    )

    with patch.object(service, "_node_executable", return_value=r"C:\Program Files\nodejs\node.exe"):
        command = service.build_command(request)

    assert command[command.index("--js-runtimes") + 1] == r"node:C:\Program Files\nodejs\node.exe"
