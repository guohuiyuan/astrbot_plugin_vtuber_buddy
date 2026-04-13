from __future__ import annotations

DEFAULT_LIP_SYNC_PARAMETER_IDS = [
    "ParamMouthOpenY",
    "PARAM_MOUTH_OPEN_Y",
    "MouthOpenY",
    "ParamA",
]

DEFAULT_MOUTH_FORM_PARAMETER_IDS = [
    "ParamMouthForm",
    "PARAM_MOUTH_FORM",
    "MouthForm",
]

LIVE2D_SOURCE_WORKSPACE = "workspace"
LIVE2D_SOURCE_BUILTIN = "builtin"
LIVE2D_SOURCE_EXTERNAL = "external"

DEFAULT_LIVE2D_SELECTION_KEY = "builtin:mao_pro_en/runtime/mao_pro.model3.json"

EMOTION_KEYS = (
    "neutral",
    "happy",
    "shy",
    "excited",
    "grumpy",
    "concerned",
    "sleepy",
)

MOTION_KEYS = (
    "idle",
    "wave",
    "nod",
    "bounce",
    "pout",
    "blink",
)

BUILTIN_PRESENTATION_HINTS = {
    "builtin:mao_pro_en/runtime/mao_pro.model3.json": {
        "emotion_expression_map": {
            "neutral": "expressions/exp_01.exp3.json",
            "happy": "expressions/exp_02.exp3.json",
            "shy": "expressions/exp_06.exp3.json",
            "excited": "expressions/exp_04.exp3.json",
            "grumpy": "expressions/exp_08.exp3.json",
            "concerned": "expressions/exp_05.exp3.json",
            "sleepy": "expressions/exp_07.exp3.json",
        },
        "motion_alias_map": {
            "idle": ("Idle", 0),
            "wave": ("", 0),
            "nod": ("", 1),
            "bounce": ("", 2),
            "pout": ("", 3),
            "blink": ("Idle", 0),
        },
    },
    "builtin:hiyori_pro_en/runtime/hiyori_pro_t11.model3.json": {
        "motion_alias_map": {
            "idle": ("Idle", 0),
            "wave": ("Tap", 0),
            "nod": ("Tap", 1),
            "bounce": ("FlickUp", 0),
            "pout": ("Flick@Body", 0),
            "blink": ("Idle", 1),
        },
    },
}
