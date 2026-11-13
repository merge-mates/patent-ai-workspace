import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const { parseMarkdown } = createRequire(import.meta.url)("../src/rag/web/md.js");
const T = (v) => ({ t: "text", v });
const B = (v) => ({ t: "strong", v });

test("굵게(**)는 strong 으로, 나머지는 글자로 나온다", () => {
  assert.deepEqual(parseMarkdown("**굵게** 보통"), [{ type: "p", inline: [B("굵게"), T(" 보통")] }]);
});

test("짝이 안 맞는 ** 는 글자 그대로 둔다", () => {
  assert.deepEqual(parseMarkdown("a **b"), [{ type: "p", inline: [T("a **b")] }]);
});

test("HTML 처럼 생긴 글은 해석하지 않고 글자로 둔다", () => {
  assert.deepEqual(parseMarkdown("<b>x</b><script>1</script>"), [{ type: "p", inline: [T("<b>x</b><script>1</script>")] }]);
});

test("빈 줄은 문단을 나누고, 한 줄 바꿈은 br 로 남는다", () => {
  assert.deepEqual(parseMarkdown("첫째\n둘째\n\n셋째"), [
    { type: "p", inline: [T("첫째"), { t: "br" }, T("둘째")] },
    { type: "p", inline: [T("셋째")] },
  ]);
});

test("번호 목록 안의 하위 글머리 목록이 중첩된다", () => {
  const out = parseMarkdown("1. 첫째\n   - 하위1\n   - 하위2\n2. 둘째");
  assert.deepEqual(out, [{
    type: "ol", start: 1, items: [
      { inline: [T("첫째")], children: { type: "ul", items: [{ inline: [T("하위1")], children: null }, { inline: [T("하위2")], children: null }] } },
      { inline: [T("둘째")], children: null },
    ],
  }]);
});

test("번호 목록은 첫 번호를 start 로 기억한다", () => {
  assert.equal(parseMarkdown("3. 가\n4. 나")[0].start, 3);
});

test("글머리 목록 항목 안의 굵게도 해석한다", () => {
  assert.deepEqual(parseMarkdown("- **제1호** 설명"), [{ type: "ul", items: [{ inline: [B("제1호"), T(" 설명")], children: null }] }]);
});

test("문단, 목록, 문단이 섞여도 순서대로 나온다", () => {
  const out = parseMarkdown("머리말\n\n- 가\n- 나\n\n맺음");
  assert.deepEqual(out.map((b) => b.type), ["p", "ul", "p"]);
});

test("빈 입력은 빈 목록", () => {
  assert.deepEqual(parseMarkdown("  \n\n "), []);
});
