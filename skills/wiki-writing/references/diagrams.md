# Visuals: decide, then execute

## Choose
| Content | Use |
|---|---|
| Calls/handshake between components over time | Mermaid `sequenceDiagram` |
| Topology, architecture, dependencies | `flowchart` (max 15 nodes) |
| Lifecycle or states | `stateDiagram` |
| Entities and relations | `erDiagram` |
| Linear steps | Numbered list, no diagram |
| 3+ attributes across items, exact values | Table |
| Trend, scale or dispersion of measured data | Chart + the data table beside it |
| UI is the subject | Cropped screenshot, no personal data |
| Code, terminal output | Text code block, never an image |

## Skip the visual when
- it repeats the text (drop the visual, keep the text);
- the content changes often and nobody maintains the figure;
- it exists only to make the page look less dense.

## Execute
- One message per figure. Diagram the concept; put details in text.
- A legend or many colors means too much: split it.
- Keep diagrams as text (Mermaid) in the same repository/PR as the change. Confirm the target wiki renders Mermaid; avoid `classDef`/`style` so it also renders on GitHub.
- Introduce with a full sentence; caption "Figure N. <what it shows>."; refer to it by number, never "the image above".
- Alt text: at most 155 characters, describes what the figure conveys, no "image of". If the figure holds more, repeat the content in text. New information never lives only in the image.
- Exported images: SVG (or PNG), opaque background, no animated GIF. Hide personal data with a solid fill, never blur.
