from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

PATCH_TARGET = Path("src/features/retro-office/objects/agents.tsx")
PATCHER = Path("scripts/apply-trading-speech-ux.mjs")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_overlay_files(overlay_root: Path) -> list[Path]:
    return sorted(path for path in overlay_root.rglob("*") if path.is_file())


def compare_overlay(repo_root: Path, runtime_root: Path) -> list[str]:
    overlay_root = repo_root / "deploy" / "hermes3d" / "overlay"
    if not overlay_root.is_dir():
        raise FileNotFoundError(f"Hermes3D overlay not found: {overlay_root}")
    if not runtime_root.is_dir():
        raise FileNotFoundError(f"Hermes3D runtime not found: {runtime_root}")

    drift: list[str] = []
    for source in iter_overlay_files(overlay_root):
        relative = source.relative_to(overlay_root)
        target = runtime_root / relative
        if not target.is_file():
            drift.append(f"missing:{relative.as_posix()}")
            continue
        if sha256_file(source) != sha256_file(target):
            drift.append(f"changed:{relative.as_posix()}")
    return drift


def verify_patcher_idempotency(runtime_root: Path) -> None:
    target = runtime_root / PATCH_TARGET
    patcher = runtime_root / PATCHER
    if not target.is_file():
        raise FileNotFoundError(f"Hermes3D patch target not found: {target}")
    if not patcher.is_file():
        raise FileNotFoundError(f"Hermes3D patcher not found: {patcher}")
    if shutil.which("node") is None:
        raise RuntimeError("node is required for Hermes3D patch idempotency verification")

    with tempfile.TemporaryDirectory(prefix="hermes3d-consistency-") as temp_dir:
        workspace = Path(temp_dir)
        copied_target = workspace / PATCH_TARGET
        copied_patcher = workspace / PATCHER
        copied_target.parent.mkdir(parents=True, exist_ok=True)
        copied_patcher.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, copied_target)
        shutil.copy2(patcher, copied_patcher)

        before = sha256_file(copied_target)
        result = subprocess.run(
            ["node", str(PATCHER)],
            cwd=workspace,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            details = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"Hermes3D speech patch verification failed: {details}")
        after = sha256_file(copied_target)
        if before != after:
            raise RuntimeError(
                "Hermes3D runtime patch target drifted from the repository-generated state"
            )


def verify_runtime(repo_root: Path, runtime_root: Path, *, check_patcher: bool = True) -> list[str]:
    drift = compare_overlay(repo_root, runtime_root)
    if check_patcher:
        verify_patcher_idempotency(runtime_root)
    return drift


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify that a Hermes3D runtime matches the repository overlay and speech patch."
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--runtime", type=Path, default=Path("/root/Hermes3D-runtime"))
    parser.add_argument(
        "--skip-patcher",
        action="store_true",
        help="Skip the Node.js idempotency check and only compare overlay-managed files.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    drift = verify_runtime(
        args.repo_root.resolve(),
        args.runtime.resolve(),
        check_patcher=not args.skip_patcher,
    )
    if drift:
        print("Hermes3D runtime drift detected:")
        for item in drift:
            print(f"  - {item}")
        return 1
    print("Hermes3D runtime consistency: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
