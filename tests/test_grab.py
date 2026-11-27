"""test_grab.py — 抓模特链路（providers / 下载 / vision 全 mock，零真网零真 key）。

一图一测试要点（spec §9）：命中链路 + vision 验货正反 + 本地硬闸门 + md5 去重 +
fail-closed（验货入口异常 = 不合格，不放过可疑图）+ 来源连续失败熔断。
"""
import json
import os
import struct

import pytest

from realphoto import grab, providers

CARD = {
    "schema": "model-card/1",
    "name": "test-model",
    "providers": {
        "pexels": {"enabled": True, "env_key": "PEXELS_API_KEY",
                   "endpoint": "http://pexels.test/search"},
        "pixabay": {"enabled": True, "env_key": "PIXABAY_API_KEY",
                    "endpoint": "http://pixabay.test/"},
    },
    "search_keywords": ["kw1", "kw2"],
    "verify_prompt": "验货 prompt",
}

ACCEPT = json.dumps({"is_person": True, "is_single_person": True,
                     "is_usable": True, "reason": "ok"})
REJECT = json.dumps({"is_person": True, "is_single_person": False,
                     "is_usable": False, "reason": "风格不符"})


def _jpeg(w=320, h=200):
    sof = (b"\xff\xc0" + struct.pack(">H", 17) + b"\x08"
           + struct.pack(">HH", h, w) + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00")
    return b"\xff\xd8" + sof + b"\xff\xd9" + b"x" * 50000


@pytest.fixture
def env(tmp_path, monkeypatch):
    """隔离运行态目录 + 默认 mock：pexels 出 2 候选、下载成真图、其余源空。"""
    gd = str(tmp_path / "grab")
    pl = str(tmp_path / "pool")
    grab._vision_fail.clear()  # 模块级熔断状态，测试间隔离
    monkeypatch.setenv("PEXELS_API_KEY", "fake-key")
    monkeypatch.setattr(grab.paths, "grab_dir", lambda: gd)
    monkeypatch.setattr(grab.paths, "pool_dir", lambda: pl)
    monkeypatch.setattr(providers, "pexels_images",
                        lambda card, q, key: ["http://x.test/1.jpg", "http://x.test/2.jpg"])
    monkeypatch.setattr(providers, "pixabay_images", lambda card, q, key: [])
    monkeypatch.setattr(grab, "bing_images", lambda q, n=10: [])

    def fake_download(url, dst, **_):
        with open(dst, "wb") as f:
            f.write(_jpeg())
        return True

    monkeypatch.setattr(grab, "download_image", fake_download)
    return {"grab_dir": gd, "pool": pl}


class TestGrabOne:
    def test_happy_path_accept(self, env):
        see = lambda p, pr: ACCEPT
        hit = grab.grab_one(CARD, see_image=see)
        assert hit is not None
        dst, src = hit
        assert src == "pexels"  # chain 源名（配置 chain 顺序，小写）
        assert os.path.basename(dst).startswith("模特-")
        # last.json 已记 md5（跨进程去重）
        with open(os.path.join(env["grab_dir"], "last.json"), encoding="utf-8") as f:
            assert len(json.load(f)["md5s"]) == 1

    def test_vision_reject_retries_next_candidate(self, env, tmp_path):
        # 第一张验货不合格 → 不落盘重抓；第二张合格 → 命中
        calls = []

        def see(p, pr):
            calls.append(p)
            return REJECT if len(calls) == 1 else ACCEPT

        hit = grab.grab_one(CARD, see_image=see)
        assert hit is not None
        assert len(calls) == 2

    def test_vision_reject_all_returns_none(self, env):
        hit = grab.grab_one(CARD, see_image=lambda p, pr: REJECT)
        assert hit is None
        # 不合格图已清理，grab 目录无成品
        assert not os.path.isdir(env["grab_dir"]) or \
            [f for f in os.listdir(env["grab_dir"]) if f.endswith(".jpg")] == []

    def test_vision_error_fail_closed(self, env):
        """验货入口异常 = 不通过（fail-closed，不放过可疑图）。"""
        def boom(p, pr):
            raise RuntimeError("vision entry missing")

        assert grab.grab_one(CARD, see_image=boom) is None

    def test_vision_fail_limit_breaks_source(self, env):
        """同源连续 vision 失败达上限 → 熔断该来源（不重抓死循环）。"""
        monkeypatch_urls = ["http://x.test/%d.jpg" % i for i in range(10)]
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(providers, "pexels_images",
                            lambda card, q, key: monkeypatch_urls)
        try:
            hit = grab.grab_one(CARD, see_image=lambda p, pr: REJECT)
            assert hit is None
            assert grab._vision_fail.get("pexels", 0) >= grab.VISION_FAIL_LIMIT
        finally:
            monkeypatch.undo()
            grab._vision_fail.clear()

    def test_md5_dedup_against_history(self, env):
        # 历史已发图（同字节 = 同 md5）→ 候选被跳过
        os.makedirs(env["grab_dir"], exist_ok=True)
        with open(os.path.join(env["grab_dir"], "模特-历史.jpg"), "wb") as f:
            f.write(_jpeg())
        hit = grab.grab_one(CARD, see_image=lambda p, pr: ACCEPT)
        assert hit is None  # 两个候选字节相同，全被去重

    def test_min_dim_gate(self, env, monkeypatch):
        # 尺寸闸门：50x40 < MIN_DIM → 拒（不进 vision）
        def tiny_download(url, dst, **_):
            with open(dst, "wb") as f:
                f.write(_jpeg(50, 40))
            return True

        monkeypatch.setattr(grab, "download_image", tiny_download)
        seen = []
        hit = grab.grab_one(CARD, see_image=lambda p, pr: seen.append(p) or ACCEPT)
        assert hit is None
        assert seen == []  # 没进 vision（省 token）

    def test_kw_override(self, env, monkeypatch):
        used = []
        monkeypatch.setattr(providers, "pexels_images",
                            lambda card, q, key: used.append(q) or ["http://x.test/1.jpg"])
        grab.grab_one(CARD, kw="custom kw", see_image=lambda p, pr: ACCEPT)
        assert used == ["custom kw"]  # 覆盖卡内关键词

    def test_bing_fallback(self, env, monkeypatch):
        monkeypatch.setattr(providers, "pexels_images", lambda card, q, key: [])
        monkeypatch.setattr(providers, "pixabay_images", lambda card, q, key: [])
        monkeypatch.setattr(grab, "bing_images",
                            lambda q, n=10: ["http://b.test/9.jpg"])
        hit = grab.grab_one(CARD, see_image=lambda p, pr: ACCEPT)
        assert hit is not None and hit[1] == "bing"  # chain 兜底源名（小写）


class TestFillConsume:
    def test_fill_accepts_only_passed(self, env):
        n = grab.fill(2, CARD, CARD["verify_prompt"],
                      see_image=lambda p, pr: ACCEPT, pool=env["pool"])
        assert n >= 1
        assert grab.pool_size(env["pool"]) == n

    def test_fill_vision_error_not_stocked(self, env):
        def boom(p, pr):
            raise RuntimeError("no vision")

        assert grab.fill(1, CARD, CARD["verify_prompt"], see_image=boom,
                         pool=env["pool"]) == 0

    def test_consume_moves_from_pool(self, env):
        grab.fill(1, CARD, CARD["verify_prompt"],
                  see_image=lambda p, pr: ACCEPT, pool=env["pool"])
        dst = grab.consume(CARD, CARD["verify_prompt"],
                           see_image=lambda p, pr: ACCEPT,
                           pool=env["pool"], grab_dir=env["grab_dir"])
        assert dst and os.path.exists(dst)


class TestPassesAccept:
    def test_all_true(self):
        assert grab.passes_accept(json.loads(ACCEPT))

    @pytest.mark.parametrize("key", ["is_person", "is_single_person", "is_usable"])
    def test_any_false_rejects(self, key):
        j = json.loads(ACCEPT)
        j[key] = False
        assert not grab.passes_accept(j)

    def test_missing_key_rejects(self):
        assert not grab.passes_accept({"is_person": True})


class TestGrabMany:
    """grab_many（n 张流式）：命中数 / 失败即停 / 画像 kw+vprompt 透传。"""

    def test_yields_n_hits(self, monkeypatch):
        monkeypatch.setattr(
            grab, "grab_one",
            lambda card, kw=None, see_image=None, grab_dir=None,
                   pool=None, vprompt=None: ("/tmp/m.jpg", "Pexels"))
        got = list(grab.grab_many(CARD, n=3))
        assert len(got) == 3

    def test_stops_on_first_miss(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            grab, "grab_one",
            lambda card, kw=None, see_image=None, grab_dir=None,
                   pool=None, vprompt=None: calls.append(1) or None)
        assert list(grab.grab_many(CARD, n=5)) == []
        assert len(calls) == 1  # 第一张失败即停，不空转

    def test_profile_kw_and_vprompt(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            grab, "grab_one",
            lambda card, kw=None, see_image=None, grab_dir=None,
                   pool=None, vprompt=None: seen.update(kw=kw, vprompt=vprompt) or None)
        prof = {"keywords": ["x1", "x2"], "verify_prompt": "p2"}
        list(grab.grab_many(CARD, n=1, profile_cfg=prof))
        assert seen["kw"] == "x1"
        assert seen["vprompt"] == "p2"

    def test_default_profile_uses_card(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            grab, "grab_one",
            lambda card, kw=None, see_image=None, grab_dir=None,
                   pool=None, vprompt=None: seen.update(kw=kw, vprompt=vprompt) or None)
        list(grab.grab_many(CARD, n=1, profile_cfg=None))
        assert seen["kw"] == "kw1"          # card.search_keywords[0]
        assert seen["vprompt"] == "验货 prompt"  # card.verify_prompt
