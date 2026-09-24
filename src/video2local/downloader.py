from dataclasses import dataclass
from mimetypes import guess_extension
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from threading import Event, Lock
from urllib.request import Request, urlopen

from video2local.archive import ArchiveManager
from video2local.domain import SourceType, VideoMetadata


PROBE_TIMEOUT_SECONDS = 90
DOWNLOAD_TIMEOUT_SECONDS = 60 * 60
DIRECT_DOWNLOAD_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class DownloadRequest:
    url: str
    download_dir: Path
    filename_stem: str
    cookies_from_browser: str | None
    cookies_file: Path | None = None
    format_selector: str | None = None


class YtDlpService:
    def __init__(self, binary_name: str | list[str] | None = None) -> None:
        self.binary_name = binary_name
        self.archive_manager = ArchiveManager(download_root=Path("."))
        self._stop_event = Event()
        self._process_lock = Lock()
        self._active_process: subprocess.Popen[str] | None = None

    def clear_stop_request(self) -> None:
        self._stop_event.clear()

    def request_stop(self) -> None:
        self._stop_event.set()
        with self._process_lock:
            process = self._active_process
            if process is not None and process.poll() is None:
                process.terminate()

    @staticmethod
    def _windows_path_entries() -> list[str]:
        if os.name != "nt":
            return []
        try:
            import winreg
        except ImportError:
            return []

        entries: list[str] = []
        registry_paths = (
            (winreg.HKEY_CURRENT_USER, r"Environment"),
            (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        )
        for root, key_path in registry_paths:
            try:
                with winreg.OpenKey(root, key_path) as key:
                    value, _ = winreg.QueryValueEx(key, "Path")
            except OSError:
                continue
            if isinstance(value, str) and value:
                entries.append(os.path.expandvars(value))
        return entries

    def _ffmpeg_directory(self) -> Path | None:
        discovered = shutil.which("ffmpeg")
        if discovered is None:
            refreshed_path = os.pathsep.join([os.environ.get("PATH", ""), *self._windows_path_entries()])
            discovered = shutil.which("ffmpeg", path=refreshed_path)
        return Path(discovered).parent if discovered else None

    def command_prefix(self) -> list[str]:
        if self.binary_name is None:
            return [sys.executable, "-m", "yt_dlp"]
        if isinstance(self.binary_name, str):
            return [self.binary_name]
        return list(self.binary_name)

    def _uses_embedded_ytdlp(self) -> bool:
        """A frozen app must not relaunch its own EXE as ``python -m yt_dlp``."""
        return self.binary_name is None and bool(getattr(sys, "frozen", False))

    @staticmethod
    def _background_process_kwargs() -> dict[str, int]:
        """Keep CLI helpers invisible when the desktop app is running on Windows."""
        if os.name != "nt":
            return {}
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}

    def build_request(
        self,
        metadata: VideoMetadata,
        download_dir: Path,
        cookies_from_browser: str | None,
        cookies_file: Path | None = None,
        filename_stem: str | None = None,
        format_selector: str | None = None,
    ) -> DownloadRequest:
        return DownloadRequest(
            url=metadata.download_url,
            download_dir=download_dir,
            filename_stem=filename_stem
            or self.archive_manager.build_filename_stem(video_id=metadata.video_id, title=metadata.title),
            cookies_from_browser=cookies_from_browser,
            cookies_file=cookies_file,
            format_selector=format_selector,
        )

    def build_command(self, request: DownloadRequest) -> list[str]:
        escaped_stem = request.filename_stem.replace("%", "%%")
        output_template = str(request.download_dir / f"{escaped_stem}.%(ext)s")
        command = [
            *self.command_prefix(),
            "--ignore-config",
            "-f",
            request.format_selector or "bv*+ba/b",
            "--merge-output-format",
            "mp4",
            "--print",
            "after_move:filepath",
            "-o",
            output_template,
        ]
        ffmpeg_directory = self._ffmpeg_directory()
        if ffmpeg_directory is not None:
            command.extend(["--ffmpeg-location", str(ffmpeg_directory)])
        if request.cookies_file is not None:
            command.extend(["--cookies", str(request.cookies_file)])
        elif request.cookies_from_browser:
            command.extend(["--cookies-from-browser", request.cookies_from_browser])
        command.append(request.url)
        return command

    def infer_extension(self, output_path: str) -> str:
        return Path(output_path).suffix.lstrip(".")

    def probe_metadata(
        self,
        *,
        url: str,
        platform: str,
        source_type: SourceType,
        cookies_from_browser: str | None,
        cookies_file: Path | None = None,
    ) -> VideoMetadata:
        payload = self.probe_video_info(
            url=url,
            cookies_from_browser=cookies_from_browser,
            cookies_file=cookies_file,
        )
        video_id = str(payload["id"])
        title = payload.get("title") or video_id
        author_name = payload.get("uploader") or payload.get("channel") or payload.get("creator") or "unknown"
        page_url = payload.get("webpage_url") or url
        return VideoMetadata(
            platform=platform,
            source_type=source_type,
            video_id=video_id,
            title=title,
            author_name=author_name,
            page_url=page_url,
            download_url=page_url,
        )

    def probe_video_info(
        self,
        *,
        url: str,
        cookies_from_browser: str | None = None,
        cookies_file: Path | None = None,
    ) -> dict:
        if self._uses_embedded_ytdlp():
            return self._probe_with_embedded_ytdlp(
                url=url,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies_file,
            )
        command = [
            *self.command_prefix(),
            "--ignore-config",
            "--skip-download",
            "--dump-single-json",
        ]
        if cookies_file is not None:
            command.extend(["--cookies", str(cookies_file)])
        elif cookies_from_browser:
            command.extend(["--cookies-from-browser", cookies_from_browser])
        command.append(url)
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=PROBE_TIMEOUT_SECONDS,
                **self._background_process_kwargs(),
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("视频信息解析超时，请检查网络后重试") from exc
        if completed.returncode != 0:
            raise RuntimeError(self._probe_error_message(url, completed.stderr, completed.stdout))
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(self._probe_error_message(url, completed.stderr, completed.stdout)) from exc
        if not isinstance(payload, dict):
            raise RuntimeError(self._probe_error_message(url, completed.stderr, completed.stdout))
        return payload

    @staticmethod
    def _embedded_ytdlp_options(
        *,
        cookies_from_browser: str | None,
        cookies_file: Path | None,
    ) -> dict:
        options: dict = {
            "ignoreconfig": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
        }
        if cookies_file is not None:
            options["cookiefile"] = str(cookies_file)
        elif cookies_from_browser:
            options["cookiesfrombrowser"] = (cookies_from_browser,)
        return options

    def _probe_with_embedded_ytdlp(
        self,
        *,
        url: str,
        cookies_from_browser: str | None,
        cookies_file: Path | None,
    ) -> dict:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError

        options = self._embedded_ytdlp_options(
            cookies_from_browser=cookies_from_browser,
            cookies_file=cookies_file,
        )
        options["skip_download"] = True
        try:
            with YoutubeDL(options) as ydl:
                payload = ydl.extract_info(url, download=False)
        except DownloadError as exc:
            raise RuntimeError(self._probe_error_message(url, str(exc), "")) from exc
        if not isinstance(payload, dict):
            raise RuntimeError(self._probe_error_message(url, "", ""))
        return payload

    def _probe_error_message(self, url: str, stderr: str, stdout: str) -> str:
        detail = (stderr or stdout).strip()
        lowered = detail.lower()
        compact_detail = " ".join(detail.split())
        if compact_detail:
            return f"视频信息解析失败: {compact_detail[-500:]}"
        return f"视频信息解析失败，yt-dlp 未返回可读结果: {url}"

    def should_download_direct(self, metadata: VideoMetadata) -> bool:
        if metadata.media_type in {"image", "live_photo"}:
            return True
        download_url = metadata.download_url
        return any(
            marker in download_url
            for marker in (
                "mime_type=video_mp4",
                ".zjcdn.com/",
                "douyinvod.com",
                "/aweme/v1/play/?video_id=",
            )
        )

    def download(
        self,
        metadata: VideoMetadata,
        target_dir: Path,
        cookies_file: Path | None = None,
        filename_stem: str | None = None,
        format_selector: str | None = None,
    ) -> tuple[str, str]:
        format_selector = format_selector or metadata.format_selector
        if self.should_download_direct(metadata):
            return self._download_direct_media(metadata, target_dir, filename_stem=filename_stem)
        if format_selector and "+" in format_selector and self._ffmpeg_directory() is None:
            raise RuntimeError("下载所选音视频组合需要 ffmpeg，请安装 ffmpeg 并将其加入 PATH 后重试")
        request = self.build_request(
            metadata=metadata,
            download_dir=target_dir,
            cookies_from_browser="chrome",
            cookies_file=cookies_file,
            filename_stem=filename_stem,
            format_selector=format_selector,
        )
        if self._uses_embedded_ytdlp():
            return self._download_with_embedded_ytdlp(request)
        command = self.build_command(request)
        completed = self._run_download_command(command)
        output_path = completed.stdout.strip().splitlines()[-1]
        return self.infer_extension(output_path), output_path

    def _download_with_embedded_ytdlp(self, request: DownloadRequest) -> tuple[str, str]:
        """Run the bundled yt-dlp library without spawning another Video2Local EXE."""
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError

        request.download_dir.mkdir(parents=True, exist_ok=True)
        output_template = str(request.download_dir / f"{request.filename_stem}.%(ext)s")
        options = self._embedded_ytdlp_options(
            cookies_from_browser=request.cookies_from_browser,
            cookies_file=request.cookies_file,
        )
        options.update(
            {
                "format": request.format_selector or "bv*+ba/b",
                "merge_output_format": "mp4",
                "outtmpl": output_template,
            }
        )
        ffmpeg_directory = self._ffmpeg_directory()
        if ffmpeg_directory is not None:
            options["ffmpeg_location"] = str(ffmpeg_directory)
        existing_paths = set(request.download_dir.glob(f"{request.filename_stem}.*"))
        try:
            with YoutubeDL(options) as ydl:
                ydl.extract_info(request.url, download=True)
        except DownloadError as exc:
            raise RuntimeError(f"视频下载失败: {exc}") from exc
        candidates = [
            path
            for path in request.download_dir.glob(f"{request.filename_stem}.*")
            if path not in existing_paths and path.is_file() and path.suffix not in {".part", ".ytdl"}
        ]
        if not candidates:
            raise RuntimeError("yt-dlp 未返回下载文件路径")
        output_path = max(
            candidates,
            key=lambda path: (path.suffix.lower() == ".mp4", path.stat().st_mtime_ns),
        )
        return self.infer_extension(str(output_path)), str(output_path)

    def _run_download_command(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        with self._process_lock:
            self._active_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                **self._background_process_kwargs(),
            )
            process = self._active_process
        try:
            stdout, stderr = process.communicate(timeout=DOWNLOAD_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            raise RuntimeError("视频下载超时，请检查网络后重试") from exc
        finally:
            with self._process_lock:
                self._active_process = None
        if self._stop_event.is_set():
            raise RuntimeError("下载已停止")
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command, output=stdout, stderr=stderr)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)

    def _download_direct_media(
        self,
        metadata: VideoMetadata,
        target_dir: Path,
        *,
        filename_stem: str | None = None,
    ) -> tuple[str, str]:
        request = self.build_request(
            metadata=metadata,
            download_dir=target_dir,
            cookies_from_browser=None,
            filename_stem=filename_stem,
        )
        http_request = Request(
            metadata.download_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/138.0.0.0 Safari/537.36"
                ),
                "Referer": metadata.page_url,
            },
        )
        output_path: Path | None = None
        try:
            with urlopen(http_request, timeout=DIRECT_DOWNLOAD_TIMEOUT_SECONDS) as response:
                extension = self._direct_media_extension(metadata, response)
                output_path = request.download_dir / f"{request.filename_stem}.{extension}"
                with output_path.open("wb") as output_file:
                    while True:
                        if self._stop_event.is_set():
                            raise RuntimeError("下载已停止")
                        chunk = response.read(1024 * 64)
                        if not chunk:
                            break
                        output_file.write(chunk)
        except Exception:
            if output_path is not None:
                output_path.unlink(missing_ok=True)
            raise
        assert output_path is not None
        return output_path.suffix.lstrip("."), str(output_path)

    @staticmethod
    def _direct_media_extension(metadata: VideoMetadata, response) -> str:
        if metadata.media_type not in {"image", "live_photo"}:
            return "mp4"
        headers = getattr(response, "headers", None)
        content_type = headers.get("Content-Type", "") if headers is not None else ""
        mime_type = content_type.split(";", maxsplit=1)[0].strip().lower()
        extension = guess_extension(mime_type)
        if extension:
            return extension.lstrip(".").replace("jpe", "jpg")
        return "jpg" if metadata.media_type == "image" else "mp4"
