"""Control-flow structuring for C output.

Natural loops (back edges to a dominating header) become `while (true)` with break and
continue; conditional branches become if/else around their immediate post-dominator;
jump tables become `switch`. Anything that does not fit (irreducible flow, jumps into an
already emitted region) becomes `goto LAB_xxx;` with a label, which keeps the C exact.
Afterwards simple shapes are rewritten: `while (true) { if (c) break; ...}` -> `while (!c)`
and `while (true) { ...; if (c) continue; break; }` -> `do { ... } while (c);`.
"""
import re

from .ir import Branch, IndirectJump, Jump, Ret, Switch, negate

INDENT = '  '


def compute_dominators(order, succ, preds, entry):
    index = {b: i for i, b in enumerate(order)}
    idom = {entry: entry}

    def intersect(a, b):
        while a != b:
            while index[a] > index[b]:
                a = idom[a]
            while index[b] > index[a]:
                b = idom[b]
        return a
    changed = True
    while changed:
        changed = False
        for b in order:
            if b == entry:
                continue
            ps = [p for p in preds.get(b, []) if p in idom]
            if not ps:
                continue
            new = ps[0]
            for p in ps[1:]:
                new = intersect(p, new)
            if idom.get(b) != new:
                idom[b] = new
                changed = True
    return idom


def rpo(entry, succ):
    seen, order = set(), []
    stack = [(entry, iter(succ.get(entry, [])))]
    seen.add(entry)
    while stack:
        node, it = stack[-1]
        nxt = next(it, None)
        if nxt is None:
            stack.pop()
            order.append(node)
        elif nxt not in seen:
            seen.add(nxt)
            stack.append((nxt, iter(succ.get(nxt, []))))
    return list(reversed(order))


def dominates(idom, a, b):
    while True:
        if a == b:
            return True
        parent = idom.get(b)
        if parent is None or parent == b:
            return False
        b = parent


