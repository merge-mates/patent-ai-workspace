"""변수 실험(V1)용 변형 코퍼스. 청크 id·메타데이터는 그대로, 검색에 쓰는 text 만 바꾼다."""


def drop_header(text: str) -> str:
    """첫 줄(`특허법 제N조(제목)`)을 지우고 본문만 남긴다. 줄바꿈이 없으면(본문 없음) 그대로 둔다."""
    head, sep, body = text.partition("\n")
    return body if sep else text


def make_noheader(chunks: list[dict]) -> list[dict]:
    out = []
    for c in chunks:
        d = dict(c)
        d["text"] = drop_header(c["text"])
        out.append(d)
    return out


def make_context(chunks: list[dict]) -> list[dict]:
    """Phase 6 실험 ③: 장·절·관 제목을 청크 맨 앞에 붙인다(예: "제3장 특허출원 및 심사 > 제1절 출원").
    제목이 없는 청크는 그대로 둔다. id·메타데이터는 그대로, text 만 바뀐다."""
    out = []
    for c in chunks:
        d = dict(c)
        md = c.get("metadata", {})
        path = " > ".join(x for x in (md.get("chapter"), md.get("section"), md.get("subsection")) if x)
        if path:
            d["text"] = f"{path}\n{c['text']}"
        out.append(d)
    return out
