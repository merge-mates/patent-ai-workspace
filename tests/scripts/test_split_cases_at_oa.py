"""사건 자료를 OA 시점 입력으로 자르는 스크립트 테스트 (#148, #150 1번).

번호·글자는 모두 지어낸 값이다.
"""

from pathlib import Path

import pytest

from eval.retrieval.claim_history import claims_at_oa
from scripts.split_cases_at_oa import audit, main, parse_pub_date, plan_case, write_plan

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


def _make_case(
    root: Path, *, two_oas: bool = False, ghost_claim: bool = False, application_file: bool = True
) -> Path:
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
    if not application_file:  # 출원서 파일이 없는 사건 (PCT 국내단계처럼)
        files.remove(f"{APP}_출원서_{APPLY}.pdf")
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
    assert any("마지막 줄이 대상 OA가 아님" in p for p in problems)
    assert any("시점 모를 파일" in p for p in problems)
    assert any("행정이력에 없는 번호의 파일" in p for p in problems)


def test_case_without_oa_warns_and_fails_when_nothing_to_cut(tmp_path, capsys):
    d = tmp_path / "src" / APP
    d.mkdir(parents=True)
    _write(d / f"{APP}_행정이력.txt", [ADMIN_HEAD, _admin_row(APPLY, "20990101", "특허출원서")])
    _write(d / f"{APP}_청구항이력.txt", [CLAIM_HEAD])
    code = main(["--src", str(tmp_path / "src"), "--out", str(tmp_path / "out")])
    assert code == 1
    assert "OA 없음" in capsys.readouterr().err


def test_non_case_folders_like_report_are_skipped_unopened(tmp_path, capsys):
    _make_case(tmp_path / "src")
    sealed = tmp_path / "src" / "_report" / APP
    sealed.mkdir(parents=True)  # 이력 파일이 없어 열면 오류가 난다
    out = tmp_path / "out"
    code = main(["--src", str(tmp_path / "src"), "--out", str(out), "--write"])
    assert code == 0
    assert [p.name for p in out.iterdir()] == [APP]
    assert "_report" in capsys.readouterr().err


def test_cut_history_gives_same_claims_at_oa_as_full(tmp_path):
    case = _make_case(tmp_path / "src", two_oas=True, ghost_claim=True)
    out = tmp_path / "out"
    for plan in plan_case(case):
        d = write_plan(plan, out)
        full = claims_at_oa(
            case / f"{APP}_청구항이력.txt", case / f"{APP}_행정이력.txt", plan.oa_no
        )
        cut = claims_at_oa(d / f"{APP}_청구항이력.txt", d / f"{APP}_행정이력.txt", plan.oa_no)
        assert cut == full and cut


def test_write_checks_all_targets_first_and_writes_nothing(tmp_path, capsys):
    _make_case(tmp_path / "src", two_oas=True)
    out = tmp_path / "out"
    (out / APP / OA2).mkdir(parents=True)
    log = tmp_path / "work" / "split.log"
    code = main(["--src", str(tmp_path / "src"), "--out", str(out), "--write", "--log", str(log)])
    assert code == 1
    assert not (out / APP / OA1).exists()
    assert not log.exists()
    assert "이미 있는 대상 1개" in capsys.readouterr().err


def test_audit_counts_missing_claim_history(tmp_path):
    (plan,) = plan_case(_make_case(tmp_path / "src"))
    d = write_plan(plan, tmp_path / "out")
    (d / f"{APP}_청구항이력.txt").unlink()
    assert audit(tmp_path / "out") == [f"{APP}/{OA1}: 청구항이력 없음"]


# --- 출원서 없는 사건의 공개공보 (#150 3번, 11/20 은진) ---
# PRD 163줄대로 OA 전 공개공보를 최초 명세서로 넣는다
PUB = f"{APP}_공개공보.pdf"


def _pub_date(date: str | None):
    """공개일 읽기 대신 쓰는 가짜 (공개공보 파일만 읽는지도 본다)."""

    def read(path: Path) -> str | None:
        assert path.name == PUB
        return date

    return read


def test_parse_pub_date_reads_43_field():
    text = (
        "(19) 대한민국특허청(KR)\n"
        "(12) 공개특허공보(A) (43) 공개일자 2099년01월15일\n"
        "국제공개일자 2098년04월05일"
    )
    assert parse_pub_date(text) == "20990115"
    assert parse_pub_date("공개일자 없음") is None


def test_no_application_file_takes_publication_before_oa(tmp_path):
    case = _make_case(tmp_path / "src", application_file=False)
    (plan,) = plan_case(case, pub_date=_pub_date("20990115"))  # OA1 발송 20990201 전
    assert PUB in plan.copy_files
    d = write_plan(plan, tmp_path / "out")
    assert (d / PUB).exists()
    assert audit(tmp_path / "out", pub_date=_pub_date("20990115")) == []


def test_no_application_file_drops_publication_after_oa(tmp_path):
    case = _make_case(tmp_path / "src", application_file=False)
    (plan,) = plan_case(case, pub_date=_pub_date("20990201"))  # OA 발송일과 같은 날도 뺀다
    assert dict(plan.dropped_files)[PUB] == "OA 뒤 공개"


def test_no_application_file_drops_publication_with_unreadable_date(tmp_path):
    case = _make_case(tmp_path / "src", application_file=False)
    (plan,) = plan_case(case, pub_date=_pub_date(None))
    assert dict(plan.dropped_files)[PUB] == "공개일 모름"


def test_publication_stays_out_when_application_file_is_input(tmp_path):
    def never(path: Path) -> str | None:
        raise AssertionError("출원서가 있으면 공개공보를 열지 않는다")

    (plan,) = plan_case(_make_case(tmp_path / "src"), pub_date=never)
    assert dict(plan.dropped_files)[PUB] == "시점 모름"


def test_audit_flags_publication_next_to_application_or_after_oa(tmp_path):
    (plan,) = plan_case(_make_case(tmp_path / "src"))
    d = write_plan(plan, tmp_path / "out")
    (d / PUB).write_bytes(b"x")  # 출원서가 있는데 공개공보도 들어감
    assert audit(tmp_path / "out", pub_date=_pub_date("20990115")) == [
        f"{APP}/{OA1}: 출원서가 있는데 공개공보도 있음"
    ]
    (d / f"{APP}_출원서_{APPLY}.pdf").unlink()
    assert audit(tmp_path / "out", pub_date=_pub_date("20990301")) == [
        f"{APP}/{OA1}: OA 뒤(또는 공개일 모름) 공개공보 {PUB}"
    ]
