from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChromeLaunchSpec:
    executable_path: Path
    user_data_dir: Path
    remote_debugging_port: int

    def to_argv(self) -> list[str]:
        return [
            str(self.executable_path),
            f"--user-data-dir={self.user_data_dir}",
            f"--remote-debugging-port={self.remote_debugging_port}",
            "--new-window",
            "about:blank",
        ]
