// 답변 마크다운 해석기(순수 함수). HTML 을 만들지 않고 구조(JSON)만 돌려준다 -> 화면이 textContent 로 안전하게 그린다.
// 지원: **굵게**, 번호 목록(1.), 글머리 목록(-, *), 한 단계 하위 목록(들여쓰기 2칸 이상), 문단, 줄 바꿈.
// 제목·표·코드 블록은 해석하지 않고 글자 그대로 둔다(프롬프트가 쓰지 말라고 안내한다).
(function (root) {
  "use strict";

  function inline(text) {
    var parts = [], re = /\*\*(.+?)\*\*/g, last = 0, m;
    while ((m = re.exec(text)) !== null) {
      if (m.index > last) parts.push({ t: "text", v: text.slice(last, m.index) });
      parts.push({ t: "strong", v: m[1] });
      last = re.lastIndex;
    }
    if (last < text.length) parts.push({ t: "text", v: text.slice(last) });
    return parts;
  }

  var ITEM = /^(\s*)([-*]|\d+\.)\s+(.*)$/;

  function makeList(marker) {
    return /^\d/.test(marker) ? { type: "ol", start: parseInt(marker, 10), items: [] } : { type: "ul", items: [] };
  }

  function parseMarkdown(text) {
    var lines = String(text).replace(/\r\n?/g, "\n").split("\n");
    var blocks = [], para = null, list = null, lastItem = null;

    function flushPara() { if (para) { blocks.push({ type: "p", inline: para }); para = null; } }
    function endList() { list = null; lastItem = null; }

    lines.forEach(function (line) {
      if (!line.trim()) { flushPara(); endList(); return; }
      var m = ITEM.exec(line);
      if (m) {
        flushPara();
        var indent = m[1].replace(/\t/g, "  ").length, marker = m[2];
        var item = { inline: inline(m[3]), children: null };
        if (indent >= 2 && lastItem) {
          if (!lastItem.children) lastItem.children = makeList(marker);
          lastItem.children.items.push(item);
        } else {
          var type = /^\d/.test(marker) ? "ol" : "ul";
          if (!list || list.type !== type) { list = makeList(marker); blocks.push(list); }
          list.items.push(item);
          lastItem = item;
        }
        return;
      }
      endList();
      var parts = inline(line.trim());
      if (!para) para = parts;
      else para = para.concat([{ t: "br" }], parts);
    });
    flushPara();
    return blocks;
  }

  if (typeof module !== "undefined" && module.exports) module.exports = { parseMarkdown: parseMarkdown };
  else root.parseMarkdown = parseMarkdown;
})(typeof globalThis !== "undefined" ? globalThis : this);
