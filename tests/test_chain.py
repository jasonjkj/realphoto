"""test_chain.py — 抓模特 chain 配置化。

一图一测试要点：chain 顺序（主渠道→fallback）、单源失败隔离、自定义 provider
（外部函数 entry）、配置缺失回退默认链、本地相簿 local_dir 源直出。
"""
import json
import os
import struct

import pytest

from realphoto import config, grab, paths, providers, sources

CARD = {
    "schema": "model-card/1",
    "name": "test-model",
    "providers": {
        "pexels": {"enabled": True, "env_key": "PEXELS_API_KEY",
                   "endpoint": "http://pexels.test/search"},
        "pixabay": {"enabled": True, "env_key": "PIXABAY_API_KEY",
                    "endpoint": "http://pixabay.test/"},
    },
    "search_keywords": ["kw1"],
    "verify_prompt": "验货 prompt",
}

ACCEPT = json.dumps({"is_person": True, "is_single_person": True,
                     "is_usable": True, "reason": "ok"})


def _jpeg(w=320, h=200):
    sof = (b"\xff\xc0" + struct.pack(">H", 17) + b"\x08"
           + struct.pack(">HH", h, w) + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00")
    return b"\xff\xd8" + sof + b"\xff\xd9" + b"x" * 50000


@pytest.fixture
def env(tmp_path, monkeypatch):
    grab._vision_fail.clear()
    monkeypatch.setenv("PEXELS_API_KEY", "fake-key")
    monkeypatch.setenv("PIXABAY_API_KEY", "fake-key")
    monkeypatch.setattr(grab.paths, "grab_dir", lambda: str(tmp_path / "grab"))
    monkeypatch.setattr(grab.paths, "pool_dir", lambda: str(tmp_path / "pool"))
    monkeypatch.setattr(providers, "pexels_images",
                        lambda card, q, key: ["http://x.test/1.jpg"])
    monkeypatch.setattr(providers, "pixabay_images",
                        lambda card, q, key: ["http://y.test/1.jpg"])
    monkeypatch.setattr(grab, "bing_images", lambda q, n=10: ["http://b.test/9.jpg"])

    def fake_download(url, dst, **_):
        with open(dst, "wb") as f:
            f.write(_jpeg())
        return True

    monkeypatch.setattr(grab, "download_image", fake_download)
    return {"tmp": str(tmp_path)}


def _write_cfg(tmp, cfg):
    p = os.path.join(tmp, "cfg.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    return p


class TestChainOrder:
    def test_config_missing_uses_default_chain(self, env, monkeypatch):
        """配置缺失 → 默认链 [pexels, pixabay, bing]，主源 pexels 先命中。"""
        monkeypatch.setattr(config, "load_config", lambda: config.DEFAULTS)
        hit = grab.grab_one(CARD, see_image=lambda p, pr: ACCEPT)
        assert hit is not None and hit[1] == "pexels"

    def test_chain_order_first_wins(self, env, monkeypatch):
        """chain 顺序决定主渠道：pixabay 排前 → 先走 pixabay。"""
        cfg = {"chain": ["pixabay", "pexels"]}
        monkeypatch.setattr(config, "load_config", lambda: cfg)
        hit = grab.grab_one(CARD, see_image=lambda p, pr: ACCEPT)
        assert hit is not None and hit[1] == "pixabay"

    def test_first_source_empty_falls_through(self, env, monkeypatch):
        """主源空结果 → fallback 到下一源（不中断）。"""
        monkeypatch.setattr(providers, "pexels_images", lambda card, q, key: [])
        monkeypatch.setattr(config, "load_config",
                            lambda: {"chain": ["pexels", "pixabay"]})
        hit = grab.grab_one(CARD, see_image=lambda p, pr: ACCEPT)
        assert hit is not None and hit[1] == "pixabay"


class TestSourceIsolation:
    def test_first_source_crash_skips_to_next(self, env, monkeypatch):
        """单源异常（网络挂）→ stderr + 跳过，链不中断。"""
        def boom(card, q, key):
            raise RuntimeError("network down")

        monkeypatch.setattr(providers, "pexels_images", boom)
        monkeypatch.setattr(config, "load_config",
                            lambda: {"chain": ["pexels", "pixabay"]})
        hit = grab.grab_one(CARD, see_image=lambda p, pr: ACCEPT)
        assert hit is not None and hit[1] == "pixabay"

    def test_disabled_provider_skipped(self, env, monkeypatch):
        """enabled: false 的源不调。"""
        monkeypatch.setattr(config, "load_config", lambda: {
            "chain": ["pixabay"],
            "providers": {"pixabay": {"enabled": False,
                                      "entry": "builtin:pixabay"}},
        })
        assert grab.grab_one(CARD, see_image=lambda p, pr: ACCEPT) is None


class TestCustomProvider:
    def test_external_function_entry(self, env, monkeypatch, tmp_path):
        """自定义外部函数 provider（entry=<路径.py>:<func>）→ 用户可自放资源。"""
        ext = os.path.join(tmp_path, "my_source.py")
        with open(ext, "w", encoding="utf-8") as f:
            f.write("def my_fetch(query, ctx, opts):\n"
                    "    return ['http://mine.test/1.jpg']\n")
        monkeypatch.setattr(config, "load_config", lambda: {
            "chain": ["mine"],
            "providers": {"mine": {"enabled": True,
                                   "entry": "%s:my_fetch" % ext}},
        })
        hit = grab.grab_one(CARD, see_image=lambda p, pr: ACCEPT)
        assert hit is not None and hit[1] == "mine"

    def test_builtin_local_dir_source(self, env, monkeypatch, tmp_path):
        """builtin:local_dir 从真人相簿 photo/ 直出（免下载）。"""
        photo = os.path.join(tmp_path, "album", "photo")
        os.makedirs(photo, exist_ok=True)
        with open(os.path.join(photo, "p1.jpg"), "wb") as f:
            f.write(_jpeg())
        monkeypatch.setattr(config, "load_config", lambda: {
            "chain": ["local"],
            "providers": {"local": {"enabled": True, "entry": "builtin:local_dir",
                                    "options": {"dir": photo}}},
        })
        hit = grab.grab_one(CARD, see_image=lambda p, pr: ACCEPT)
        assert hit is not None and hit[1] == "local"


class TestConfigHelpers:
    def test_chain_of_default(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "load_config", lambda: {})
        assert config.chain_of() == ["pexels", "pixabay", "bing"]

    def test_chain_of_custom(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "load_config",
                            lambda: {"chain": ["bing", "local"]})
        assert config.chain_of() == ["bing", "local"]

    def test_album_dir_of(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "load_config",
                            lambda: {"album": {"dir": str(tmp_path)}})
        assert config.album_dir_of() == str(tmp_path)
        assert config.album_dir_of({"album": {}}) == paths.album_dir()

    def test_storage_dir_of(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "load_config",
                            lambda: {"storage": {"dir": str(tmp_path)}})
        assert config.storage_dir_of() == str(tmp_path)

    def test_album_dir_under_own_home(self, monkeypatch):
        """相簿缺省落在本包自己的数据目录下，不依赖任何外部域。"""
        monkeypatch.delenv("REALPHOTO_ALBUM_DIR", raising=False)
        monkeypatch.delenv("REALPHOTO_HOME", raising=False)
        ad = paths.album_dir()
        assert ad.endswith(os.path.join(".realphoto", "album"))
