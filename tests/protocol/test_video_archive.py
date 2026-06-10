from pathlib import Path
from custom_components.dreame_a2_mower.archive.videos import VideoArchive, ArchivedVideo


def test_archive_video_stores_thumb_and_mp4(tmp_path: Path):
    arch = VideoArchive(tmp_path, retention=10)
    v = arch.archive(video_id="9", mp4=b"MP4DATA", thumb=b"\xff\xd8\xff\xd9", unix_ts=5, duration=18)
    assert v is not None and v.duration == 18
    assert (tmp_path / v.mp4_filename).read_bytes() == b"MP4DATA"
    assert (tmp_path / v.thumb_filename).exists()
    assert arch.has("9")
    assert arch.count == 1


def test_dedup_by_video_id(tmp_path: Path):
    arch = VideoArchive(tmp_path, retention=10)
    arch.archive(video_id="9", mp4=b"M", thumb=b"\xff\xd8\xff\xd9", unix_ts=5, duration=1)
    again = arch.archive(video_id="9", mp4=b"M2", thumb=b"\xff\xd8\xff\xd9", unix_ts=5, duration=1)
    assert again is None and arch.count == 1  # already have id 9


def test_retention_prunes_mp4_and_thumb_together(tmp_path: Path):
    arch = VideoArchive(tmp_path, retention=2)
    for i in range(4):
        arch.archive(video_id=str(i), mp4=b"M", thumb=b"\xff\xd8\xff\xd9", unix_ts=i, duration=1)
    assert arch.count == 2
    assert len(list(tmp_path.glob("*.mp4"))) == 2
    assert len(list(tmp_path.glob("*.jpg"))) == 2  # thumbs pruned with their mp4
    ids = {v.video_id for v in arch._index}
    assert ids == {"2", "3"}  # newest kept


def test_index_roundtrip(tmp_path: Path):
    arch = VideoArchive(tmp_path, retention=10)
    arch.archive(video_id="9", mp4=b"M", thumb=b"\xff\xd8\xff\xd9", unix_ts=5, duration=18)
    arch2 = VideoArchive(tmp_path, retention=10)
    arch2.load_index()
    assert arch2.has("9") and arch2.latest().duration == 18
