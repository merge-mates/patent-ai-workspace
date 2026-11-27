# ruff: noqa: E501  (git 밖 자료를 다루는 실험 실행기)
"""보정안을 의견서 입력으로 넣은 초안을 만들고 재아 채점기로 채점한다 (모델 호출은 구독 claude -p).

단계: setup → freeze → draft → prep → response → support → coverage → report
재아 채점기(m3-i2-oa-draft-judge-pilot)의 프롬프트·입력 준비·출력 검사를 그대로 부른다.
사건 번호 대응(cases.json)과 모든 출력은 git 밖 --work 폴더에 둔다.
"""

import argparse
import json
import os
import re
import string
import subprocess
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
JUDGE = HERE.parent / "m3-i2-oa-draft-judge-pilot"
sys.path.insert(0, str(JUDGE))
import judge as J  # noqa: E402
import sources as S  # noqa: E402
from freeze_issues import freeze  # noqa: E402

ARMS = ("direction", "amend", "amend_check")
WRITER = ("claude-haiku-5-5", "medium")  # 서비스 F4 의견서와 같은 모델·노력
GRADER = ("claude-opus-5-5", "high")
SYSTEM = "사용자 글에 있는 지시대로만 답한다. 요청한 JSON 하나만 출력한다."


def ask(model, effort, prompt, system=None):
    """구독으로 한 번 부른다. API 키를 빼고, 빈 폴더에서, 도구 없이."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("ANTHROPIC_")}
    for wait in (60, 180, None):
        with tempfile.TemporaryDirectory(prefix="sub_") as d:
            cmd = ["claude", "-p", "--safe-mode", "--tools", "", "--strict-mcp-config"]
            cmd += ["--no-session-persistence", "--model", model, "--effort", effort]
            cmd += ["--system-prompt", system or SYSTEM, "--output-format", "json"]
            r = subprocess.run(
                cmd, input=prompt, text=True, capture_output=True, cwd=d, env=env, timeout=1800
            )
        try:
            x = json.loads(r.stdout)
        except ValueError:
            raise RuntimeError(
                f"claude 출력이 JSON이 아님: {(r.stdout or r.stderr)[:200]}"
            ) from None
        if x.get("is_error") or x.get("subtype") != "success":
            msg = str(x.get("result"))[:200]
            if wait and any(w in msg for w in ("529", "Overloaded", "500 ", "502", "503", "504")):
                time.sleep(wait)
                continue
            raise RuntimeError(f"구독 호출 실패: {msg}")
        if model not in x.get("modelUsage", {}):
            raise RuntimeError(f"다른 모델이 답함: {set(x.get('modelUsage', {}))}")
        return x["result"], x["usage"]


def parse(text):
    return json.loads(text[text.index("{") : text.rindex("}") + 1])


def call(dest, who, prompt, check):
    """검사를 통과한 답만 저장한다. 같은 입력이면 다시 부르지 않는다. 세 번 다 떨어지면 멈춘다."""
    key = sha256(json.dumps([who, prompt], ensure_ascii=False).encode()).hexdigest()
    if dest.exists():
        old = J.read_json(dest)
        if old["key"] != key:
            raise ValueError(f"입력이 바뀜, 새 폴더를 쓴다: {dest}")
        if old["parsed"] is not None:
            return old["parsed"]
    note, tries = "", []
    for _ in range(3):
        text, usage = ask(*who, prompt + note)
        try:
            out = parse(text)
            check(out)
            tries.append({"ok": True, "usage": usage})
            J.write_json(dest, {"key": key, "model": who, "parsed": out, "attempts": tries})
            print("OK", dest.parent.name, dest.stem, flush=True)
            return out
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            tries.append({"error": f"{type(e).__name__}: {e}", "usage": usage, "text": text})
            note = f"\n직전 출력 검증 오류를 바로잡아 JSON 하나를 정확히 다시 출력한다. {e}"
    J.write_json(dest, {"key": key, "model": who, "parsed": None, "attempts": tries})
    raise RuntimeError(f"{dest.stem}: 세 번 다 검사에 떨어짐: {[t['error'] for t in tries]}")


def fan(fn, items, workers):
    """하나가 실패해도 나머지는 마치고, 끝에 실패를 모아 알린다."""
    bad = []

    def safe(x):
        try:
            fn(x)
        except Exception as e:  # noqa: BLE001
            bad.append((str(x), f"{type(e).__name__}: {e}"))
            print("FAILED", x, e, flush=True)

    with ThreadPoolExecutor(workers) as p:
        list(p.map(safe, items))
    if bad:
        sys.exit(f"실패 {len(bad)}건: {bad}")


def spec_rows(path):
    """출원서의 【0012】 문단. 재아 근거 목록의 명세서 조각 모양으로 낸다."""
    rows, cur = [], None
    for page, lines in enumerate(S.pdf_pages(path), 1):
        for line in map(str.strip, lines):
            m = re.match(r"^【(\d{4})】\s*(.*)", line)
            if m:
                cur = {
                    "page": page,
                    "chunk": {"location": {"kind": "paragraph", "label": f"[{m[1]}]"}},
                }
                cur["chunk"]["text"] = m[2]
                rows.append(cur)
            elif line.startswith("【"):
                cur = None  # 다른 제목(청구범위 등)
            elif cur:
                cur["chunk"]["text"] += " " + line
    return rows


_korean_source = S.patent_source


def any_source(path, source):
    """재아 근거 목록은 한글 공보만 읽는다. 하나도 못 읽은 문헌(미국·논문)은 [0000] 문단과 쪽으로 읽는다."""
    found = _korean_source(path, source)
    if found:
        return found
    raw = subprocess.run(["pdftotext", str(path), "-"], capture_output=True, check=True).stdout
    pages = raw.decode("utf-8", "replace").split("\f")
    groups, cur = {}, None
    for n, text in enumerate(pages, 1):
        for piece in re.split(r"(?m)(^\[?0\d{3}[\].]? (?=[A-Z]))", text):
            # 미국 공보 글자층은 [0019]가 "0019."처럼 깨져 있어 줄 머리 번호로 읽는다
            if m := re.fullmatch(r"\[?(0\d{3})[\].]? ", piece):
                cur = f"[{m[1]}]"
            elif cur:
                old = groups.setdefault(cur, ["", []])
                old[0] += " " + piece
                old[1].append(n)
    rows = [S.entry(source, k, t, sorted(set(p))) for k, (t, p) in groups.items()]
    rows += [S.entry(source, f"{n}쪽", t, [n]) for n, t in enumerate(pages, 1) if t.strip()]
    if not rows:
        raise ValueError(f"글자를 못 읽은 문헌: {path.name}")
    return rows


S.patent_source = any_source


class Run:
    def __init__(self, a):
        self.repo, self.work = a.repo.resolve(), a.work.resolve()
        self.exp = self.repo / "work/agentic_rag_1123"
        self.root, self.run, self.base = (self.work / x for x in ("root", "run", "baseline"))
        self.cases = J.read_json(self.work / "cases.json")  # [{case, key}]
        self.workers, self.rep, self.sub = a.workers, a.rep, a.sub
        self.arms = a.arms.split(",")
        self.plan_dir = a.plan_dir

    def inputs(self, c):
        return J.read_json(self.exp / f"pattern_exp3/inputs_final/{c['key']}.json")

    def plan(self, c):
        """E 추천 1번 안. 글이 정말 달라진 항만 남긴다. --plan-dir를 주면 그 폴더의 <case>/plan.json을 쓴다."""
        if self.plan_dir:
            return J.read_json(self.plan_dir / c["case"] / "plan.json")
        (f,) = (self.exp / "pattern_exp3/out_sub/ours3").glob(f"E_{c['key']}_*.json")
        d = J.read_json(f)["drafts"][0]
        old = self.old_claims(c)
        keep = []
        for q in d["amended"]:
            before = old.get(q["claim"], "")
            same = re.sub(r"\s", "", q["text"]) == re.sub(r"\s", "", before)
            if q["action"] == "amend" and same:
                print(f"{c['case']} 청구항 {q['claim']}: 글이 그대로라 보정에서 뺌", flush=True)
                continue
            keep.append({**q, "before": before})
        if not keep:
            raise ValueError(f"{c['case']}: 보정한 항이 0개")
        return {"strategy": d["strategy"], "amended": sorted(keep, key=lambda q: q["claim"])}

    def old_claims(self, c):
        parts = re.split(r"【청구항 (\d+)】\n", self.inputs(c)["claims"])
        return {int(n): t.strip() for n, t in zip(parts[1::2], parts[2::2], strict=True)}

    def f1(self, c):
        return J.read_json(self.work / "f1" / f"{c['case']}.json")

    def cited_path(self, c, cit):
        folder = self.repo / "data/raw/cited_v2" / c["key"].split("_")[0]
        hits = [p for p in folder.glob("*.pdf") if p.stem == cit["key"]]
        if not hits and cit["key"].startswith("NPL"):
            n = int(cit["label"].removeprefix("D"))
            hits = list(folder.glob(f"NPL{n}_*.pdf"))
        (path,) = hits
        return path

    # ---- setup: F1 자료, manifest, 명세서 조각, 근거 원문 ----
    def setup(self):
        sys.path.insert(0, str(self.exp / "pattern_exp"))
        import common as C

        all_f1 = C.f1_data()
        manifest = []
        for c in self.cases:
            app, disp = c["key"].split("_")
            J.write_json(self.work / "f1" / f"{c['case']}.json", all_f1[c["key"]])
            (oa,) = (self.repo / "data/processed/cases" / app / disp).glob("*_OA_*.pdf")
            manifest.append(
                {
                    "case": c["case"],
                    "oa_pdf": str(oa.relative_to(self.repo)),
                    "oa_pdf_sha256": sha256(oa.read_bytes()).hexdigest(),
                }
            )
            (spec,) = oa.parent.glob("*출원서*.pdf")
            rows = spec_rows(spec)
            if not rows:
                raise ValueError(f"{c['case']}: 명세서 문단이 0개")
            folder = self.base / "spec-retrieval" / c["case"]
            folder.mkdir(parents=True, exist_ok=True)
            J.write_rows(folder / "paragraphs.jsonl", rows)
            # 심사관이 짚은 위치 + 요약 + 청구항 1만 의견서 입력으로 준다 (세 조건 같음)
            blocks = []
            for cit in self.f1(c)["citations"]:
                src = S.patent_source(self.cited_path(c, cit), cit["label"])
                want = self.locations(c, cit["label"])
                picked = [e for e in src if e["location"] in want]
                if len([e for e in picked if e["location"] not in ("요약", "청구항 1")]) == 0:
                    picked += [e for e in src if e["location"].endswith("쪽")][:6]
                text, total = [], 0
                for e in picked:
                    total += len(e["text"])
                    if total > 30000:
                        print(f"{c['case']} {cit['label']}: 발췌 3만 자에서 자름", flush=True)
                        break
                    text.append(f"{e['location']} {e['text']}")
                found = {e["location"] for e in picked}
                print(
                    c["case"], cit["label"], "발췌", len(text), "못 찾음", sorted(want - found)[:12]
                )
                n = cit["label"].removeprefix("D")
                blocks.append(f"[인용발명 {n}] {cit['text']}\n" + "\n".join(text))
            J.write_json(self.work / "cited" / f"{c['case']}.json", "\n\n".join(blocks))
        J.write_json(self.base / "manifest.json", {"cases": manifest})

    def locations(self, c, label):
        want = {"요약", "청구항 1"}
        for row in self.f1(c)["claim_rows"]:
            for loc in row.get("locations", {}).get(label, []):
                nums = list(map(int, re.findall(r"\[(\d{4})\]", loc)))
                if nums:
                    last = nums[1] if len(nums) > 1 else nums[0]
                    want |= {f"[{n:04}]" for n in range(nums[0], last + 1)}
                elif m := re.fullmatch(r"청구항 (\d+)(?:-(\d+))?", loc):
                    want |= {f"청구항 {n}" for n in range(int(m[1]), int(m[2] or m[1]) + 1)}
        return want

    # ---- freeze: 논점 고정 ----
    def freeze(self):
        target = self.root / "01-source-freeze"
        target.mkdir(parents=True, exist_ok=True)
        if (target / "freeze.json").exists():
            sys.exit("이미 고정함. 다시 만들지 않는다")
        if list((self.work / "drafts").glob("*.json")):
            sys.exit("초안을 먼저 만들었다. 논점은 초안 전에 고정해야 한다")
        tmpl = (HERE / "prompts/freeze.md").read_text(encoding="utf-8")
        manifest = {m["case"]: m for m in J.read_json(self.base / "manifest.json")["cases"]}

        def one(c):
            pages = [
                [line.strip() for line in lines if line.strip()]
                for lines in S.pdf_pages(self.repo / manifest[c["case"]]["oa_pdf"])
            ]
            rej = [
                {"no": r["no"], "kind": r["kind"], "claims": r["targets"]["value"]}
                for r in self.f1(c)["rejections"]
            ]
            body = "\n".join(
                f"[{p}쪽]\n" + "\n".join(f"{n}: {t}" for n, t in enumerate(lines, 1))
                for p, lines in enumerate(pages, 1)
            )

            def check(x):
                if not x["issues"]:
                    raise ValueError("논점이 0개")
                nos = {r["no"]: set(r["claims"]) for r in rej}
                for i in x["issues"]:
                    if not set(i["claims"]) <= nos[i["rejection"]] or not i["claims"]:
                        raise ValueError(f"거절이유 {i['rejection']}에 없는 청구항 {i['claims']}")
                    if i["scope"] not in ("supported", "out_of_product_scope"):
                        raise ValueError("scope가 틀림")
                    for loc in i["locations"].split(","):
                        p, a, b = map(int, re.fullmatch(r"(\d+):(\d+)-(\d+)", loc.strip()).groups())
                        if not 1 <= a <= b <= len(pages[p - 1]):
                            raise ValueError(f"줄 범위가 틀림 {loc}")
                missed = {
                    (no, n)
                    for no, ns in nos.items()
                    for n in ns
                    if not any(i["rejection"] == no and n in i["claims"] for i in x["issues"])
                }
                if missed:
                    raise ValueError(f"논점이 하나도 없는 (거절이유, 청구항) {sorted(missed)}")

            prompt = J.anonymize(tmpl + json.dumps(rej, ensure_ascii=False) + "\n" + body)
            return call(self.work / "freeze-raw" / f"{c['case']}.json", GRADER, prompt, check)

        fan(one, self.cases, self.workers)
        cols = ("case", "rejection", "claims", "scope", "examiner_proposition", "locations")
        lines = ["\t".join(cols)]
        for c in self.cases:
            for i in J.read_json(self.work / "freeze-raw" / f"{c['case']}.json")["parsed"][
                "issues"
            ]:
                vals = (
                    c["case"],
                    i["rejection"],
                    ",".join(map(str, i["claims"])),
                    i["scope"],
                    re.sub(r"[\s\"]+", " ", i["examiner_proposition"]),
                    i["locations"].replace(" ", ""),
                )
                lines.append("\t".join(map(str, vals)))
        (target / "issue-decisions.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
        freeze(self.repo, self.base, target)  # 재아 코드: 원문 대조와 해시 고정
        print(J.read_json(target / "freeze.json"))

    # ---- draft: 의견서 생성 ----
    def draft(self):
        if not (self.root / "01-source-freeze/freeze.json").exists():
            sys.exit("논점을 먼저 고정한다")
        P = {
            n: (HERE / f"prompts/{n}.md").read_text()
            for n in ("opinion", "note_amend", "note_check")
        }

        def one(job):
            c, arm = job
            d, plan = self.inputs(c), self.plan(c)
            if arm == "direction":
                rows = [{"claim": q["claim"], "kind": q["action"]} for q in plan["amended"]]
                text = plan["strategy"] + "\n보정할 항: " + json.dumps(rows, ensure_ascii=False)
            else:
                rows = "\n\n".join(
                    f"[청구항 {q['claim']}] {'삭제' if q['action'] == 'delete' else '고침'}\n"
                    f"이유: {q['reason']}\n보정 뒤 글: {q['text'] or '(삭제)'}"
                    for q in plan["amended"]
                )
                text = plan["strategy"] + "\n\n보정안\n" + rows
            extra = {"direction": "", "amend": P["note_amend"]}.get(
                arm, P["note_amend"] + P["note_check"]
            )
            rej = [
                {
                    "no": r["no"],
                    "kind": r["kind"],
                    "article": r["article"],
                    "claims": r["targets"]["value"],
                }
                for r in self.f1(c)["rejections"]
            ]
            prompt = string.Template(P["opinion"]).substitute(
                extra=extra,
                direction=text,
                rejections=json.dumps(rej, ensure_ascii=False),
                oa=d["oa"],
                claims=d["claims"],
                cited=J.read_json(self.work / "cited" / f"{c['case']}.json"),
                application=d["application"],
            )

            def check(x):
                for k in ("points", "response", "amendment", "closing"):
                    if not isinstance(x[k], str) or not x[k].strip():
                        raise ValueError(f"{k} 칸이 비었음")

            call(self.work / "drafts" / f"{c['case']}-{arm}.json", WRITER, prompt, check)

        fan(one, [(c, a) for c in self.cases for a in ARMS], self.workers)

    def opinion_of(self, path):
        return [{"section": t, "text": x} for t, x in J.read_json(path).items()]

    def e_amends(self, c):
        return [
            {
                "claim": q["claim"],
                "original": q["before"],
                "draft_text": "(삭제)" if q["action"] == "delete" else q["text"],
                "basis": [],
                "held_reason": None,
            }
            for q in self.plan(c)["amended"]
        ]

    def drafts2(self, c, runs, rep):
        d = J.read_json(runs / c["case"] / f"f4_r{rep}.json")["drafts"] or {
            "opinion": [],
            "claims": [],
        }
        return {
            "f4": (
                [{"section": x["title"], "text": x["ai_text"]} for x in d["opinion"]],
                [
                    {
                        "claim": x["claim"],
                        "original": x["before"],
                        "draft_text": x["ai_text"],
                        "basis": [],
                        "held_reason": x["held_reason"],
                    }
                    for x in d["claims"]
                ],
            ),
            "f4_ours": (self.opinion_of(runs / c["case"] / f"ours_r{rep}.json"), self.e_amends(c)),
        }

    def drafts3(self, c, runs, rep):
        return {
            m: (self.opinion_of(runs / c["case"] / f"{m}_r{rep}.json"), self.e_amends(c))
            for m in self.arms
        }

    # ---- prep2: 앱 F4와 합친 방식의 초안을 같은 채점 입력으로 ----
    def prep2(self):
        runs, rep = self.repo / "work/e2e_opinion_1125/runs_api", self.rep
        keys = []
        for c in self.cases:
            drafts = self.drafts3(c, runs, rep) if self.sub else self.drafts2(c, runs, rep)
            order = sorted(
                drafts, key=lambda m: sha256(f"{c['case']}:{rep}:{m}".encode()).hexdigest()
            )
            key = {f"초안 {x}": m for x, m in zip("AB", order, strict=True)}
            J.write_json(
                self.root / c["case"] / "drafts-blinded.json",
                [
                    {"draft": k, "opinion": drafts[m][0], "amendments": drafts[m][1]}
                    for k, m in key.items()
                ],
            )
            cits = [
                {"label": x["label"], "number": self.cited_path(c, x).stem}
                for x in self.f1(c)["citations"]
            ]
            claims = [{"claim": n, "text": t} for n, t in self.old_claims(c).items()]
            J.write_json(
                self.root / c["case"] / "oa-evidence.json",
                {
                    "case": c["case"],
                    "claims_at_oa": claims,
                    "resolved_comparison_evidence": [{"citations": cits}],
                    "resolved_legal_evidence": [],
                },
            )
            keys.append({"case": c["case"], "draft_labels": key})
        J.write_json(self.root / "condition-key-local.json", keys)
        J.prepare_responses(self.root, self.run)
        S.build_corpus(self.repo, self.base, self.root, self.run)

    # ---- plans: combine.py에 줄 E 보정안 ----
    def plans(self):
        for c in self.cases:
            J.write_json(
                self.repo / "work/e2e_opinion_1125/runs_api" / c["case"] / "plan.json", self.plan(c)
            )

    # ---- claims: 보정안을 실제 보정과 비교 (코드만) ----
    def claims(self):
        sys.path.insert(0, str(self.exp / "pattern_exp"))
        import common as C

        key = {
            f"{r['case']}-{k[-1]}": v
            for r in J.read_json(self.root / "condition-key-local.json")
            for k, v in r["draft_labels"].items()
        }
        tot = {}
        for n, arm in sorted(key.items()):
            c = next(x for x in self.cases if x["case"] == n[:3])
            old = self.old_claims(c)
            gold = C.answers({"출원번호": c["key"].split("_")[0]})[0]
            pred = {}
            for a in J.read_json(self.run / "response-input" / f"{n}.json")["amendments"]:
                k, t = int(a["anchor"][2:]), a["draft_text"]
                if t and C.bare(t) != C.bare(old.get(k, "")):
                    pred[k] = "delete" if t.strip() == "(삭제)" else "amend"
            hit = sum(pred.get(k, "unchanged") == gold.get(k, "unchanged") for k in old)
            row = dict(
                n=len(old),
                hit=hit,
                over=sum(k in pred for k in old if k not in gold),
                keep=sum(k not in gold for k in old),
                miss=sum(k not in pred for k in old if k in gold),
                changed=sum(k in gold for k in old),
            )
            print(n[:3], arm, row)
            for k, v in row.items():
                tot.setdefault(arm, Counter())[k] += v
        for arm, t in tot.items():
            print("합", arm, dict(t), f"세 갈래 {t['hit'] / t['n']:.3f}")

    # ---- prep: 재아 채점기 입력 만들기 (조건 가림) ----
    def prep(self):
        titles = {
            "points": "지적 요지",
            "response": "대응과 근거",
            "amendment": "보정 설명",
            "closing": "마무리",
        }
        keys = []
        for c in self.cases:
            plan, folder = self.plan(c), self.root / c["case"]
            f1 = self.f1(c)
            claims = [{"claim": n, "text": t} for n, t in self.old_claims(c).items()]
            cits = [
                {"label": x["label"], "number": self.cited_path(c, x).stem} for x in f1["citations"]
            ]
            evidence = {
                "case": c["case"],
                "claims_at_oa": claims,
                "resolved_comparison_evidence": [{"citations": cits}],
                "resolved_legal_evidence": [],
            }
            J.write_json(folder / "oa-evidence.json", evidence)
            order = sorted(ARMS, key=lambda m: sha256(f"{c['case']}:{m}".encode()).hexdigest())
            blinded, key = [], {}
            for label, arm in zip("ABC", order, strict=True):
                out = J.read_json(self.work / "drafts" / f"{c['case']}-{arm}.json")["parsed"]
                key[f"초안 {label}"] = arm
                blinded.append(
                    {
                        "draft": f"초안 {label}",
                        "opinion": [{"section": t, "text": out[k]} for k, t in titles.items()],
                        "amendments": [
                            {
                                "claim": q["claim"],
                                "original": q["before"],
                                "draft_text": "(삭제)" if q["action"] == "delete" else q["text"],
                                "basis": [],
                                "held_reason": None,
                            }
                            for q in plan["amended"]
                        ],
                    }
                )
            J.write_json(folder / "drafts-blinded.json", blinded)
            keys.append({"case": c["case"], "draft_labels": key})
        J.write_json(self.root / "condition-key-local.json", keys)
        J.prepare_responses(self.root, self.run)
        S.build_corpus(self.repo, self.base, self.root, self.run)

    def phase(self, name, prompt_path, validate, inp=None):
        prompt = prompt_path.read_text(encoding="utf-8")
        paths = sorted((self.run / f"{inp or name}-input").glob("*.json"))
        if not paths:
            sys.exit(f"{name} 입력이 0개")

        def one(path):
            data = path.read_text(encoding="utf-8")
            obj = json.loads(data)
            dest = self.run / f"{name}-raw" / path.name
            call(dest, GRADER, prompt + "\n\n입력 JSON\n" + data, lambda x: validate(x, obj))

        fan(one, paths, self.workers)

    def response(self):
        self.phase("response", JUDGE / "response-prompt.md", J.validate_response)

    def support(self):
        S.prepare_batches(self.run, 18)
        for path in sorted((self.run / "support-input").glob("*.json")):
            # 보정 근거는 세 조건이 같은 보정안이라 재지 않는다
            data = J.read_json(path)
            data["checks"] = [k for k in data["checks"] if k["type"] == "issue_evidence"]
            if data["checks"]:
                J.write_json(path, data)
            else:
                path.unlink()
        self.phase("support", JUDGE / "support-prompt.md", J.validate_support)

    def coverage(self):
        def validate(x, data):
            if [r["anchor"] for r in x["claims"]] != [r["anchor"] for r in data["amendments"]]:
                raise ValueError("amendments 순서가 다름")
            for r in x["claims"] + x["phantom"]:
                if not set(r["anchors"]) <= set(data["opinion_lines"]):
                    raise ValueError(f"없는 줄 {r['anchors']}")
            for r in x["claims"]:
                if r["label"] not in ("explained", "partial", "mentioned", "missing", "conflict"):
                    raise ValueError("label이 틀림")
                if r["label"] != "missing" and not r["anchors"]:
                    raise ValueError("anchors가 비었음")

        for path in sorted((self.run / "response-input").glob("*.json")):
            d = J.read_json(path)
            keep = {k: d[k] for k in ("amendments", "opinion_lines")}
            J.write_json(self.run / "coverage-input" / path.name, keep)
        self.phase("coverage", HERE / "prompts/coverage.md", validate)

    def report(self):
        key = {
            f"{r['case']}-{k[-1]}": v
            for r in J.read_json(self.root / "condition-key-local.json")
            for k, v in r["draft_labels"].items()
        }
        issues = {
            r["issue_id"]: r for r in J.read_rows(self.root / "01-source-freeze/issues.jsonl")
        }
        out = {}
        for arm in sorted(set(key.values())):
            for scope in ["all", *[c["case"] for c in self.cases]]:
                names = [n for n, v in key.items() if v == arm and scope in ("all", n[:3])]
                r, dep, sup, cov, cross, ph, ln = (Counter() for _ in range(7))
                for n in names:
                    resp = J.read_json(self.run / "response-raw" / f"{n}.json")["parsed"]
                    indep = {
                        t["claim"]
                        for t in self.inputs(next(c for c in self.cases if c["case"] == n[:3]))[
                            "targets"
                        ]
                        if t["independent"]
                    }
                    for x in resp["issues"]:
                        i = issues[x["issue_id"]]
                        if i["scope"] != "supported":
                            continue
                        r[x["response"]] += 1
                        if not set(i["claims"]) & indep:
                            dep[x["response"]] += 1
                    cross.update(x["cross_document"] for x in resp["amendments"])
                    for p in (self.run / "support-raw").glob(f"{n}-*.json"):
                        sup.update(x["support"] for x in J.read_json(p)["parsed"]["checks"])
                    cv = J.read_json(self.run / "coverage-raw" / f"{n}.json")["parsed"]
                    cov.update(x["label"] for x in cv["claims"])
                    ph["phantom"] += len(cv["phantom"])
                    lines = J.read_json(self.run / "response-input" / f"{n}.json")["opinion_lines"]
                    ln["chars"] += sum(map(len, lines.values()))
                parts = dict(
                    issues=r, dependent_only=dep, support=sup, coverage=cov, cross_document=cross
                )
                parts |= dict(phantom=ph, opinion=ln)
                out.setdefault(scope, {})[arm] = {k: dict(v) for k, v in parts.items()}
        J.write_json(self.work / "summary.json", out)
        print(json.dumps(out["all"], ensure_ascii=False, indent=1))


def main():
    steps = (
        "setup",
        "freeze",
        "draft",
        "prep",
        "response",
        "support",
        "coverage",
        "report",
        "prep2",
        "plans",
        "claims",
    )
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("step", choices=steps)
    p.add_argument("--repo", type=Path, required=True, help="data/와 work/가 있는 폴더")
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--sub", action="store_true", help="prep2에서 셋째 비교 초안을 쓴다")
    p.add_argument("--plan-dir", type=Path, help="보정안 plan.json을 사건 폴더마다 읽을 곳")
    p.add_argument("--arms", default="ours_sub,ours_oa_sub")
    p.add_argument("--rep", type=int, default=1)
    p.add_argument("--workers", type=int, default=3)
    a = p.parse_args()
    getattr(Run(a), a.step)()


if __name__ == "__main__":
    main()
