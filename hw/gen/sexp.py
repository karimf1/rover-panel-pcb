"""Minimal S-expression reader/writer for KiCad files.

KiCad's file formats are all S-expressions. Parsing them properly (rather than
with regex) is about forty lines and makes everything downstream reliable.
Atoms come back as str; quoted strings come back as QStr so they can be
re-emitted with quotes.
"""

class QStr(str):
    """A string that was quoted in the source and must be re-quoted on output."""
    __slots__ = ()


def parse(text):
    """Parse the first S-expression in `text`. Returns nested lists."""
    toks, i, n = [], 0, len(text)
    stack, cur = [], None
    while i < n:
        c = text[i]
        if c == '(':
            new = []
            if cur is not None: cur.append(new)
            stack.append(cur); cur = new; i += 1
        elif c == ')':
            done = cur; cur = stack.pop(); i += 1
            if cur is None: return done
        elif c == '"':
            j, buf = i + 1, []
            while j < n:
                if text[j] == '\\': buf.append(text[j+1]); j += 2
                elif text[j] == '"': break
                else: buf.append(text[j]); j += 1
            cur.append(QStr(''.join(buf))); i = j + 1
        elif c in ' \t\r\n':
            i += 1
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n()"': j += 1
            cur.append(text[i:j]); i = j
    return cur


def parse_all(text):
    """Parse a whole library file: returns the single top-level expression."""
    return parse(text)


def _esc(s):
    return s.replace('\\', '\\\\').replace('"', '\\"')


def dump(node, indent=0, tab='\t'):
    """Re-emit an expression in KiCad's usual indented style."""
    pad = tab * indent
    if not isinstance(node, list):
        return QStr and ('"%s"' % _esc(node) if isinstance(node, QStr) else str(node))
    # leaf-ish: no nested lists -> one line
    if not any(isinstance(c, list) for c in node):
        inner = ' '.join(dump(c) for c in node)
        return '%s(%s)' % (pad, inner)
    head = [c for c in node if not isinstance(c, list)]
    rest = [c for c in node if isinstance(c, list)]
    out = ['%s(%s' % (pad, ' '.join(dump(h) for h in head))]
    for r in rest:
        out.append(dump(r, indent + 1, tab))
    out.append('%s)' % pad)
    return '\n'.join(out)


def find(node, tag):
    """First direct child list whose head is `tag`."""
    for c in node:
        if isinstance(c, list) and c and c[0] == tag:
            return c
    return None


def findall(node, tag):
    return [c for c in node if isinstance(c, list) and c and c[0] == tag]


def val(node, tag, idx=1, default=None):
    c = find(node, tag)
    return c[idx] if c and len(c) > idx else default
