from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from .live2d_constants import (
    DEFAULT_LIP_SYNC_PARAMETER_IDS,
    LIVE2D_SOURCE_BUILTIN,
    LIVE2D_SOURCE_EXTERNAL,
    LIVE2D_SOURCE_WORKSPACE,
)
from .live2d_models import Live2DModelCandidate


class BuddyLive2DModelCatalog:
    def __init__(self, workspace_root: Path, builtin_root: Path) -> None:
        self.workspace_root = workspace_root
        self.builtin_root = builtin_root

    def empty_config(self, mouse_follow_enabled: bool = True) -> dict[str, object]:
        return {
            "available": False,
            "source": "",
            "selection_key": "",
            "saved_selection_key": "",
            "model_name": "",
            "model_url": "",
            "directory_name": "",
            "mouse_follow_enabled": mouse_follow_enabled,
            "custom_model_url": "",
            "lip_sync_parameter_ids": DEFAULT_LIP_SYNC_PARAMETER_IDS[:],
            "mouth_form_parameter_id": None,
            "expressions": [],
            "motions": [],
            "emotion_expression_map": {},
            "motion_alias_map": {},
            "models": [],
            "supports_expressions": False,
            "supports_motions": False,
            "is_custom_model": False,
        }

    def discover_model_candidates(self) -> list[Live2DModelCandidate]:
        candidates: list[Live2DModelCandidate] = []
        for source, root in self._roots():
            if not root.exists():
                continue
            model_paths = sorted(
                root.rglob("*.model3.json"),
                key=lambda path: (len(path.parts), path.as_posix()),
            )
            for model_path in model_paths:
                candidate = self._candidate_from_path(source, root, model_path)
                if candidate is not None:
                    candidates.append(candidate)
        return candidates

    def select_candidate(
        self,
        candidates: list[Live2DModelCandidate],
        preferred_selection_key: str,
    ) -> Live2DModelCandidate | None:
        normalized_key = str(preferred_selection_key or "").strip()
        if normalized_key:
            for candidate in candidates:
                if self.selection_key_for(candidate) == normalized_key:
                    return candidate

        for candidate in candidates:
            relative_path = candidate.model_relative_path.as_posix()
            if (
                candidate.source == LIVE2D_SOURCE_BUILTIN
                and "mao_pro_en" in relative_path
            ):
                return candidate

        return candidates[0] if candidates else None

    def selection_key_for(self, candidate: Live2DModelCandidate) -> str:
        return f"{candidate.source}:{candidate.model_relative_path.as_posix()}"

    def directory_name_for(self, candidate: Live2DModelCandidate) -> str:
        runtime_relative_path = candidate.runtime_relative_path
        if len(runtime_relative_path.parts) > 1:
            return runtime_relative_path.parts[0]
        if runtime_relative_path.parts:
            return runtime_relative_path.name
        return candidate.model_name

    def asset_url_for(self, candidate: Live2DModelCandidate, relative_path: str) -> str:
        normalized = str(relative_path or "").replace("\\", "/")
        return f"/api/live2d/assets/{candidate.source}/{quote(normalized, safe='/')}"

    def resolve_asset(self, asset_path: str) -> Path:
        source, relative_path = self.parse_asset_path(asset_path)
        root = self._root_for(source)
        resolved_path = self._resolve_under_root(root, relative_path)
        if resolved_path is None:
            raise ValueError(f"Invalid Live2D asset path: {asset_path}")
        if not resolved_path.is_file():
            raise FileNotFoundError(asset_path)
        return resolved_path

    def candidate_from_selection_key(
        self,
        selection_key: str,
    ) -> Live2DModelCandidate | None:
        normalized = str(selection_key or "").strip()
        if not normalized or ":" not in normalized:
            return None

        source, raw_path = normalized.split(":", 1)
        if source not in {LIVE2D_SOURCE_WORKSPACE, LIVE2D_SOURCE_BUILTIN}:
            return None

        relative_path = self._normalize_relative_path(raw_path)
        if relative_path is None:
            return None

        root = self._root_for(source)
        resolved_path = self._resolve_under_root(root, relative_path)
        if resolved_path is None or not resolved_path.is_file():
            return None
        if not resolved_path.name.endswith(".model3.json"):
            return None

        return self._candidate_from_path(source, root, resolved_path)

    def candidate_for_asset(self, asset_path: str) -> Live2DModelCandidate | None:
        try:
            source, relative_path = self.parse_asset_path(asset_path)
        except ValueError:
            return None

        if not relative_path.name.endswith(".model3.json"):
            return None

        root = self._root_for(source)
        resolved_path = self._resolve_under_root(root, relative_path)
        if resolved_path is None or not resolved_path.is_file():
            return None
        return self._candidate_from_path(source, root, resolved_path)

    def parse_asset_path(self, asset_path: str) -> tuple[str, Path]:
        normalized_path = self._normalize_relative_path(asset_path)
        if normalized_path is None:
            raise ValueError(f"Invalid Live2D asset path: {asset_path}")

        source = normalized_path.parts[0]
        if source in {LIVE2D_SOURCE_WORKSPACE, LIVE2D_SOURCE_BUILTIN}:
            relative_path = Path(*normalized_path.parts[1:])
            if not relative_path.parts:
                raise ValueError(f"Invalid Live2D asset path: {asset_path}")
            return source, relative_path

        return LIVE2D_SOURCE_WORKSPACE, normalized_path

    def _roots(self) -> Iterable[tuple[str, Path]]:
        return (
            (LIVE2D_SOURCE_WORKSPACE, self.workspace_root),
            (LIVE2D_SOURCE_BUILTIN, self.builtin_root),
        )

    def _root_for(self, source: str) -> Path:
        if source == LIVE2D_SOURCE_BUILTIN:
            return self.builtin_root
        if source == LIVE2D_SOURCE_EXTERNAL:
            raise ValueError("External Live2D models do not have local assets")
        return self.workspace_root

    def _candidate_from_path(
        self,
        source: str,
        root: Path,
        model_path: Path,
    ) -> Live2DModelCandidate | None:
        resolved_root = root.resolve()
        resolved_model_path = model_path.resolve()
        if (
            resolved_model_path != resolved_root
            and resolved_root not in resolved_model_path.parents
        ):
            return None
        if not resolved_model_path.name.endswith(".model3.json"):
            return None
        return Live2DModelCandidate(
            source=source,
            source_root=resolved_root,
            model_path=resolved_model_path,
            runtime_root=resolved_model_path.parent,
        )

    @staticmethod
    def _normalize_relative_path(path_text: str) -> Path | None:
        normalized_text = str(path_text or "").replace("\\", "/").strip()
        if not normalized_text or normalized_text.startswith("/"):
            return None

        normalized_path = PurePosixPath(normalized_text)
        if not normalized_path.parts:
            return None
        if any(part in {"", ".", ".."} for part in normalized_path.parts):
            return None
        if any(":" in part for part in normalized_path.parts):
            return None

        return Path(*normalized_path.parts)

    @staticmethod
    def _resolve_under_root(root: Path, relative_path: Path) -> Path | None:
        resolved_root = root.resolve()
        resolved_path = (resolved_root / relative_path).resolve()
        if (
            resolved_path != resolved_root
            and resolved_root not in resolved_path.parents
        ):
            return None
        return resolved_path
