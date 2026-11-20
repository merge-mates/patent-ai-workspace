"""원문 대조 도우미: 글자가 원문에 그대로 있는지 찾는다 (공백 줄이기만 허용).

모델이 준 글자(구성요소, 인용구, 근거)를 원문과 맞출 때 F3 단계들이 같이 쓴다.
이어진 공백·줄바꿈을 한 칸으로 줄여 비교하고, 찾은 자리는 원문 오프셋으로 돌려준다.
"""


def squeeze(text: str) -> tuple[str, list[int]]:
    """이어진 공백(줄바꿈 포함)을 한 칸으로 줄인 글자와, 그 글자마다 원문 오프셋을 돌려준다."""
    chars: list[str] = []
    offsets: list[int] = []
    for i, ch in enumerate(text):
        if ch.isspace():
            if chars and chars[-1] != " ":
                chars.append(" ")
                offsets.append(i)
        else:
            chars.append(ch)
            offsets.append(i)
    if chars and chars[-1] == " ":  # 끝 공백은 뺀다
        chars.pop()
        offsets.pop()
    return "".join(chars), offsets


def find_from(
    needle: str, squeezed: str, offsets: list[int], cursor: int
) -> tuple[int, int, int] | None:
    """needle을 줄인 원문의 cursor 자리부터 찾는다.

    돌려주는 값: (원문 start, 원문 end, 다음 cursor). 못 찾으면 None.
    """
    wanted = " ".join(needle.split())
    if not wanted:
        return None
    pos = squeezed.find(wanted, cursor)
    if pos < 0:
        return None
    last = pos + len(wanted) - 1
    return offsets[pos], offsets[last] + 1, last + 1


def find_span(needle: str, text: str) -> tuple[int, int] | None:
    """needle이 text에 그대로 있으면 (원문 start, 원문 end), 없으면 None. 처음 나온 자리."""
    squeezed, offsets = squeeze(text)
    found = find_from(needle, squeezed, offsets, 0)
    return None if found is None else (found[0], found[1])


def find_all_spans(needle: str, text: str) -> list[tuple[int, int]]:
    """needle이 text에 나오는 모든 자리 (원문 start, end). 서로 겹치지 않게 앞에서부터 센다."""
    squeezed, offsets = squeeze(text)
    spans: list[tuple[int, int]] = []
    cursor = 0
    while (found := find_from(needle, squeezed, offsets, cursor)) is not None:
        spans.append((found[0], found[1]))
        cursor = found[2]
    return spans


def is_too_short(quote: str, text: str, min_chars: int) -> bool:
    """근거로 옮긴 글자가 너무 짧은가 (공백을 뺀 글자 수로 센다).

    한두 글자는 아무 글에나 들어 있어 "원문에 있음"이 근거가 되지 못한다.
    글 전체가 하한보다 짧을 때(도면 설명 한 줄 등)는 글 전체를 옮긴 것만 받는다.
    """
    n = len("".join(quote.split()))
    return n < min_chars and n < len("".join(text.split()))
