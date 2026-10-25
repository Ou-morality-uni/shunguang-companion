# Third-party notices

## React Bits backgrounds

DarkVeil, GradientBlinds and Aurora in `src/backgrounds/` are adapted from [React Bits](https://github.com/DavidHDev/react-bits), retrieved from its official TypeScript/CSS registry on 2026-10-23.

Local changes: red-gold integration, failure/context-loss handling, bounded canvas resolution, 30 fps rendering limit and resource cleanup. No runtime MCP connection is required.

Upstream license, reproduced below:

MIT + Commons Clause License Condition v1.0

Copyright (c) 2026 David Haz

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, and distribute the Software **as part of an application, website, or product**, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

## Commons Clause Restriction

You may use this Software, including for any commercial purpose, **so long as you do not sell, sublicense, or redistribute the components themselves-whether alone, in a bundle, or as a ported version.**

The same restriction covers the React Bits tools (Background Studio, Texture Lab, Shape Magic, Center Stage, Sound Lab and any tools added later) and the sounds in the sound library. **You may not sell, sublicense, or redistribute the tools or the sounds themselves, or offer the tools or a substantially similar copy of them as a hosted service-whether alone, in a bundle, or as a ported version.**

What you make with the tools is yours to use. You can use exported code, images, videos, and audio files in any personal or commercial application, website, or product, including paid ones. **You may not sell or redistribute the exports on their own, either individually or as the product itself, such as a sound, texture, background, or template pack.**

## No Warranty

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.


## PDF.js continuous document preview (v0.6.2)

Uses `pdfjs-dist@6.4.299` without modifying upstream files: the official PDFViewer, rendering queue, text layer, worker, CMaps, standard fonts, image decoding WASM and ICC data. Copyright Mozilla Foundation and contributors; Apache-2.0 and the accompanying font/codec licenses. Copies are in `licenses/pdfjs/`, and the build includes those notices with same-origin runtime assets. Source: https://github.com/mozilla/pdf.js .

## Local OCR (v0.6.2)

Uses `tesseract.js@7.0.0`, its locked `tesseract.js-core` engine, and unmodified `@tesseract.js-data/chi_sim@1.0.0` / `eng@1.0.0` `4.0.0_best_int` dictionaries. Tesseract.js and core use Apache-2.0. The npm dictionary package metadata declares MIT; the actual upstream tessdata distribution includes Apache-2.0. Preserve its license at `licenses/ocr/traineddata-LICENSE` (https://github.com/naptha/tessdata/blob/gh-pages/LICENSE), alongside the JS/core licenses. Dictionaries and workers are served from this application, not a runtime CDN. User files are recognized locally only after pressing the OCR button.

React Bits MCP was consulted for GlareHover examples; this version reuses the project's existing button treatment and Radix/Motion controls, without copying another hover component.
