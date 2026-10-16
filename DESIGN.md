---
version: alpha
name: Xcollect Editorial Reader
description: Target design direction for a content-first Xcollect reading experience; migration from existing indigo CSS is not complete.
colors:
  primary: "#176B63"
  primary-dark: "#65B7A6"
  light-background: "#F7F8F5"
  light-surface: "#FFFFFF"
  light-foreground: "#172723"
  light-muted: "#4E625B"
  light-border: "#DDE5DF"
  dark-background: "#101A18"
  dark-surface: "#192522"
  dark-foreground: "#E5F0EB"
  dark-muted: "#A6B9B0"
  dark-border: "#334840"
  action-warning: "#A26719"
typography:
  body:
    fontFamily: "Inter"
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.65
  article-heading:
    fontFamily: "Plus Jakarta Sans"
    fontSize: 20px
    fontWeight: 600
    lineHeight: 1.35
    letterSpacing: "-0.015em"
  metadata:
    fontFamily: "Inter"
    fontSize: 13px
    fontWeight: 500
    lineHeight: 1.5
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
rounded:
  sm: 6px
  md: 10px
  lg: 14px
  full: 999px
components:
  feed-card:
    background: "{colors.light-surface}"
    radius: "{rounded.md}"
  primary-action:
    color: "{colors.primary}"
---
# Xcollect Editorial Reader — DESIGN.md

> Google Stitch open DESIGN.md format (alpha): https://github.com/google-labs-code/design.md
> **Status: TARGET, not an assertion about deployed CSS.** This is the agreed working direction for the next iteration; current UI still uses separate indigo-based `--c-*` tokens in `public/css/theme.css`. Every token migration needs screenshots, test verification, and explicit deployment status. Do not interpret the target palette as proof of an implemented change.

## Overview

A personal reading room for discovered ideas, evidence and saved explorations. More like a deliberately typeset publication with clear provenance than a crowded admin dashboard. Primary goal: make browsing Xcollect intrinsically comfortable and rewarding enough to replace habitual X scrolling. **Density serves content, never decoration.**

The working aesthetic: warm neutral surfaces, restrained petrol-teal interaction color, strong body text, quieter metadata, fluid reading rhythm, generous media, and a stable place for meaningful actions. Target a low-distraction reader, not high-gloss “AI SaaS”.

## Colors

The YAML tokens define the **target** palette. In light mode use warm-white page `#F7F8F5`, true-white content surface `#FFFFFF`, primary text `#172723`, muted text `#4E625B`, borders `#DDE5DF`. In dark mode use deep green-charcoal `#101A18`, elevated `#192522`, text `#E5F0EB`, muted `#A6B9B0`, borders `#334840`. Interactive accent: `#176B63` on light and `#65B7A6` on dark. Check contrast for every state rather than assuming a nominal token passes.

**Existing (as of 2026-10-16):** `theme.css` defines dark `--c-bg: 13 19 31`, `--c-brand: 99 102 241`, and light `--c-brand: 79 70 229`. Do not merge target and incumbent as if they were identical; migrate intentionally, component-by-component.

## Typography

Use 16px body as the default reading target, with ~1.6–1.7 line height and paragraphs separated by whitespace. Titles must describe content, not dominate author/source identity. Reserve display-size type for a true page heading; do not render every card title as a giant bold headline. Prefer a sensible mixed Chinese/Latin fallback stack and test actual Chinese rendering; the named Latin fonts are not a CJK guarantee.

Show authors, handles, timestamps and source state in a quieter hierarchy, but never at unreadably low contrast. Numeric popularity metrics should not overpower article text.

## Layout

- Default to a **reading-first feed**: a comfortable single reading column or clearly structured main column, max line length around 65–80 Latin characters where applicable. Multi-column grids are optional discovery scanning modes, not mandatory for long text.
- Make the first screen about reading. Search and switches stay accessible; diagnostic buttons, infrequent classification/sync actions and obscure filters can move behind a secondary control.
- Put related content together: author's identity, text, attributed quotes, media, provenance and relevant actions belong to the same reading unit.
- Cards size to real content. Do not pad short posts to arbitrary equal heights. Long text expands inline, preserving scroll position.
- Maintain responsive behavior from ~375px mobile through a ~1440px desktop. No horizontal clipping; buttons respect usable touch targets.

## Elevation & Depth

Use borders, spacing and typography before drop shadows. One subtle shadow/elevation level for active overlays or menus, not a glowing outline on every card. Avoid backdrop blur for ordinary reading surfaces unless a measured design need exists. Hover must not move the card under the pointer (existing stability invariant).

## Shapes

A coherent moderate radius system (6/10/14px). Rounded pills are for controls with a real segmented/status meaning, not universal decoration. Images reflect their source aspect ratio, with an intentional viewer for full inspection.

## Components

### Feed item

Content-centered sequence: source/author → full ordinary text or explicit inline expansion → attached media → relevant original/quote attribution → compact decision actions. **`body_raw` is canonical.** Avoid a colored inset “text-rich box” nested inside another card just to label text as content. A quoted Tweet may need a visually nested block, but it must remain one coherent attributed object with proper paragraph boundaries.

### Discovery action bar

Keep Copy, Original, Not Interested and false-positive × behavior distinct. Do not display an X Bookmark mutation control on Discovery until the verified integration actually supports it; do not conflate false-positive reporting with topic disinterest. Place uncommon actions in an overflow affordance when they clutter the reading path, without hiding the core intent.

### Active Research workspace

Use the same reading components/tokens as the feed. Put the active question and its evidence first. Task-management rails must not dominate the result body. Empty, pending and failed discovery states must be semantically honest.

### Inputs and controls

Visible labels, focus indicators, normal keyboard navigation, useful validation/help copy and disabled/loading/error feedback. Don't replace all labels with ambiguous emoji. Keep target sizes reasonable for touch.

### Reader/modal

Optional deep reading surface with a clear exit and scroll-position continuity. It must not be the required path to inspect an ordinary post. Handle long-form text, source links, images and quoted content without fragmentation.

## Do's and Don'ts

**Do:** emphasize words and evidence; use a quiet hierarchy; make decisions and their source semantics obvious; respect reduced motion; compare mobile and desktop screenshots; ensure Local Profile and Cloud display the same normalized content.

**Don't:** apply saturated purple glows, decorative gradient borders, glassmorphism or nested cards as defaults; hard-clamp the canonical content to a generic six-line snippet; hide critical provenance; promise source write-back before confirmation; let design changes break Discovery freshness/retention or bookmark ownership.

## Implementation and verification

Product facts: [PRODUCT.md](PRODUCT.md). Execution rubric: [docs/design/READING_EXPERIENCE.md](docs/design/READING_EXPERIENCE.md). Coding contracts: [AGENTS.md](AGENTS.md).

Current CSS modules: `public/css/theme.css`, `layout.css`, `cards.css`, `modal.css`, `watch.css`. Align tokens in `theme.css` first, then improve feed hierarchy and reader, then Active Research. New work should use design tokens, not one-off colors. This document is source-controlled so Stitch, Codex and Impeccable can reference the same design intent.
