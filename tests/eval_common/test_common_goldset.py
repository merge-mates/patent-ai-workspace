"""정답 세트 버전 검사와 정답 경로 (eval/common/goldset.py)."""

import pytest

from eval.common.errors import EvalError
from eval.common.goldset import check_goldset_version, gold_path


def test_VERSION이_설정과_같으면_통과(tmp_path):
    (tmp_path / "VERSION").write_text("1\n")
    check_goldset_version(tmp_path, 1)


def test_VERSION_파일이_없으면_실패(tmp_path):
    with pytest.raises(EvalError, match="VERSION 파일이 없다"):
        check_goldset_version(tmp_path, 1)


def test_VERSION이_정수가_아니면_실패(tmp_path):
    (tmp_path / "VERSION").write_text("tune-f1-v0\n")
    with pytest.raises(EvalError, match="정수가 아니다"):
        check_goldset_version(tmp_path, 1)


def test_VERSION이_설정과_다르면_두_값을_말한다(tmp_path):
    (tmp_path / "VERSION").write_text("2\n")
    with pytest.raises(EvalError, match="goldset_version이 다르다: 설정 1, VERSION 2"):
        check_goldset_version(tmp_path, 1)


def test_정답_경로는_세트_폴더_아래다(tmp_path):
    assert gold_path(tmp_path, "tune", "f1/a.json") == tmp_path / "tune" / "f1" / "a.json"


@pytest.mark.parametrize("bad", ["../a.json", "/etc/passwd", "f1/../../x.json"])
def test_정답_경로가_세트_폴더_밖이면_실패(tmp_path, bad):
    with pytest.raises(EvalError, match="gold 경로"):
        gold_path(tmp_path, "tune", bad)
