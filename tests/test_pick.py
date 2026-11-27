"""test_pick.py — 素材库直发（随机取、不重复、不生成、不验货）。

数据源是本地相簿目录（`REALPHOTO_ALBUM_DIR`）。
"""
import os

from realphoto import pick


def _mk_album(tmp_path, photos=5, videos=2):
    base = tmp_path / "album"
    for i in range(photos):
        (base / "photo").mkdir(parents=True, exist_ok=True)
        (base / "photo" / ("p%d.jpg" % i)).write_bytes(b"\xff\xd8\xff" + bytes([i]))
    for i in range(videos):
        (base / "video").mkdir(parents=True, exist_ok=True)
        (base / "video" / ("v%d.mp4" % i)).write_bytes(b"fake" + bytes([i]))
    return str(base)


class TestSendAsset:
    def test_pick_one_photo(self, tmp_path):
        base = _mk_album(tmp_path)
        files = pick.send_asset(album=base)
        assert len(files) == 1
        assert files[0].endswith(".jpg")
        assert os.sep + "photo" + os.sep in files[0]

    def test_pick_video(self, tmp_path):
        base = _mk_album(tmp_path)
        files = pick.send_asset(video=True, album=base)
        assert len(files) == 1 and files[0].endswith(".mp4")

    def test_pick_n_no_repeat(self, tmp_path):
        base = _mk_album(tmp_path, photos=6)
        files = pick.send_asset(n=3, album=base)
        assert len(files) == 3
        assert len(set(files)) == 3  # 不重复

    def test_n_capped_by_stock(self, tmp_path):
        base = _mk_album(tmp_path, photos=2)
        files = pick.send_asset(n=9, album=base)
        assert len(files) == 2  # 素材不足给全部

    def test_empty_dir_returns_empty(self, tmp_path):
        base = tmp_path / "nope"
        (base / "photo").mkdir(parents=True)
        assert pick.send_asset(album=str(base)) == []
        assert pick.send_asset(album=str(tmp_path / "missing")) == []


class TestParseN:
    def test_forms(self):
        assert pick.parse_n(["-n", "3"]) == 3
        assert pick.parse_n(["--count", "2"]) == 2
        assert pick.parse_n(["--count=4"]) == 4
        assert pick.parse_n(["--video"]) == 1
        assert pick.parse_n(["-n", "abc"]) == 1
        assert pick.parse_n(["-n", "99"]) == 9  # 上限