class Structurer:
    def __init__(self, entry, blocks, succ, printer):
        self.entry = entry
        self.blocks = blocks
        self.succ = {b: [s for s in succ.get(b, []) if s in blocks] for b in blocks}
        self.printer = printer
        self.order = rpo(entry, self.succ)
        self.preds = {b: [] for b in self.order}
        for b in self.order:
            for s in self.succ[b]:
                if s in self.preds:
                    self.preds[s].append(b)
        self.idom = compute_dominators(self.order, self.succ, self.preds, entry)
        exit_node = '__exit__'
        rsucc = {b: [] for b in self.order}
        rsucc[exit_node] = []
        for b in self.order:
            if not self.succ[b]:
                rsucc[exit_node].append(b)
            for s in self.succ[b]:
                rsucc.setdefault(s, []).append(b)
        reach = set(rpo(exit_node, rsucc))
        for b in self.order:
            if b not in reach:
                rsucc[exit_node].append(b)
        rorder = rpo(exit_node, rsucc)
        rpreds = {b: [] for b in rorder}
        for b, ss in rsucc.items():
            for s in ss:
                if s in rpreds:
                    rpreds[s].append(b)
        self.ipdom = compute_dominators(rorder, rsucc, rpreds, exit_node)
        self.exit = exit_node
        self.loops = {}
        for b in self.order:
            for s in self.succ[b]:
                if dominates(self.idom, s, b):
                    loop = self.loops.setdefault(s, {'header': s, 'latches': [], 'body': {s}})
                    loop['latches'].append(b)
        for header, loop in self.loops.items():
            stack = list(loop['latches'])
            while stack:
                node = stack.pop()
                if node in loop['body']:
                    continue
                loop['body'].add(node)
                stack.extend(self.preds.get(node, []))
            exits = []
            for node in self.order:
                if node in loop['body']:
                    for s in self.succ[node]:
                        if s not in loop['body'] and s not in exits:
                            exits.append(s)
            merge = self.ipdom.get(header)
            if merge == exit_node or merge in loop['body'] or merge is None:
                merge = exits[0] if exits else None
            loop['merge'] = merge
        self.lines = []
        self.depth = 1
        self.emitted = set()
        self.marked = set()
        self.labels = set()
        self.loop_stack = []

    def post_dominator(self, b):
        p = self.ipdom.get(b)
        return None if p == self.exit else p

    def emit(self, text):
        self.lines.append(INDENT * self.depth + text)

    def run(self):
        self.sequence(self.entry, set(), None)
        # Blocks reached only through a goto (secondary loop exits, irreducible flow).
        for _ in range(len(self.blocks)):
            pending = [b for b in self.labels if b not in self.emitted and b in self.blocks]
            if not pending:
                break
            for block in sorted(pending):
                if block in self.emitted:
                    continue
                self.depth = 1
                saved = self.loop_stack
                self.loop_stack = []
                self.sequence(block, set(), None)
                self.loop_stack = saved
        # Block markers become labels where a goto needs one, and disappear elsewhere.
        lines = []
        for line in self.lines:
            stripped = line.strip()
            if stripped.startswith(MARK):
                block = int(stripped[len(MARK):], 16)
                if block in self.labels:
                    lines.append('%s:' % self.printer.label(block))
                continue
            lines.append(line)
        lines = collapse_else_chains(lines)
        lines = rewrite_loops(lines)
        # A label needs a statement after it.
        lines = [line + ' ;' if line.endswith(':') and not line.startswith(' ') and label_needs_statement(lines, index)
                 else line for index, line in enumerate(lines)]
        while lines and lines[-1].strip() == 'return;':
            lines.pop()
        return lines

    def mark(self, block):
        if block not in self.marked:
            self.marked.add(block)
            self.emit('%s%x' % (MARK, block))

    def goto(self, target):
        self.labels.add(target)
        self.emit('goto %s;' % self.printer.label(target))

    def sequence(self, block, stops, follow):
        guard = 0
        while block is not None and block not in stops and guard < 100000:
            guard += 1
            if block not in self.blocks:
                return
            loop = self.loops.get(block)
            if block in self.emitted:
                if self.loop_stack and block == self.loop_stack[-1]['header']:
                    self.emit('continue;')
                else:
                    self.goto(block)
                return
            if loop is not None and loop not in self.loop_stack:
                self.mark(block)
                self.emit('while (true) {')
                self.depth += 1
                self.loop_stack.append(loop)
                self.sequence(block, set(), loop['header'])
                self.loop_stack.pop()
                while self.lines and self.lines[-1].strip() == 'continue;':
                    self.lines.pop()
                self.depth -= 1
                self.emit('}')
                block = loop['merge']
                continue
            self.emitted.add(block)
            self.mark(block)
            for line in self.printer.statements(block):
                self.emit(line)
            block = self.terminator(block, stops, follow)

    def jump(self, source, target, follow, stops):
        """Unconditional transfer: returns the block to continue with, or None."""
        if target == follow:
            return None
        if self.loop_stack:
            loop = self.loop_stack[-1]
            if target == loop['header']:
                self.emit('continue;')
                return None
            if target == loop['merge'] or target not in loop['body']:
                if target == loop['merge']:
                    self.emit('break;')
                else:
                    self.goto(target)
                return None
        if target in stops:
            return None
        if target in self.emitted:
            self.goto(target)
            return None
        return target

    def terminator(self, block, stops, follow):
        term = self.blocks[block][-1] if self.blocks[block] else None
        if isinstance(term, Ret):
            self.emit(self.printer.ret(term))
            return None
        if isinstance(term, Jump):
            return self.jump(block, term.target, follow, stops)
        if isinstance(term, IndirectJump):
            self.emit('((code *)(%s))(); /* indirect jump (unresolved table or tail call) */'
                      % self.printer.expr(term.expr))
            return None
        if isinstance(term, Branch):
            return self.branch(block, term, stops, follow)
        if isinstance(term, Switch):
            return self.switch(block, term, stops, follow)
        return None

    def loop_exit(self, target):
        if not self.loop_stack:
            return None
        loop = self.loop_stack[-1]
        if target == loop['header']:
            return 'continue'
        if target not in loop['body']:
            return 'break' if target == loop['merge'] else 'goto'
        return None

    def branch(self, block, term, stops, follow):
        cond = term.cond
        t, f = term.true, term.false
        if t == f:
            return self.jump(block, t, follow, stops)
        kind_t, kind_f = self.loop_exit(t), self.loop_exit(f)
        if kind_t or kind_f:
            if kind_t and not kind_f:
                self.emit('if (%s) {' % self.printer.cond(cond))
                self.depth += 1
                self.jump(block, t, None, set())
                self.depth -= 1
                self.emit('}')
                return self.jump(block, f, follow, stops)
            if kind_f and not kind_t:
                self.emit('if (%s) {' % self.printer.cond(negate(cond)))
                self.depth += 1
                self.jump(block, f, None, set())
                self.depth -= 1
                self.emit('}')
                return self.jump(block, t, follow, stops)
            self.emit('if (%s) {' % self.printer.cond(cond))
            self.depth += 1
            self.jump(block, t, None, set())
            self.depth -= 1
            self.emit('}')
            self.jump(block, f, None, set())
            return None
        merge = self.post_dominator(block)
        if self.loop_stack and merge is not None and merge not in self.loop_stack[-1]['body']:
            merge = None
        inner = set(stops) | ({merge} if merge is not None else set())
        if t == merge:
            cond, t, f = negate(cond), f, t
        self.emit('if (%s) {' % self.printer.cond(cond))
        self.depth += 1
        self.arm(block, t, inner, merge)
        self.depth -= 1
        if f != merge:
            self.emit('}')
            self.emit('else {')
            self.depth += 1
            self.arm(block, f, inner, merge)
            self.depth -= 1
            self.emit('}')
        else:
            self.emit('}')
        if merge is None or merge in stops:
            return None
        if merge == follow:
            return None
        if merge in self.emitted:
            self.goto(merge)
            return None
        return merge

    def arm(self, source, target, stops, merge):
        if target == merge:
            return
        kind = self.loop_exit(target)
        if kind:
            self.jump(source, target, None, set())
            return
        if target in self.emitted:
            self.goto(target)
            return
        self.sequence(target, stops, merge)

    def switch(self, block, term, stops, follow):
        merge = self.post_dominator(block)
        if self.loop_stack and merge is not None and merge not in self.loop_stack[-1]['body']:
            merge = None
        self.emit('switch (%s) {' % self.printer.expr(term.expr))
        inner = set(stops) | ({merge} if merge is not None else set())
        targets = sorted(term.cases.items(), key=lambda item: min(item[1]))
        self.loop_stack.append({'header': None, 'merge': merge, 'body': set(self.blocks) - {merge}})
        for target, values in targets:
            for value in values:
                self.emit('case %d:' % value)
            self.depth += 1
            if target == merge:
                self.emit('break;')
            elif target in self.emitted:
                self.goto(target)
            else:
                self.sequence(target, inner, merge)
                if not self.lines[-1].strip().startswith(('break;', 'return', 'goto', 'continue;')):
                    self.emit('break;')
            self.depth -= 1
        self.loop_stack.pop()
        self.emit('default:')
        self.depth += 1
        self.emit('break;' if merge is not None else '/* unreachable default */ break;')
        self.depth -= 1
        self.emit('}')
        if merge is None or merge in stops or merge == follow:
            return None
        return merge


