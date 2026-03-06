import os
from functools import lru_cache
from pathlib import Path


def _looks_like_repo_root(p: Path) -> bool:
    return (p / "app").is_dir() and (p / "main.py").is_file() and (p / "requirements.txt").is_file()


def _find_repo_root(start_dir: Path) -> Path:
    for p in (start_dir, *start_dir.parents):
        if _looks_like_repo_root(p):
            return p
    return start_dir


@lru_cache(maxsize=1)
def project_root() -> Path:
    env_root = (os.getenv("CHRONOFOLD_PROJECT_ROOT") or os.getenv("PROJECT_ROOT") or "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()
    return _find_repo_root(Path(__file__).resolve().parent).resolve()


def path_in_root(*parts: str) -> Path:
    return project_root().joinpath(*parts)


def output_dir() -> Path:
    raw = (os.getenv("CHRONOFOLD_OUTPUT_DIR") or "notion_output").strip()
    p = Path(raw).expanduser()
    return p.resolve() if p.is_absolute() else path_in_root(raw)


def reports_dir() -> Path:
    raw = (os.getenv("CHRONOFOLD_REPORTS_DIR") or "_reports").strip()
    p = Path(raw).expanduser()
    return p.resolve() if p.is_absolute() else path_in_root(raw)


def config_dir() -> Path:
    raw = (os.getenv("CHRONOFOLD_CONFIG_DIR") or "config").strip()
    p = Path(raw).expanduser()
    return p.resolve() if p.is_absolute() else path_in_root(raw)

