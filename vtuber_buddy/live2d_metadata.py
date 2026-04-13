from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .live2d_constants import (
    BUILTIN_PRESENTATION_HINTS,
    DEFAULT_MOUTH_FORM_PARAMETER_IDS,
    EMOTION_KEYS,
    MOTION_KEYS,
)
from .live2d_models import Live2DExpression, Live2DModelCandidate, Live2DMotion


class BuddyLive2DMetadataService:
    def load_model_data(self, candidate: Live2DModelCandidate) -> dict[str, Any]:
        return json.loads(candidate.model_path.read_text(encoding="utf-8"))

    def load_parameter_ids(
        self,
        candidate: Live2DModelCandidate,
        model_data: dict[str, Any],
    ) -> list[str]:
        file_references = model_data.get("FileReferences", {})
        display_info = file_references.get("DisplayInfo")
        if not isinstance(display_info, str) or not display_info.strip():
            return []

        display_info_path = candidate.model_path.parent / display_info
        if not display_info_path.exists():
            return []

        payload = json.loads(display_info_path.read_text(encoding="utf-8"))
        parameters = payload.get("Parameters", [])
        return [
            item["Id"]
            for item in parameters
            if isinstance(item, dict) and isinstance(item.get("Id"), str)
        ]

    @staticmethod
    def load_group_parameter_ids(
        model_data: dict[str, Any],
        group_name: str,
    ) -> list[str]:
        groups = model_data.get("Groups", [])
        for group in groups:
            if not isinstance(group, dict):
                continue
            if group.get("Target") != "Parameter":
                continue
            if group.get("Name") != group_name:
                continue
            return [
                parameter_id
                for parameter_id in group.get("Ids", [])
                if isinstance(parameter_id, str)
            ]
        return []

    def discover_expressions(
        self,
        candidate: Live2DModelCandidate,
        model_data: dict[str, Any],
    ) -> list[Live2DExpression]:
        expressions: dict[str, Live2DExpression] = {}
        file_references = model_data.get("FileReferences", {})
        raw_expressions = file_references.get("Expressions", [])
        if isinstance(raw_expressions, list):
            for item in raw_expressions:
                if not isinstance(item, dict):
                    continue
                expression_path = self._resolve_runtime_reference(
                    candidate.runtime_root,
                    candidate.model_path.parent,
                    item.get("File"),
                )
                if expression_path is None:
                    continue
                file_key = expression_path.relative_to(
                    candidate.runtime_root
                ).as_posix()
                expressions[file_key] = Live2DExpression(
                    name=str(item.get("Name") or expression_path.stem).strip()
                    or expression_path.stem,
                    file=file_key,
                    asset_relative_path=expression_path.relative_to(
                        candidate.source_root
                    ).as_posix(),
                )

        for expression_path in sorted(candidate.runtime_root.rglob("*.exp3.json")):
            file_key = expression_path.relative_to(candidate.runtime_root).as_posix()
            expressions.setdefault(
                file_key,
                Live2DExpression(
                    name=expression_path.name.removesuffix(".exp3.json"),
                    file=file_key,
                    asset_relative_path=expression_path.relative_to(
                        candidate.source_root
                    ).as_posix(),
                ),
            )

        return list(expressions.values())

    def discover_motions(
        self,
        candidate: Live2DModelCandidate,
        model_data: dict[str, Any],
    ) -> list[Live2DMotion]:
        motions: list[Live2DMotion] = []
        seen_files: set[str] = set()

        file_references = model_data.get("FileReferences", {})
        raw_motions = file_references.get("Motions", {})
        if isinstance(raw_motions, dict):
            for group_name, entries in raw_motions.items():
                if not isinstance(entries, list):
                    continue
                for index, item in enumerate(entries):
                    if not isinstance(item, dict):
                        continue
                    motion_path = self._resolve_runtime_reference(
                        candidate.runtime_root,
                        candidate.model_path.parent,
                        item.get("File"),
                    )
                    if motion_path is None:
                        continue
                    file_key = motion_path.relative_to(
                        candidate.runtime_root
                    ).as_posix()
                    if file_key in seen_files:
                        continue
                    seen_files.add(file_key)
                    motions.append(
                        Live2DMotion(
                            name=str(item.get("Name") or motion_path.stem).strip()
                            or motion_path.stem,
                            file=file_key,
                            asset_relative_path=motion_path.relative_to(
                                candidate.source_root
                            ).as_posix(),
                            group=str(group_name),
                            index=index,
                            definition=dict(item),
                        )
                    )

        grouped_indexes = {
            group_name: max(item.index for item in motions if item.group == group_name)
            + 1
            for group_name in {item.group for item in motions}
        }
        for motion_path in sorted(candidate.runtime_root.rglob("*.motion3.json")):
            file_key = motion_path.relative_to(candidate.runtime_root).as_posix()
            if file_key in seen_files:
                continue
            seen_files.add(file_key)
            group_name = "Auto"
            index = grouped_indexes.get(group_name, 0)
            grouped_indexes[group_name] = index + 1
            motions.append(
                Live2DMotion(
                    name=motion_path.name.removesuffix(".motion3.json"),
                    file=file_key,
                    asset_relative_path=motion_path.relative_to(
                        candidate.source_root
                    ).as_posix(),
                    group=group_name,
                    index=index,
                    definition={"File": file_key},
                )
            )

        return motions

    def patch_model_data(
        self,
        candidate: Live2DModelCandidate,
        model_data: dict[str, Any],
        expressions: list[Live2DExpression],
        motions: list[Live2DMotion],
    ) -> dict[str, Any]:
        patched_model = json.loads(json.dumps(model_data))
        file_references = patched_model.setdefault("FileReferences", {})
        if not isinstance(file_references, dict):
            file_references = {}
            patched_model["FileReferences"] = file_references

        if expressions:
            file_references["Expressions"] = [
                {
                    "Name": expression.name,
                    "File": self._relative_file_to_model_parent(
                        candidate,
                        expression.asset_relative_path,
                    ),
                }
                for expression in expressions
            ]

        if motions:
            grouped: dict[str, list[dict[str, Any]]] = {}
            for motion in motions:
                entry = dict(motion.definition)
                entry["File"] = self._relative_file_to_model_parent(
                    candidate,
                    motion.asset_relative_path,
                )
                group_entries = grouped.setdefault(motion.group, [])
                while len(group_entries) <= motion.index:
                    group_entries.append({})
                group_entries[motion.index] = entry
            file_references["Motions"] = grouped

        return patched_model

    def build_presentation_maps(
        self,
        selection_key: str,
        expressions: list[Live2DExpression],
        motions: list[Live2DMotion],
    ) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        return (
            self._build_expression_map(selection_key, expressions),
            self._build_motion_map(selection_key, motions),
        )

    def resolve_mouth_form_parameter_id(self, parameter_ids: list[str]) -> str | None:
        for parameter_id in parameter_ids:
            if "MouthForm" in parameter_id:
                return parameter_id
        for parameter_id in DEFAULT_MOUTH_FORM_PARAMETER_IDS:
            if parameter_id in parameter_ids:
                return parameter_id
        return None

    def _build_expression_map(
        self,
        selection_key: str,
        expressions: list[Live2DExpression],
    ) -> dict[str, str]:
        by_file = {item.file: item for item in expressions}
        by_name = {item.name.casefold(): item for item in expressions}
        result: dict[str, str] = {}

        hints = BUILTIN_PRESENTATION_HINTS.get(selection_key, {}).get(
            "emotion_expression_map",
            {},
        )
        for emotion in EMOTION_KEYS:
            hinted_file = str(hints.get(emotion, "")).strip()
            if hinted_file in by_file:
                result[emotion] = hinted_file

        keyword_map = {
            "happy": ("happy", "smile", "laugh"),
            "shy": ("shy", "blush"),
            "excited": ("excited", "surprise", "sparkle"),
            "grumpy": ("angry", "grumpy", "mad"),
            "concerned": ("sad", "worry", "concern"),
            "sleepy": ("sleep", "tired", "closed"),
        }
        for emotion, keywords in keyword_map.items():
            if emotion in result:
                continue
            matched = next(
                (
                    item.file
                    for key, item in by_name.items()
                    if any(keyword in key for keyword in keywords)
                ),
                "",
            )
            if matched:
                result[emotion] = matched

        if "neutral" not in result and expressions:
            result["neutral"] = expressions[0].file

        return result

    def _build_motion_map(
        self,
        selection_key: str,
        motions: list[Live2DMotion],
    ) -> dict[str, dict[str, Any]]:
        by_group_index = {(item.group, item.index): item for item in motions}
        result: dict[str, dict[str, Any]] = {}

        hints = BUILTIN_PRESENTATION_HINTS.get(selection_key, {}).get(
            "motion_alias_map",
            {},
        )
        for motion_name in MOTION_KEYS:
            hint = hints.get(motion_name)
            if not hint:
                continue
            candidate = by_group_index.get((str(hint[0]), int(hint[1])))
            if candidate is None:
                continue
            result[motion_name] = self._motion_payload(candidate)

        lookup_rules = {
            "idle": ("idle",),
            "wave": ("wave", "tap", "flick"),
            "nod": ("nod", "idle", "tap"),
            "bounce": ("jump", "bounce", "flickup", "body"),
            "pout": ("angry", "body", "special"),
            "blink": ("blink", "idle"),
        }
        for motion_name, keywords in lookup_rules.items():
            if motion_name in result:
                continue
            matched = self._find_motion_by_keyword(motions, keywords)
            if matched is not None:
                result[motion_name] = self._motion_payload(matched)

        if "idle" not in result and motions:
            idle_candidate = next(
                (item for item in motions if item.group.casefold() == "idle"),
                motions[0],
            )
            result["idle"] = self._motion_payload(idle_candidate)

        non_idle = [item for item in motions if item.group.casefold() != "idle"]
        for motion_name in ("wave", "nod", "bounce", "pout", "blink"):
            if motion_name in result:
                continue
            fallback = non_idle[0] if non_idle else motions[0] if motions else None
            if fallback is not None:
                result[motion_name] = self._motion_payload(fallback)

        return result

    @staticmethod
    def _find_motion_by_keyword(
        motions: list[Live2DMotion],
        keywords: tuple[str, ...],
    ) -> Live2DMotion | None:
        for motion in motions:
            haystack = " ".join(
                [
                    motion.name.casefold(),
                    motion.file.casefold(),
                    motion.group.casefold(),
                ]
            )
            if any(keyword in haystack for keyword in keywords):
                return motion
        return None

    @staticmethod
    def _motion_payload(motion: Live2DMotion) -> dict[str, Any]:
        return {
            "name": motion.name,
            "file": motion.file,
            "group": motion.group,
            "index": motion.index,
        }

    @staticmethod
    def _resolve_runtime_reference(
        runtime_root: Path,
        base_directory: Path,
        file_reference: Any,
    ) -> Path | None:
        normalized = str(file_reference or "").replace("\\", "/").strip()
        if not normalized:
            return None
        reference_path = Path(normalized)
        if reference_path.is_absolute():
            return None
        resolved_path = (base_directory / reference_path).resolve()
        resolved_runtime_root = runtime_root.resolve()
        if (
            resolved_path != resolved_runtime_root
            and resolved_runtime_root not in resolved_path.parents
        ):
            return None
        if not resolved_path.is_file():
            return None
        return resolved_path

    @staticmethod
    def _relative_file_to_model_parent(
        candidate: Live2DModelCandidate,
        asset_relative_path: str,
    ) -> str:
        asset_path = candidate.source_root / asset_relative_path
        return asset_path.relative_to(candidate.model_path.parent).as_posix()