MARK = '\x00B'


LITERAL = re.compile(r'"(?:\\.|[^"\\])*"' + r"|'(?:\\.|[^'\\])*'")


def brace_delta(line):
    """{ minus } on a line, ignoring string and character literals."""
    code = LITERAL.sub('""', line)
    return code.count('{') - code.count('}')


def label_needs_statement(lines, index):
    """True when only comments separate the label at `index` from a closing brace."""
    for line in lines[index + 1:]:
        stripped = line.strip()
        if stripped.startswith('/*') and stripped.endswith('*/'):
            continue
        return stripped.startswith('}')
    return True


def collapse_else_chains(lines):
    """'}' 'else {' 'if (...) {' ... '}' '}'  ->  '}' 'else if (...) {' ... '}' when the else holds
    exactly one if-chain (a label before the inner if keeps the braces)."""
    lines = list(lines)
    index = 0
    while index + 2 < len(lines):
        if lines[index].strip() == '}' and lines[index + 1].strip() == 'else {' and \
                lines[index + 2].strip().startswith('if ('):
            depth, end = 0, None
            for j in range(index + 2, len(lines)):
                stripped = lines[j].strip()
                depth += brace_delta(stripped)
                if depth < 0:
                    end = j
                    break
            body = lines[index + 2:end] if end is not None else []
            base = len(body[0]) - len(body[0].lstrip()) if body else 0
            depth, single = 0, bool(body)
            for k, line in enumerate(body):
                stripped = line.strip()
                indent = len(line) - len(line.lstrip())
                if k > 0 and depth == 0 and (indent <= base or not line.startswith(' ')) and \
                        not (indent == base and stripped.startswith(('}', 'else'))):
                    single = False
                    break
                depth += brace_delta(stripped)
            if single:
                indent_text = lines[index + 1][:len(lines[index + 1]) - len(lines[index + 1].lstrip())]
                rebuilt = [indent_text + 'else ' + body[0].strip()]
                rebuilt += [line[len(INDENT):] if line.startswith(INDENT) else line for line in body[1:]]
                lines[index + 1:end + 1] = rebuilt
                continue
        index += 1
    return lines


