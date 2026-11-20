"""사건 자료를 OA 시점 입력으로 자르는 스크립트 테스트 (#148, #150 1번).

번호·글자는 모두 지어낸 값이다.
"""

from pathlib import Path

import pytest

from scripts.split_cases_at_oa import audit, main, plan_case, write_plan

SEP = "¶"
APP = "1020990000001"
ADMIN_HEAD = SEP.join(
    [
        "출원번호",
        "접수발송번호",
        "접수발송일자",
        "접수발송서류명",
        "접수발송서류영문명",
        "처리상태",
        "처리상태영문명",
        "단계",
        "심판번호",
        "등록번호",
    ]
)
CLAIM_HEAD = SEP.join(
    [
        "출원번호",
        "접수발송일련번호",
        "접수발송번호",
        "청구항번호",
        "변경구분코드",
        "변경구분명",
        "청구항",
        "변동대상접수문서번호",
        "변동청구항",
    ]
)

APPLY = "112099000000001"  # 출원서
EXAM = "112099000000002"  # 심사청구
OA1 = "952099000000011"
AMEND1 = "112099000000021"  # OA1 뒤 보정서
OPINION1 = "112099000000022"  # OA1 뒤 의견서
OA2 = "952099000000031"
AMEND2 = "112099000000041"
GRANT = "952099000000051"  # 등록결정
GHOST = "112099000000099"  # 행정이력에 없는 접수


def _admin_row(no: str, date: str, name: str) -> str:
    return SEP.join([APP, no, date, name, " ", "수리", "Accepted", "출원", " ", " "])


def _claim_row(seq: int, no: str, claim: int, kind: str, text: str) -> str:
    return SEP.join([APP, str(seq), no, str(claim), "I", kind, text, " ", " "])


