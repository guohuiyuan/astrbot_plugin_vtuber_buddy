from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from .live2d_catalog import BuddyLive2DModelCatalog
from .live2d_constants import (
    DEFAULT_LIP_SYNC_PARAMETER_IDS,
    DEFAULT_LIVE2D_SELECTION_KEY,
    LIVE2D_SOURCE_EXTERNAL,
)
from .live2d_metadata import BuddyLive2DMetadataService
from .live2d_models import Live2DModelCandidate


class BuddyLive2DService:
    def __init__(
        self,
        *,
        workspace_root: Path,
        builtin_root: Path,
        default_selection_key: str = DEFAULT_LIVE2D_SELECTION_KEY,
    ) -> None:
        self.catalog = BuddyLive2DModelCatalog(workspace_root, builtin_root)
        self.metadata = BuddyLive2DMetadataService()
        self.default_selection_key = (
            default_selection_key.strip() or DEFAULT_LIVE2D_SELECTION_KEY
        )

    async def build_config(
        self,
        *,
        selection_key: str = "",
        custom_model_url: str = "",
        mouse_follow_enabled: bool = True,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._build_config_sync,
            selection_key,
            custom_model_url,
            mouse_follow_enabled,
        )

    async def render_model_json(self, asset_path: str) -> str:
        return await asyncio.to_thread(self._render_model_json_sync, asset_path)

    def resolve_asset(self, asset_path: str) -> Path:
        return self.catalog.resolve_asset(asset_path)

    def _build_config_sync(
        self,
        selection_key: str,
        custom_model_url: str,
        mouse_follow_enabled: bool,
    ) -> dict[str, Any]:
        candidates = self.catalog.discover_model_candidates()
        model_options = [
            self._build_model_option(candidate) for candidate in candidates
        ]
        preferred_key = str(selection_key or "").strip() or self.default_selection_key
        selected_candidate = self.catalog.select_candidate(candidates, preferred_key)
        active_selection_key = (
            self.catalog.selection_key_for(selected_candidate)
            if selected_candidate is not None
            else ""
        )
        selected_option = next(
            (
                option
                for option in model_options
                if option["selection_key"] == active_selection_key
            ),
            None,
        )

        custom_model_url = str(custom_model_url or "").strip()
        if custom_model_url:
            return {
                **self.catalog.empty_config(mouse_follow_enabled),
                "available": True,
                "source": LIVE2D_SOURCE_EXTERNAL,
                "selection_key": f"{LIVE2D_SOURCE_EXTERNAL}:{custom_model_url}",
                "saved_selection_key": preferred_key,
                "model_name": "Custom Live2D URL",
                "model_url": custom_model_url,
                "directory_name": "custom",
                "mouse_follow_enabled": mouse_follow_enabled,
                "custom_model_url": custom_model_url,
                "models": model_options,
                "is_custom_model": True,
            }

        if selected_option is None:
            payload = self.catalog.empty_config(mouse_follow_enabled)
            payload["saved_selection_key"] = preferred_key
            payload["models"] = model_options
            return payload

        return {
            **selected_option,
            "available": True,
            "saved_selection_key": preferred_key,
            "mouse_follow_enabled": mouse_follow_enabled,
            "custom_model_url": "",
            "models": model_options,
            "is_custom_model": False,
        }

    def _render_model_json_sync(self, asset_path: str) -> str:
        candidate = self.catalog.candidate_for_asset(asset_path)
        if candidate is None:
            raise FileNotFoundError(asset_path)

        model_data = self.metadata.load_model_data(candidate)
        expressions = self.metadata.discover_expressions(candidate, model_data)
        motions = self.metadata.discover_motions(candidate, model_data)
        patched = self.metadata.patch_model_data(
            candidate,
            model_data,
            expressions,
            motions,
        )
        return json.dumps(patched, ensure_ascii=False)

    def _build_model_option(self, candidate: Live2DModelCandidate) -> dict[str, Any]:
        model_data = self.metadata.load_model_data(candidate)
        expressions = self.metadata.discover_expressions(candidate, model_data)
        motions = self.metadata.discover_motions(candidate, model_data)
        parameter_ids = self.metadata.load_parameter_ids(candidate, model_data)
        lip_sync_parameter_ids = self._resolve_lip_sync_parameter_ids(
            model_data,
            parameter_ids,
        )
        mouth_form_parameter_id = self.metadata.resolve_mouth_form_parameter_id(
            parameter_ids
        )
        selection_key = self.catalog.selection_key_for(candidate)
        emotion_expression_map, motion_alias_map = (
            self.metadata.build_presentation_maps(
                selection_key,
                expressions,
                motions,
            )
        )

        return {
            "source": candidate.source,
            "selection_key": selection_key,
            "model_name": candidate.model_name,
            "model_url": self.catalog.asset_url_for(
                candidate,
                candidate.model_relative_path.as_posix(),
            ),
            "directory_name": self.catalog.directory_name_for(candidate),
            "lip_sync_parameter_ids": lip_sync_parameter_ids,
            "mouth_form_parameter_id": mouth_form_parameter_id,
            "expressions": [
                {
                    "name": item.name,
                    "file": item.file,
                    "url": self.catalog.asset_url_for(
                        candidate, item.asset_relative_path
                    ),
                }
                for item in expressions
            ],
            "motions": [
                {
                    "name": item.name,
                    "file": item.file,
                    "url": self.catalog.asset_url_for(
                        candidate, item.asset_relative_path
                    ),
                    "group": item.group,
                    "index": item.index,
                }
                for item in motions
            ],
            "emotion_expression_map": emotion_expression_map,
            "motion_alias_map": motion_alias_map,
            "supports_expressions": bool(expressions),
            "supports_motions": bool(motions),
        }

    def _resolve_lip_sync_parameter_ids(
        self,
        model_data: dict[str, Any],
        parameter_ids: list[str],
    ) -> list[str]:
        group_ids = self.metadata.load_group_parameter_ids(model_data, "LipSync")
        if group_ids:
            return group_ids

        inferred_ids = [
            parameter_id
            for parameter_id in parameter_ids
            if "MouthOpen" in parameter_id or parameter_id == "ParamA"
        ]
        if inferred_ids:
            return inferred_ids
        return DEFAULT_LIP_SYNC_PARAMETER_IDS[:]
