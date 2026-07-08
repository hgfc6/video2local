from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DownloadRequest:
    url: str
    download_dir: Path
    filename_stem: str
    cookies_from_browser: str | None


class YtDlpService:
    def __init__(self, binary_name: str = "yt-dlp") -> None:
        self.binary_name = binary_name

    def build_command(self, request: DownloadRequest) -> list[str]:
        escaped_stem = request.filename_stem.replace("%", "%%")
        output_template = str(request.download_dir / f"{escaped_stem}.%(ext)s")
        command = [
            self.binary_name,
            "--ignore-config",
            "-f",
            "bv*+ba/b",
            "--merge-output-format",
            "mp4",
            "--print",
            "after_move:filepath",
            "-o",
            output_template,
        ]
        if request.cookies_from_browser:
            command.extend(["--cookies-from-browser", request.cookies_from_browser])
        command.append(request.url)
        return command

    def infer_extension(self, output_path: str) -> str:
        return Path(output_path).suffix.lstrip(".")
