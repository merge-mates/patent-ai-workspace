"""받은 사건 묶음을 OA 시점까지 자른 AI 입력으로 만든다 (#148, #150 1번).

받은 묶음 전체(정답 쪽)는 그대로 두고, OA 한 통마다 `<out>/<출원번호>/<발송번호>/`에 입력만 쓴다.
자르는 규칙 (날짜로 자르지 않는다. eval/retrieval/claim_history.py와 같은 줄 순서 규칙):
- 행정이력: 줄 순서로 대상 OA 줄까지 남긴다.
- 청구항이력: OA 앞 행정이력에 나온 접수번호의 줄만 남긴다. 행정이력에 없는 접수의 줄은 빼고 센다.
- 파일: 이름 끝 번호가 OA 앞 행정이력에 나왔거나 그 OA 발송번호인 것만 복사한다.
  번호가 없는 파일(공개공보·등록공보·결정본문)은 시점을 모르므로 뺀다 (F1 합격 기준 8).
- 예외: 출원서가 입력에 없는 사건(PCT 국내단계 등)은 공개공보 첫 쪽 "(43) 공개일자"가
  OA 발송일보다 앞설 때만 공개공보를 최초 명세서로 넣는다 (PRD 163줄, #150 3번 11/20 은진).
  이력에 공개 줄이 없어 이 한 경우만 날짜로 본다. 공개일을 못 읽으면 뺀다.

실행 (기본은 마른 실행, 아무것도 안 씀):
  uv run python scripts/split_cases_at_oa.py --src <받은 묶음 폴더> --out data/processed/cases
  ... --write --log work/split_cases_<날짜>.log   # 실제로 쓰기, 파일 이름 목록은 git 밖 로그로
  uv run python scripts/split_cases_at_oa.py --audit data/processed/cases   # 다 쓴 뒤 새는 것 세기
출력에는 원문 글자를 넣지 않는다. 대상 폴더가 하나라도 이미 있으면 아무것도 안 쓰고 멈춘다.
--src는 받은 묶음 폴더다. tune은 정답 쪽 `data/goldsets/tune/case_full/`에 있어 이 스크립트가
거기를 읽는다 (입력을 만드는 데이터 준비 단계라 예외. 앱 코드는 여전히 goldsets를 읽지 않는다).
"""

import argparse
import re
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

SEP = "¶"
OA_DOC_NAME = "의견제출통지서"
ADMIN = "행정이력.txt"
CLAIMS = "청구항이력.txt"
# 파일 이름 끝의 접수·발송번호: <출원번호>_<종류>_<번호>.<확장자>
NUMBER_RE = re.compile(r"_(\d{10,})\.[^.]+$")
PUB_SUFFIX = "_공개공보.pdf"
APPLICATION_MARK = "_출원서_"
# 공개공보 첫 쪽 서지의 (43) 공개일자. "국제공개일자"는 앞에 (43)이 없어 걸리지 않는다
PUB_DATE_RE = re.compile(r"\(43\)\s*공개일자\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일")

PubDateReader = Callable[[Path], str | None]


def parse_pub_date(text: str) -> str | None:
    """공개공보 첫 쪽 글자에서 (43) 공개일자를 YYYYMMDD로. 없으면 None."""
    m = PUB_DATE_RE.search(text)
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{y}{int(mo):02d}{int(d):02d}"


def read_pub_date(path: Path) -> str | None:
    """공개공보 PDF 첫 쪽에서 공개일을 읽는다. 못 읽으면 None (원문 글자는 내보내지 않음)."""
    import pdfplumber

    try:
        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                return None
            text = pdf.pages[0].extract_text() or ""
    except Exception:  # 깨진 PDF 등: 공개일 모름으로 빼고 경고로 남긴다
        return None
    return parse_pub_date(text)


@dataclass
class OaPlan:
    """OA 한 통의 입력 폴더에 쓸 것."""

    app_no: str
    oa_no: str
    src_dir: Path
    admin_lines: list[str]  # 머리글 포함, 원래 줄 그대로
    claim_lines: list[str]
    copy_files: list[str] = field(default_factory=list)
    dropped_files: list[tuple[str, str]] = field(default_factory=list)  # (파일 이름, 이유)
    dropped_claim_rows: int = 0  # OA 뒤 접수의 청구항 줄
    unmatched_claim_rows: int = 0  # 행정이력에 없는 접수의 청구항 줄

    @property
    def missing_oa_file(self) -> bool:
        """받은 묶음에 대상 OA 원문(`_<발송번호>.` 파일)이 없다."""
        return not any(_file_number(n) == self.oa_no for n in self.copy_files)

    @property
    def no_first_spec(self) -> bool:
        """최초 명세서(출원서·OA 전 공개공보)가 입력에 하나도 없다."""
        return not any(APPLICATION_MARK in n or n.endswith(PUB_SUFFIX) for n in self.copy_files)