def _write(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_case(root: Path, *, two_oas: bool = False, ghost_claim: bool = False) -> Path:
    """지어낸 받은 묶음 하나. two_oas면 OA1 → 보정 → OA2 → 보정 → 등록결정."""
    d = root / APP
    d.mkdir(parents=True)
    admin = [
        ADMIN_HEAD,
        _admin_row(APPLY, "20990101", "[특허출원]특허출원서"),
        _admin_row(EXAM, "20990102", "[심사청구]심사청구서"),
        _admin_row(OA1, "20990201", "의견제출통지서"),
        _admin_row(AMEND1, "20990301", "[명세서등 보정]보정서"),
        _admin_row(OPINION1, "20990301", "[거절이유 등 통지에 따른 의견]의견(답변, 소명)서"),
    ]
    claims = [
        CLAIM_HEAD,
        _claim_row(1, APPLY, 1, "신규", "처음 청구항 1"),
        _claim_row(1, APPLY, 2, "신규", "처음 청구항 2"),
        _claim_row(2, AMEND1, 1, "수정", "첫 보정 청구항 1"),
    ]
    files = [
        f"{APP}_출원서_{APPLY}.pdf",
        f"{APP}_OA_{OA1}.pdf",
        f"{APP}_보정서_{AMEND1}.pdf",
        f"{APP}_의견서_{OPINION1}.pdf",
        f"{APP}_공개공보.pdf",
        f"{APP}_등록공보.pdf",
        f"{APP}_결정_{GRANT}.pdf",
        f"{APP}_결정본문.txt",
    ]
    if two_oas:
        admin += [
            _admin_row(OA2, "20990401", "의견제출통지서"),
            _admin_row(AMEND2, "20990501", "[명세서등 보정]보정서"),
        ]
        claims.append(_claim_row(3, AMEND2, 2, "삭제", " "))
        files += [f"{APP}_OA_{OA2}.pdf", f"{APP}_보정서_{AMEND2}.pdf"]
    admin.append(_admin_row(GRANT, "20990601", "등록결정서"))
    if ghost_claim:
        claims.append(_claim_row(9, GHOST, 1, "수정", "이력에 없는 접수"))
    _write(d / f"{APP}_행정이력.txt", admin)
    _write(d / f"{APP}_청구항이력.txt", claims)
    for name in files:
        (d / name).write_bytes(b"x")
    return d


def _numbers(path: Path, col: int) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()[1:]
    return [ln.split(SEP)[col] for ln in lines if ln.strip()]


def test_one_oa_keeps_only_material_up_to_oa(tmp_path):
    case = _make_case(tmp_path / "src")
    (plan,) = plan_case(case)
    out = tmp_path / "out"
    write_plan(plan, out)

    oa_dir = out / APP / OA1
    assert sorted(p.name for p in oa_dir.iterdir()) == sorted(
        [
            f"{APP}_출원서_{APPLY}.pdf",
            f"{APP}_OA_{OA1}.pdf",
            f"{APP}_행정이력.txt",
            f"{APP}_청구항이력.txt",
        ]
    )
    # 행정이력은 OA 줄까지, 청구항이력은 OA 앞 접수의 줄만
    assert _numbers(oa_dir / f"{APP}_행정이력.txt", 1) == [APPLY, EXAM, OA1]
    assert _numbers(oa_dir / f"{APP}_청구항이력.txt", 2) == [APPLY, APPLY]
    # 머리글은 그대로
    head = (oa_dir / f"{APP}_청구항이력.txt").read_text(encoding="utf-8").splitlines()[0]
    assert head == CLAIM_HEAD


def test_one_oa_reports_why_files_were_left_out(tmp_path):
    (plan,) = plan_case(_make_case(tmp_path / "src"))
    reasons = dict(plan.dropped_files)
    assert reasons[f"{APP}_보정서_{AMEND1}.pdf"] == "OA 뒤"
    assert reasons[f"{APP}_의견서_{OPINION1}.pdf"] == "OA 뒤"
    assert reasons[f"{APP}_결정_{GRANT}.pdf"] == "OA 뒤"
    assert reasons[f"{APP}_공개공보.pdf"] == "시점 모름"
    assert reasons[f"{APP}_등록공보.pdf"] == "시점 모름"
    assert reasons[f"{APP}_결정본문.txt"] == "시점 모름"
    assert plan.dropped_claim_rows == 1  # 첫 보정 청구항 1


def test_two_oas_get_separate_folders(tmp_path):
    case = _make_case(tmp_path / "src", two_oas=True)
    plans = plan_case(case)
    assert [p.oa_no for p in plans] == [OA1, OA2]
    out = tmp_path / "out"
    for p in plans:
        write_plan(p, out)

    first = sorted(p.name for p in (out / APP / OA1).iterdir())
    assert f"{APP}_보정서_{AMEND1}.pdf" not in first
    assert f"{APP}_OA_{OA2}.pdf" not in first

    second_dir = out / APP / OA2
    second = sorted(p.name for p in second_dir.iterdir())
    for name in [
        f"{APP}_OA_{OA1}.pdf",
        f"{APP}_OA_{OA2}.pdf",
        f"{APP}_보정서_{AMEND1}.pdf",
        f"{APP}_의견서_{OPINION1}.pdf",
    ]:
        assert name in second
    assert f"{APP}_보정서_{AMEND2}.pdf" not in second
    assert _numbers(second_dir / f"{APP}_행정이력.txt", 1)[-1] == OA2
    assert _numbers(second_dir / f"{APP}_청구항이력.txt", 2) == [APPLY, APPLY, AMEND1]


def test_claim_row_of_unknown_receipt_is_dropped_and_counted(tmp_path):
    (plan,) = plan_case(_make_case(tmp_path / "src", ghost_claim=True))
    assert plan.unmatched_claim_rows == 1
    assert all(GHOST not in ln for ln in plan.claim_lines)


def test_write_stops_if_target_exists(tmp_path):
    (plan,) = plan_case(_make_case(tmp_path / "src"))
    out = tmp_path / "out"
    (out / APP / OA1).mkdir(parents=True)
    with pytest.raises(FileExistsError):
        write_plan(plan, out)
    assert list((out / APP / OA1).iterdir()) == []


def test_dry_run_is_default_and_writes_nothing(tmp_path, capsys):
    _make_case(tmp_path / "src")
    out = tmp_path / "out"
    code = main(["--src", str(tmp_path / "src"), "--out", str(out)])
    assert code == 0
    assert not out.exists()
    assert "마른 실행" in capsys.readouterr().out


def test_write_then_audit_is_clean(tmp_path):
    _make_case(tmp_path / "src", two_oas=True)
    out = tmp_path / "out"
    log = tmp_path / "work" / "split.log"
    code = main(["--src", str(tmp_path / "src"), "--out", str(out), "--write", "--log", str(log)])
    assert code == 0
    assert audit(out) == []
    assert f"{APP}_등록공보.pdf" in log.read_text(encoding="utf-8")


def test_audit_finds_leaked_material(tmp_path):
    (plan,) = plan_case(_make_case(tmp_path / "src"))
    out = tmp_path / "out"
    write_plan(plan, out)
    oa_dir = out / APP / OA1
    (oa_dir / f"{APP}_등록공보.pdf").write_bytes(b"x")
    (oa_dir / f"{APP}_보정서_{AMEND1}.pdf").write_bytes(b"x")
    with (oa_dir / f"{APP}_행정이력.txt").open("a", encoding="utf-8") as f:
        f.write(_admin_row(GRANT, "20990601", "등록결정서") + "\n")
    problems = audit(out)
    assert len(problems) == 3


def test_case_without_oa_warns_and_fails_when_nothing_to_cut(tmp_path, capsys):
    d = tmp_path / "src" / APP
    d.mkdir(parents=True)
    _write(d / f"{APP}_행정이력.txt", [ADMIN_HEAD, _admin_row(APPLY, "20990101", "특허출원서")])
    _write(d / f"{APP}_청구항이력.txt", [CLAIM_HEAD])
    code = main(["--src", str(tmp_path / "src"), "--out", str(tmp_path / "out")])
    assert code == 1
    assert "OA 없음" in capsys.readouterr().err
