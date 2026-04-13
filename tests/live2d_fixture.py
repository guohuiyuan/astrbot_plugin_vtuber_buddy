from __future__ import annotations

import json
from pathlib import Path


def create_sample_live2d_root(root: Path) -> str:
    runtime_root = root / "sample" / "runtime"
    expressions_root = runtime_root / "expressions"
    motions_root = runtime_root / "motions"
    textures_root = runtime_root / "sample.2048"

    expressions_root.mkdir(parents=True, exist_ok=True)
    motions_root.mkdir(parents=True, exist_ok=True)
    textures_root.mkdir(parents=True, exist_ok=True)

    (runtime_root / "sample.moc3").write_bytes(b"moc3")
    (textures_root / "texture_00.png").write_bytes(b"png")
    (runtime_root / "sample.physics3.json").write_text("{}", encoding="utf-8")
    (runtime_root / "sample.pose3.json").write_text("{}", encoding="utf-8")

    (runtime_root / "sample.cdi3.json").write_text(
        json.dumps(
            {
                "Parameters": [
                    {"Id": "ParamMouthOpenY"},
                    {"Id": "ParamMouthForm"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (expressions_root / "happy.exp3.json").write_text(
        json.dumps(
            {
                "Type": "Live2D Expression",
                "Parameters": [
                    {"Id": "ParamMouthForm", "Value": 0.5, "Blend": "Add"}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (motions_root / "idle.motion3.json").write_text("{}", encoding="utf-8")
    (motions_root / "wave.motion3.json").write_text("{}", encoding="utf-8")

    (runtime_root / "sample.model3.json").write_text(
        json.dumps(
            {
                "Version": 3,
                "FileReferences": {
                    "Moc": "sample.moc3",
                    "Textures": ["sample.2048/texture_00.png"],
                    "Physics": "sample.physics3.json",
                    "Pose": "sample.pose3.json",
                    "DisplayInfo": "sample.cdi3.json",
                    "Expressions": [
                        {
                            "Name": "happy",
                            "File": "expressions/happy.exp3.json",
                        }
                    ],
                    "Motions": {
                        "Idle": [{"File": "motions/idle.motion3.json"}],
                        "Wave": [{"File": "motions/wave.motion3.json"}],
                    },
                },
                "Groups": [
                    {
                        "Target": "Parameter",
                        "Name": "LipSync",
                        "Ids": ["ParamMouthOpenY"],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return "builtin:sample/runtime/sample.model3.json"