def _lines(path: Path) -> list[str]:
    """줄 끝을 살린 채 읽는다 (자른 파일이 원래 줄과 글자가 같도록). BOM은 뗀다."""
    return path.read_text(encoding="utf-8-sig").splitlines(keepends=True)


def _cell(line: str, header: list[str], name: str) -> str:
    cells = line.rstrip("\r\n").split(SEP)
    i = header.index(name)
    return cells[i].strip() if i < len(cells) else ""


def _file_number(name: str) -> str | None:
    m = NUMBER_RE.search(name)
    return m.group(1) if m else None


def plan_case(case_dir: Path, pub_date: PubDateReader = read_pub_date) -> list[OaPlan]:
    """받은 사건 폴더 하나 → OA마다 자를 계획. OA가 없으면 빈 목록."""
    app_no = case_dir.name
    admin_path = case_dir / f"{app_no}_{ADMIN}"
    claim_path = case_dir / f"{app_no}_{CLAIMS}"
    if not admin_path.exists() or not claim_path.exists():
        raise FileNotFoundError(f"{case_dir.name}: 행정이력·청구항이력이 둘 다 있어야 한다")

    admin = _lines(admin_path)
    a_head = admin[0].rstrip("\r\n").split(SEP)
    a_rows = [ln for ln in admin[1:] if ln.strip()]
    claims = _lines(claim_path)
    c_head = claims[0].rstrip("\r\n").split(SEP)
    c_rows = [ln for ln in claims[1:] if ln.strip()]

    all_nos = {_cell(r, a_head, "접수발송번호") for r in a_rows}
    others = sorted(
        p.name
        for p in case_dir.iterdir()
        if p.is_file() and p.name not in {admin_path.name, claim_path.name}
    )

    plans = []
    for idx, row in enumerate(a_rows):
        if _cell(row, a_head, "접수발송서류명") != OA_DOC_NAME:
            continue
        oa_no = _cell(row, a_head, "접수발송번호")
        oa_date = _cell(row, a_head, "접수발송일자")
        # OA 앞(그 OA 줄 포함)에 나온 번호만 입력이 된다
        before = {_cell(r, a_head, "접수발송번호") for r in a_rows[: idx + 1]}
        plan = OaPlan(
            app_no=app_no,
            oa_no=oa_no,
            src_dir=case_dir,
            admin_lines=[admin[0], *a_rows[: idx + 1]],
            claim_lines=[claims[0]],
        )
        for r in c_rows:
            no = _cell(r, c_head, "접수발송번호")
            if no in before:
                plan.claim_lines.append(r)
            elif no in all_nos:
                plan.dropped_claim_rows += 1
            else:
                plan.unmatched_claim_rows += 1
        for name in others:
            no = _file_number(name)
            if no is None:
                plan.dropped_files.append((name, "시점 모름"))
            elif no in before:
                plan.copy_files.append(name)
            elif no in all_nos:
                plan.dropped_files.append((name, "OA 뒤"))
            else:
                plan.dropped_files.append((name, "이력에 없음"))
        _maybe_take_publication(plan, oa_date, pub_date)
        plans.append(plan)
    return plans


def _maybe_take_publication(plan: OaPlan, oa_date: str, pub_date: PubDateReader) -> None:
    """출원서가 입력에 없으면 OA 전 공개공보를 최초 명세서로 넣는다 (있으면 그대로 뺀다)."""
    if any(APPLICATION_MARK in n for n in plan.copy_files):
        return
    kept: list[tuple[str, str]] = []
    for name, why in plan.dropped_files:
        if not name.endswith(PUB_SUFFIX):
            kept.append((name, why))
            continue
        date = pub_date(plan.src_dir / name)
        if date is None:
            kept.append((name, "공개일 모름"))
        elif date < oa_date:  # YYYYMMDD 글자 비교. 같은 날은 앞뒤를 모르니 뺀다
            plan.copy_files.append(name)
        else:
            kept.append((name, "OA 뒤 공개"))
    plan.dropped_files = kept


def write_plan(plan: OaPlan, out_root: Path) -> Path:
    """`<out_root>/<출원번호>/<발송번호>/`에 쓴다. 이미 있으면 아무것도 안 쓰고 멈춘다."""
    target = out_root / plan.app_no / plan.oa_no
    if target.exists():
        raise FileExistsError(f"이미 있음, 덮어쓰지 않음: {target}")
    tmp = target.with_name(target.name + ".tmp")
    if tmp.exists():
        raise FileExistsError(f"이전 실행이 남긴 임시 폴더: {tmp}")
    tmp.mkdir(parents=True)
    # 임시 폴더에 다 쓴 뒤 이름을 바꾼다 (중간에 멈춰도 반쯤 쓴 입력 폴더가 남지 않게)
    (tmp / f"{plan.app_no}_{ADMIN}").write_text("".join(plan.admin_lines), encoding="utf-8")
    (tmp / f"{plan.app_no}_{CLAIMS}").write_text("".join(plan.claim_lines), encoding="utf-8")
    for name in plan.copy_files:
        shutil.copy2(plan.src_dir / name, tmp / name)
    tmp.rename(target)
    return target


