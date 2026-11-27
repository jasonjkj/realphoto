"""test_config.py — 抓模特独立配置（加载 / 缺省回退 / 口语画像解析）。

要点：缺文件或损坏 → 回默认（n=5, stream=true）；口语词经 intent_words 映射到画像。
"""

import json

from realphoto import config


def test_defaults_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("REALPHOTO_CONFIG", str(tmp_path / "nope.json"))
    cfg = config.load_config()
    assert cfg["grab"]["n"] == 5
    assert cfg["grab"]["stream"] is True


def test_defaults_when_broken(tmp_path, monkeypatch):
    p = tmp_path / "broken.json"
    p.write_text("{bad json")
    monkeypatch.setenv("REALPHOTO_CONFIG", str(p))
    cfg = config.load_config()
    assert cfg["grab"]["n"] == 5


def test_load_and_resolve(tmp_path, monkeypatch):
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({
        "grab": {"n": 3, "stream": False},
        "profiles": {"street": {"keywords": ["k"], "verify_prompt": "v"}},
        "intent_words": {"街拍": "street"},
        "user_prefs": {},
    }), encoding="utf-8")
    monkeypatch.setenv("REALPHOTO_CONFIG", str(p))
    cfg = config.load_config()
    assert cfg["grab"]["n"] == 3
    assert cfg["grab"]["stream"] is False
    prof = config.resolve_profile("街拍", cfg)
    assert prof and prof["id"] == "street" and prof["keywords"] == ["k"]
    # 未命中画像 / 空入参 → None（调用方回退默认）
    assert config.resolve_profile("nope", cfg) is None
    assert config.resolve_profile(None, cfg) is None