def rewrite_loops(lines):
    """while (true) { if (c) { break; } ... }  ->  while (!c) { ... }"""
    result = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip() == 'while (true) {' and index + 3 < len(lines) and lines[index + 1].strip().startswith('if (') \
                and lines[index + 1].strip().endswith(') {') and lines[index + 2].strip() == 'break;' \
                and lines[index + 3].strip() == '}':
            condition = lines[index + 1].strip()[4:-3]
            indent = line[:len(line) - len(line.lstrip())]
            result.append(indent + 'while (%s) {' % invert_text(condition))
            index += 4
            continue
        result.append(line)
        index += 1
    return rewrite_do_while(result)


def rewrite_do_while(lines):
    """while (true) { body; if (c) { continue; } break; }  ->  do { body; } while (c);"""
    result = list(lines)
    index = 0
    while index < len(result):
        line = result[index]
        if line.strip() == 'while (true) {':
            indent = line[:len(line) - len(line.lstrip())]
            depth = 0
            end = None
            for j in range(index, len(result)):
                depth += brace_delta(result[j])
                if depth == 0:
                    end = j
                    break
            if end is not None and end - index >= 5:
                tail = [l.strip() for l in result[end - 4:end]]
                if tail[0].startswith('if (') and tail[0].endswith(') {') and tail[1] == 'continue;' and \
                        tail[2] == '}' and tail[3] == 'break;' and \
                        len(result[end - 4]) - len(result[end - 4].lstrip()) == len(indent) + len(INDENT):
                    condition = tail[0][4:-3]
                    result[index] = indent + 'do {'
                    result[end - 4:end + 1] = [indent + '} while (%s);' % condition]
        index += 1
    return result


def invert_text(condition):
    pairs = [(' == ', ' != '), (' != ', ' == '), (' < ', ' >= '), (' >= ', ' < '), (' > ', ' <= '), (' <= ', ' > ')]
    if not any(op in condition for op in ('&&', '||', '?')) and condition.count('(') == condition.count(')'):
        for old, new in pairs:
            if condition.count(old) == 1 and sum(condition.count(o) for o, _ in pairs) == 1:
                return condition.replace(old, new)
    if condition.startswith('!') and condition[1:].replace('_', 'a').isalnum():
        return condition[1:]
    return '!(%s)' % condition