def oa_dirs(out_root: Path) -> tuple[list[Path], list[Path]]:
    """`<출원번호>/<발송번호>/` 폴더(두 이름 모두 숫자)와 그 밖의 하위 폴더를 나눈다.

    쪽 텍스트 같은 다른 폴더가 `<출원번호>/` 아래 생겨도 OA 폴더로 세지 않게 한다 (#159).
    쓰다 멈춘 `<발송번호>.tmp`도 OA 폴더가 아니라 건너뛴 쪽에 든다.
    """
    found, skipped = [], []
    for p in sorted(p for p in out_root.glob("*/*") if p.is_dir()):
        (found if p.name.isdigit() and p.parent.name.isdigit() else skipped).append(p)
    return found, skipped


def audit(out_root: Path, pub_date: PubDateReader = read_pub_date) -> list[str]:
    """입력 폴더에서 OA 뒤 줄·시점 모를 파일을 찾는다. 문제 한 줄씩 (원문 글자 없음)."""
    problems = []
    for oa_dir in oa_dirs(out_root)[0]:
        app_no, oa_no = oa_dir.parent.name, oa_dir.name
        admin_path = oa_dir / f"{app_no}_{ADMIN}"
        if not admin_path.exists():
            problems.append(f"{app_no}/{oa_no}: 행정이력 없음")
            continue
        admin = _lines(admin_path)
        head = admin[0].rstrip("\r\n").split(SEP)
        rows = [ln for ln in admin[1:] if ln.strip()]
        if not rows or _cell(rows[-1], head, "접수발송번호") != oa_no:
            problems.append(f"{app_no}/{oa_no}: 행정이력 마지막 줄이 대상 OA가 아님")
        nos = {_cell(r, head, "접수발송번호") for r in rows}
        if not any(_file_number(p.name) == oa_no for p in oa_dir.iterdir()):
            problems.append(f"{app_no}/{oa_no}: 대상 OA 원문 없음")
        oa_date = _cell(rows[-1], head, "접수발송일자") if rows else ""
        has_application = any(APPLICATION_MARK in p.name for p in oa_dir.iterdir())
        claim_path = oa_dir / f"{app_no}_{CLAIMS}"
        if not claim_path.exists():
            problems.append(f"{app_no}/{oa_no}: 청구항이력 없음")
        else:
            claims = _lines(claim_path)
            c_head = claims[0].rstrip("\r\n").split(SEP)
            bad = sum(
                1 for r in claims[1:] if r.strip() and _cell(r, c_head, "접수발송번호") not in nos
            )
            if bad:
                problems.append(f"{app_no}/{oa_no}: 행정이력에 없는 접수의 청구항 줄 {bad}개")
        for p in sorted(oa_dir.iterdir()):
            if p.name in {admin_path.name, claim_path.name}:
                continue
            no = _file_number(p.name)
            if p.name.endswith(PUB_SUFFIX):
                if has_application:
                    problems.append(f"{app_no}/{oa_no}: 출원서가 있는데 공개공보도 있음")
                else:
                    date = pub_date(p)
                    if date is None or not date < oa_date:
                        problems.append(
                            f"{app_no}/{oa_no}: OA 뒤(또는 공개일 모름) 공개공보 {p.name}"
                        )
            elif no is None:
                problems.append(f"{app_no}/{oa_no}: 시점 모를 파일 {p.name}")
            elif no not in nos:
                problems.append(f"{app_no}/{oa_no}: 잘린 행정이력에 없는 번호의 파일 {p.name}")
    return problems


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", type=Path, help="받은 묶음 폴더 (<출원번호>/ 폴더들)")
    ap.add_argument("--out", type=Path, help="입력 폴더 뿌리 (예: data/processed/cases)")
    ap.add_argument("--write", action="store_true", help="실제로 쓴다 (없으면 마른 실행)")
    ap.add_argument("--log", type=Path, help="파일 이름 목록 로그 (git 밖, 예: work/...)")
    ap.add_argument("--audit", type=Path, help="이 입력 폴더를 검사만 한다")
    args = ap.parse_args(argv)

    # report는 봉인: 경로(링크를 따라간 실제 경로 포함)에 report가 있으면 열기 전에 멈춘다
    for path in (args.src, args.out, args.audit, args.log):
        if path and any(
            part == "report" or part.startswith("_report")
            for part in (*path.parts, *path.resolve().parts)
        ):
            print(f"봉인된 report 경로라 열지 않음: {path}", file=sys.stderr)
            return 1

    if args.audit:
        problems = audit(args.audit)
        found, skipped = oa_dirs(args.audit)
        n = len(found)
        for p in skipped:
            rel = p.relative_to(args.audit)
            print(f"경고: OA 폴더(<출원번호>/<발송번호>/)가 아니라 건너뜀: {rel}", file=sys.stderr)
        for line in problems:
            print(line)
        print(f"검사: OA 폴더 {n}개, 문제 {len(problems)}건")
        if n == 0:
            print("경고: 검사할 OA 폴더가 없음", file=sys.stderr)
            return 1
        return 1 if problems else 0

    if not args.src or not args.out:
        ap.error("--src와 --out이 필요하다 (검사만 하려면 --audit)")
    dirs = sorted(p for p in args.src.iterdir() if p.is_dir()) if args.src.is_dir() else []
    # 사건 폴더는 출원번호(숫자)만. `_report/` 같은 묶음 폴더는 열지 않고 건너뛴다 (report는 봉인)
    cases = [p for p in dirs if p.name.isdigit()]
    for p in dirs:
        if not p.name.isdigit():
            print(f"경고: 출원번호 폴더가 아니라 건너뜀(열지 않음): {p.name}", file=sys.stderr)
    if not cases:
        print(f"경고: 사건 폴더가 없음: {args.src}", file=sys.stderr)
        return 1

    plans: list[OaPlan] = []
    no_oa = 0
    for case in cases:
        found = plan_case(case, pub_date=read_pub_date)
        if not found:
            no_oa += 1
            print(
                f"경고: OA 없음 (행정이력에 {OA_DOC_NAME} 줄이 없다): {case.name}", file=sys.stderr
            )
        plans.extend(found)
    if not plans:
        print("경고: 자를 OA가 하나도 없음", file=sys.stderr)
        return 1

    reasons: dict[str, int] = {}
    for p in plans:
        for _, why in p.dropped_files:
            reasons[why] = reasons.get(why, 0) + 1
    print(
        f"{'쓰기' if args.write else '마른 실행'}: 사건 {len(cases)}건, OA {len(plans)}통, "
        f"OA 없음 {no_oa}건, "
        f"입력 파일 {sum(len(p.copy_files) for p in plans)}개(이력 두 파일 빼고), "
        f"뺀 파일 {sum(reasons.values())}개 {reasons}, "
        f"뺀 청구항 줄 {sum(p.dropped_claim_rows for p in plans)}개, "
        f"행정이력에 없는 접수의 청구항 줄 {sum(p.unmatched_claim_rows for p in plans)}개"
    )
    if reasons.get("공개일 모름"):
        print("경고: 출원서 없는 사건의 공개공보 공개일을 못 읽어 입력에서 뺐다", file=sys.stderr)
    if any(p.unmatched_claim_rows for p in plans):
        print("경고: 행정이력에 없는 접수의 청구항 줄은 입력에서 뺐다", file=sys.stderr)
    for p in plans:
        if p.no_first_spec:
            print(f"경고: 최초 명세서가 없는 입력: {p.app_no}/{p.oa_no}", file=sys.stderr)
    missing = [f"{p.app_no}/{p.oa_no}" for p in plans if p.missing_oa_file]
    if missing:
        # OA 원문 없는 입력 폴더가 "성공"으로 남지 않게 아무것도 안 쓰고 실패로 끝낸다
        print(f"대상 OA 원문 없음 {len(missing)}통, 아무것도 안 씀: {missing}", file=sys.stderr)
        return 1

    if args.write:
        # 쓰기 전에 대상을 한꺼번에 본다 (일부만 쓰고 멈추면 다음 실행이 꼬인다)
        taken = [
            f"{p.app_no}/{p.oa_no}"
            for p in plans
            if (args.out / p.app_no / p.oa_no).exists()
            or (args.out / p.app_no / f"{p.oa_no}.tmp").exists()
        ]
        if taken:
            print(f"이미 있는 대상 {len(taken)}개, 아무것도 안 씀: {taken}", file=sys.stderr)
            return 1
    log = None
    if args.log:
        args.log.parent.mkdir(parents=True, exist_ok=True)
        log = args.log.open("x", encoding="utf-8")  # 이미 있으면 멈춤 (쓰기 전에 연다)
    if args.write:
        for p in plans:
            write_plan(p, args.out)
    if log:
        with log as f:
            for p in plans:
                f.write(f"## {p.app_no}/{p.oa_no}\n")
                f.writelines(f"입력 {n}\n" for n in p.copy_files)
                f.writelines(f"뺌({why}) {n}\n" for n, why in p.dropped_files)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
