"""test_bff.py — BFF 统一契约（MEDIA: 协议）。"""
import json
import os

from realphoto import bff


def _mk_album(tmp_path, photos=3, videos=1):
    base = tmp_path / "album"
    for i in range(photos):
        (base / "photo").mkdir(parents=True, exist_ok=True)
        (base / "photo" / ("p%d.jpg" % i)).write_bytes(b"\xff\xd8\xff" + bytes([i]))
    for i in range(videos):
        (base / "video").mkdir(parents=True, exist_ok=True)
        (base / "video" / ("v%d.mp4" % i)).write_bytes(b"fake")
    return str(base)


class TestSendAsset:
    def test_media_protocol(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("REALPHOTO_ALBUM_DIR", _mk_album(tmp_path))
        rc = bff.send_asset(n=2)
        out = capsys.readouterr().out
        media = [l for l in out.splitlines() if l.startswith("MEDIA:")]
        assert rc == 0 and len(media) == 2
        assert all(os.path.exists(l[6:]) for l in media)

    def test_video(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("REALPHOTO_ALBUM_DIR", _mk_album(tmp_path))
        assert bff.send_asset(video=True) == 0
        assert "MEDIA:" in capsys.readouterr().out

    def test_no_image(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("REALPHOTO_ALBUM_DIR", str(tmp_path / "empty"))
        assert bff.send_asset() == 1
        assert "NO_IMAGE" in capsys.readouterr().out


class TestGrabModel:
    def test_hit_streams_media(self, tmp_path, monkeypatch, capsys):
        """默认流式：每张一行 MEDIA + PROGRESS（count 默认 5）。"""
        dst = tmp_path / "模特-1.jpg"
        dst.write_bytes(b"\xff\xd8\xff")
        monkeypatch.setattr(bff.grab, "grab_one",
                            lambda card, kw=None, see_image=None, grab_dir=None,
                                   pool=None, vprompt=None: (str(dst), "Pexels"))
        assert bff.grab_model() == 0
        out = capsys.readouterr().out
        assert "MEDIA:%s" % dst in out
        assert "PROGRESS: 已出 5/5" in out

    def test_no_good(self, monkeypatch, capsys):
        monkeypatch.setattr(bff.grab, "grab_one",
                            lambda card, kw=None, see_image=None, grab_dir=None,
                                   pool=None, vprompt=None: None)
        assert bff.grab_model() == 1
        assert "NO_GOOD" in capsys.readouterr().err

    def test_profile_routing(self, tmp_path, monkeypatch, capsys):
        """口语画像（"街拍"）→ grab_many 收到对应 profile_cfg + 按配置 n/流式。"""
        dst = tmp_path / "m.jpg"
        dst.write_bytes(b"\xff\xd8\xff")
        captured = {}

        def fake_grab_many(card, n=5, profile_cfg=None, *, see_image="__default__"):
            captured["profile_cfg"] = profile_cfg
            return [(str(dst), "Pexels")]

        monkeypatch.setattr(bff.grab, "grab_many", fake_grab_many)
        cfgp = tmp_path / "cfg.json"
        cfgp.write_text(json.dumps({
            "grab": {"n": 2, "stream": True},
            "profiles": {"street": {"keywords": ["k"], "verify_prompt": "v"}},
            "intent_words": {"街拍": "street"},
        }), encoding="utf-8")
        monkeypatch.setenv("REALPHOTO_CONFIG", str(cfgp))
        assert bff.grab_model(n=None, profile="街拍") == 0
        assert captured["profile_cfg"]["id"] == "street"
        assert "PROGRESS: 已出 1/2" in capsys.readouterr().out

    def test_kw_old_path(self, tmp_path, monkeypatch, capsys):
        """旧用法：--kw 走单张 grab_one + 来源行。"""
        dst = tmp_path / "kw.jpg"
        dst.write_bytes(b"\xff\xd8\xff")
        monkeypatch.setattr(bff.grab, "grab_one",
                            lambda card, kw=None, see_image=None: (str(dst), "Pexels"))
        assert bff.grab_model(kw="portrait") == 0
        out = capsys.readouterr().out
        assert "MEDIA:%s" % dst in out
        assert "来源: Pexels" in out


class TestPoolStatus:
    def test_json_fields(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("REALPHOTO_HOME", str(tmp_path / "rp"))
        assert bff.pool_status() == 0
        d = json.loads(capsys.readouterr().out)
        for k in ("home", "grab_dir", "grab_count", "pool_dir", "pool_count",
                  "album_dir", "album_photo_count", "album_video_count",
                  "vision_cmd", "vision_cmd_exists", "card_path",
                  "version"):
            assert k in d, k


class TestCli:
    def test_send_asset_cli(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("REALPHOTO_ALBUM_DIR", _mk_album(tmp_path))
        assert bff.main(["send-asset", "-n", "2"]) == 0
        assert capsys.readouterr().out.count("MEDIA:") == 2

    def test_pool_status_cli(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("REALPHOTO_HOME", str(tmp_path / "rp"))
        assert bff.main(["pool-status"]) == 0

    def test_inspect_missing_file(self, capsys):
        assert bff.main(["inspect", "/nonexistent/x.jpg"]) == 1
