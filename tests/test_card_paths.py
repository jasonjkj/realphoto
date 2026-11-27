"""test_card_paths.py — model-card 加载与路径解析（包内置 + REALPHOTO_HOME 覆盖）。"""
import json
import os

from realphoto import card as card_mod
from realphoto import paths


class TestCard:
    def test_builtin_card_loads(self, monkeypatch, tmp_path):
        monkeypatch.setenv("REALPHOTO_HOME", str(tmp_path / "empty"))
        c = card_mod.load_card()
        assert c["schema"] == "model-card/1"
        assert c["search_keywords"]
        assert "verify_prompt" in c and "accept_rule" in c
        # 开箱回退的是示例档案：provider 默认全关，不带任何可用配置
        assert all(not p["enabled"] for p in c["providers"].values())

    def test_home_override_wins(self, monkeypatch, tmp_path):
        home = tmp_path / "rp"
        home.mkdir()
        (home / "model-card.json").write_text(
            json.dumps({"schema": "model-card/1", "name": "override"}), encoding="utf-8")
        monkeypatch.setenv("REALPHOTO_HOME", str(home))
        assert card_mod.load_card()["name"] == "override"


class TestPaths:
    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("REALPHOTO_HOME", raising=False)
        monkeypatch.delenv("REALPHOTO_ALBUM_DIR", raising=False)
        monkeypatch.delenv("REALPHOTO_VISION_CMD", raising=False)
        # 缺省全部落在用户自己的数据目录，不绑定任何外部结构
        assert paths.home().endswith(".realphoto")
        assert paths.album_dir().endswith(os.path.join(".realphoto", "album"))
        assert paths.grab_dir().endswith(os.path.join(".realphoto", "model-grab"))
        # 验货入口没配置 → None（调用方 fail-closed）
        assert paths.vision_cmd() is None

    def test_env_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("REALPHOTO_HOME", str(tmp_path))
        monkeypatch.setenv("REALPHOTO_ALBUM_DIR", str(tmp_path / "album"))
        assert paths.grab_dir() == str(tmp_path / "model-grab")
        assert paths.pool_dir() == str(tmp_path / "model-pool")
        assert paths.album_dir() == str(tmp_path / "album")
