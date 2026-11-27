"""card.py — 模特档案（model-card.json）加载。

查找顺序（先命中先用）：
  1. `REALPHOTO_HOME/model-card.json` —— 运行态本地调整，不动包
  2. 包内 `data/model-card.json` —— 使用方自己放的档案
  3. 包内 `data/model-card.example.json` —— 示例档案，保证开箱可用（provider 全关）
"""
import json
import os

from . import paths

_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_BUILTIN = os.path.join(_DATA, "model-card.json")
_EXAMPLE = os.path.join(_DATA, "model-card.example.json")


def card_path() -> str:
    override = os.path.join(paths.home(), "model-card.json")
    if os.path.exists(override):
        return override
    if os.path.exists(_BUILTIN):
        return _BUILTIN
    return _EXAMPLE


def load_card() -> dict:
    with open(card_path(), encoding="utf-8") as f:
        return json.load(f)
