"""Compact galleries using Canvas's supported Markdown tables."""

from markdown_it import MarkdownIt


def gallery_tables(source: str, columns: int = 4) -> str:
    """Group adjacent top-level image/caption paragraphs without crossing blocks.

    Keep complete captions and their links under the corresponding images. Existing
    tables, lists, quotes and code are left alone. A heading or extra prose paragraph
    ends a gallery. The source itself stays unchanged for publication retry receipts.
    """
    if not 2 <= columns <= 4:
        raise ValueError("Gallery columns must be between 2 and 4.")
    lines = source.splitlines(keepends=True)
    tokens = MarkdownIt().enable("table").parse(source)
    paragraphs = {}
    for i, token in enumerate(tokens):
        if token.type != "paragraph_open" or token.level != 0 or not token.map:
            continue
        inline = tokens[i + 1]
        children = inline.children or []
        image = len(children) == 1 and children[0].type == "image"
        paragraphs[token.map[0]] = (token.map[1], image)

    def next_paragraph(start):
        while start < len(lines) and not lines[start].strip():
            start += 1
        return start

    def cell(text):
        # Pipes are table separators, even in code spans. Entities preserve them.
        return text.strip().replace("|", "&#124;").replace("\n", "<br>")

    edits = []
    cursor = 0
    while cursor < len(lines):
        start = cursor
        pictures, captions = [], []
        while paragraphs.get(cursor, (0, False))[1]:
            end, _ = paragraphs[cursor]
            pictures.append("".join(lines[cursor:end]))
            cursor = next_paragraph(end)
            caption = ""
            if cursor in paragraphs and not paragraphs[cursor][1]:
                end, _ = paragraphs[cursor]
                caption = "".join(lines[cursor:end])
                cursor = next_paragraph(end)
            captions.append(caption)
        if len(pictures) > 1:
            tables = []
            for offset in range(0, len(pictures), columns):
                group = pictures[offset : offset + columns]
                labels = [f"Screen {i + 1}" for i in range(offset, offset + len(group))]
                rows = [labels, ["---"] * len(group), [cell(p) for p in group]]
                details = captions[offset : offset + columns]
                if any(details):
                    rows.append([cell(c) for c in details])
                tables.append("\n".join("| " + " | ".join(row) + " |" for row in rows))
            edits.append((start, cursor, "\n\n".join(tables) + "\n\n"))
        cursor = max(cursor, start + 1)
    for start, end, table in reversed(edits):
        lines[start:end] = [table]
    return "".join(lines)
