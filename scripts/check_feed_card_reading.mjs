/**
 * Canonical feed card rendering contract.
 * Run with: node scripts/check_feed_card_reading.mjs
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const js = fs.readFileSync("public/js/render.js", "utf8");
const css = fs.readFileSync("public/css/cards.css", "utf8");
const sandbox = {
  window: { location: { origin: "https://x.daduiot.com" } },
  URL,
  console,
};
vm.createContext(sandbox);
vm.runInContext(js, sandbox);

const baseItem = {
  id: "101",
  author: "Test",
  username: "test",
  title: "Many people misunderstand local AI. They see it as a replacement for fro...",
  snippet: "Many people misunderstand local AI. They see it as a replacement for frontier models",
  body_raw: "Many people misunderstand local AI. They see it as a replacement for frontier models.\n\nLocal AI solves three other problems with privacy, latency and cost.",
  source_kind: "discovery",
  is_bookmark: false,
  created_at: "2026-10-10T12:00:00Z",
  url: "https://x.com/test/status/101",
};

const render = item => sandbox.generateTweetCardHtml(item);
const full = render(baseItem);
assert.match(full, /Local AI solves three other problems/);
assert.match(full, /card-title is-repeated/);
assert.doesNotMatch(full, /内容预览/);
assert.doesNotMatch(full, /class="card-snippet/);
assert.match(full, /阅读模式 ↗/);
assert.doesNotMatch(full, /展开全文 ↓/);

// Older records explicitly say when only a 140-character snippet is available.
assert.match(render({ ...baseItem, body_raw: "" }), /当前仅同步到摘要/);

// Long posts retain all source text in the DOM and expand inline, not in a modal.
const endMarker = "END_OF_CANONICAL_BODY";
const longHtml = render({
  ...baseItem,
  title: "Unique article title",
  body_raw: ("A long paragraph with original technical content. ".repeat(40)) + endMarker,
});
assert.match(longHtml, /is-collapsible/);
assert.match(longHtml, /展开全文 ↓/);
assert.match(longHtml, /END_OF_CANONICAL_BODY/);
assert.match(longHtml, /toggleCardText\(this\)/);

// Old persisted quoted tweets must be one card with two internal paragraphs.
// Bare '>' is an internal paragraph boundary, not its own visible quote box.
const quoteText = "原推正文\n\n> 引用 @finnvoorhees\n>\n> Say goodbye to your Mac mini\n>\n> Your agent should live in your pocket.";
const quotedCard = render({ ...baseItem, body_raw: quoteText });
assert.equal((quotedCard.match(/<blockquote/g) || []).length, 1);
assert.match(quotedCard, /<blockquote class="quoted-tweet-content">/);
assert.match(quotedCard, /<p>引用 @finnvoorhees<\/p>/);
assert.match(quotedCard, /<p>Say goodbye to your Mac mini<\/p>/);
assert.match(quotedCard, /<p>Your agent should live in your pocket\.<\/p>/);
assert.doesNotMatch(quotedCard, /<blockquote[^>]*>\s*<\/blockquote>/);
const quotedMarkdown = sandbox.buildTweetMarkdown({ ...baseItem, body_raw: quoteText });
assert.match(quotedMarkdown, /> 引用 @finnvoorhees\n>\n> Say goodbye/);
const enrichedQuote = sandbox.parseMarkdownToHtml(
  "Top\n\n> **引用推文** · Finn Voorhees [@finnvoorhees](https://x.com/finnvoorhees/status/123)\n>\n> First paragraph\n>\n> Second paragraph",
  [], []
);
assert.equal((enrichedQuote.match(/<blockquote/g) || []).length, 1);
assert.match(enrichedQuote, /https:\/\/x\.com\/finnvoorhees\/status\/123/);
assert.equal((enrichedQuote.match(/<p>/g) || []).length, 4); // primary + 3 quoted paragraphs
const ordinaryBlock = sandbox.parseMarkdownToHtml("> Generic\n> quoted content", [], []);
assert.match(ordinaryBlock, /class="canonical-blockquote"/);
assert.equal((ordinaryBlock.match(/<blockquote/g) || []).length, 1);

// Structured X quote is an independent object, not a Markdown quote inside body_raw.
const quoteObject = {
  id: "123",
  author: "Finn Voorhees",
  username: "finnvoorhees",
  avatar: "https://pbs.twimg.com/finn_normal.jpg",
  url: "https://x.com/finnvoorhees/status/123",
  created_at: "2026-10-12T00:00:00Z",
  body_raw: "Say goodbye to your Mac mini.\n\nYour agent should live in your pocket.",
  images: ["https://pbs.twimg.com/quote.jpg"],
  videos: [],
};
const structuredCard = render({ ...baseItem, body_raw: "Pelican discussion", quoted_tweet: quoteObject });
assert.match(structuredCard, /<article class="embedded-tweet"/);
assert.match(structuredCard, /class="embedded-tweet-author">Finn Voorhees/);
assert.match(structuredCard, /href="https:\/\/x\.com\/finnvoorhees\/status\/123"/);
assert.match(structuredCard, /Your agent should live in your pocket/);
assert.match(structuredCard, /https:\/\/pbs\.twimg\.com\/quote\.jpg/);
assert.doesNotMatch(structuredCard, /<blockquote class="quoted-tweet-content">/);
assert.equal((structuredCard.match(/<article class="embedded-tweet"/g) || []).length, 1);
const mdStructured = sandbox.buildTweetMarkdown({ ...baseItem, body_raw: "Pelican discussion", quoted_tweet: quoteObject });
assert.match(mdStructured, /Pelican discussion\n\n> \*\*引用推文\*\*/);
assert.match(mdStructured, /https:\/\/x\.com\/finnvoorhees\/status\/123/);
assert.match(mdStructured, /> Say goodbye to your Mac mini\.\n>\n> Your agent/);
assert.match(mdStructured, /> !\[引用推文配图\]\(https:\/\/pbs\.twimg\.com\/quote\.jpg\)/);
assert.doesNotMatch(mdStructured.split("> **引用推文**")[0], /Say goodbye/);
const mediaQuote = sandbox.renderQuotedTweetHtml({
  ...quoteObject, videos: [{ url: "https://video.twimg.com/clip.mp4" }],
});
assert.match(mediaQuote, /<video[^>]*controls playsinline/);
const unsafeQuote = sandbox.renderQuotedTweetHtml({
  ...quoteObject, author: "<img src=x onerror=alert(1)>",
  body_raw: "<script>alert(1)</script>", url: "javascript:alert(1)", avatar: "javascript:alert(2)"
});
assert.match(unsafeQuote, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
assert.doesNotMatch(unsafeQuote, /<script>|href="javascript:|src="javascript:/);
assert.match(structuredCard, /card-readable-content/);
assert.match(structuredCard, /embedded-tweet/);

// Old flattened bookmarks continue to use the previous quote grouping.
assert.equal((quotedCard.match(/<blockquote/g) || []).length, 1);

// Source text must remain escaped even when rendered inside the card.
const escaped = render({
  ...baseItem,
  body_raw: "<img src=x onerror=alert(1)> test",
  title: "HTML escape test",
});
assert.match(escaped, /&lt;img src=x onerror=alert\(1\)&gt;/);
assert.doesNotMatch(escaped, /<img src=x onerror=/);

// Body + media coexist; video retains its own controls.
assert.match(render({
  ...baseItem,
  videos: [{ url: "https://video.twimg.com/test.mp4", type: "video" }],
}), /<video[^>]*controls playsinline/);

// No forced empty 420px cards; card body is not the mobile 3-line snippet.
assert.doesNotMatch(css, /min-height:\s*420px/);
assert.match(css, /\.card-readable-content/);
assert.match(css, /\.card-title\.is-repeated/);
assert.match(js, /window\.toggleCardText\s*=\s*toggleCardText/);

console.log("Feed card canonical-reading checks passed");
