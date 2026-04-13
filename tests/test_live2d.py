from __future__ import annotations

import json

import pytest

from data.plugins.astrbot_plugin_vtuber_buddy.tests.live2d_fixture import (
    create_sample_live2d_root,
)
from data.plugins.astrbot_plugin_vtuber_buddy.vtuber_buddy.live2d_service import (
    BuddyLive2DService,
)


@pytest.mark.asyncio
async def test_live2d_service_builds_config_and_patches_model_json(tmp_path):
    builtin_root = tmp_path / "builtin_live2d"
    selection_key = create_sample_live2d_root(builtin_root)
    service = BuddyLive2DService(
        workspace_root=tmp_path / "workspace_live2d",
        builtin_root=builtin_root,
        default_selection_key=selection_key,
    )

    config = await service.build_config(selection_key=selection_key)
    assert config["available"] is True
    assert config["selection_key"] == selection_key
    assert config["model_name"] == "sample"
    assert config["lip_sync_parameter_ids"] == ["ParamMouthOpenY"]
    assert config["emotion_expression_map"]["happy"] == "expressions/happy.exp3.json"
    assert config["motion_alias_map"]["idle"]["group"] == "Idle"

    rendered = await service.render_model_json("builtin/sample/runtime/sample.model3.json")
    payload = json.loads(rendered)
    assert payload["FileReferences"]["Expressions"][0]["File"] == "expressions/happy.exp3.json"
    assert payload["FileReferences"]["Motions"]["Wave"][0]["File"] == "motions/wave.motion3.json"


@pytest.mark.asyncio
async def test_live2d_service_can_fall_back_to_external_model_url(tmp_path):
    builtin_root = tmp_path / "builtin_live2d"
    selection_key = create_sample_live2d_root(builtin_root)
    service = BuddyLive2DService(
        workspace_root=tmp_path / "workspace_live2d",
        builtin_root=builtin_root,
        default_selection_key=selection_key,
    )

    config = await service.build_config(
        selection_key=selection_key,
        custom_model_url="https://example.com/live2d/model3.json",
        mouse_follow_enabled=False,
    )
    assert config["available"] is True
    assert config["source"] == "external"
    assert config["is_custom_model"] is True
    assert config["mouse_follow_enabled"] is False
    assert config["models"][0]["selection_key"] == selection_key
