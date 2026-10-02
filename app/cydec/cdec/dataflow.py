"""Data-flow passes on a lifted function: propagation, dead code, return value, variables.

Definitions are statements (Assign, Clobber) identified by (block, index). Reaching
definitions are computed with the classic iterative bit-vector algorithm (Python sets),
then:

1. `propagate`: a use is replaced by the defining expression when exactly one definition
   reaches it and moving the expression is safe (no intervening redefinition of its
   variables, no memory write between a load and its use, calls never move). Flags are
   always propagated so every Cond(cc, flags) becomes a real comparison.
2. `eliminate`: liveness-based dead assignment removal (a dead call keeps its call).
3. `webs`: the definitions reaching common uses are merged into variables, which gives
   independent variables for unrelated reuses of the same register or stack slot.
"""
from .ir import (Assign, Branch, Call, Clobber, Comment, Cond, Const, ExprStmt, Flags, IndirectJump, Jump, Ret,
                 Store, Switch, Var, simplify)

CHEAP = (Var, Const)


class Program:
    def __init__(self, lifted):
        self.f = lifted
        self.float_return = 0
        self.blocks = lifted.blocks
        self.order = lifted.order
        self.succ = lifted.succ
        self.preds = {b: [] for b in self.order}
        for b in self.order:
            for s in self.succ.get(b, []):
                if s in self.preds:
                    self.preds[s].append(b)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def defined(statement):
        if isinstance(statement, Assign):
            return [statement.dst.name]
        if isinstance(statement, Clobber):
            return list(statement.names)
        return []

    @staticmethod
    def used(statement):
        names = set()
        for expr in statement.exprs():
            names |= expr.vars()
        return names

    def reaching(self):
        """IN sets per block: set of (var, block, index) definitions; ENTRY defs use block None."""
        gen = {}
        kill_vars = {}
        for b in self.order:
            last = {}
            for i, s in enumerate(self.blocks[b]):
                for name in self.defined(s):
                    last[name] = (name, b, i)
            gen[b] = set(last.values())
            kill_vars[b] = set(last)
        all_vars = set()
        for b in self.order:
            for s in self.blocks[b]:
                all_vars |= set(self.defined(s)) | self.used(s)
        entry = {(v, None, -1) for v in all_vars}
        IN = {b: set() for b in self.order}
        OUT = {b: set(gen[b]) for b in self.order}
        changed = True
        while changed:
            changed = False
            for b in self.order:
                new_in = set(entry) if b == self.order[0] else set()
                for p in self.preds[b]:
                    new_in |= OUT[p]
                new_out = gen[b] | {d for d in new_in if d[0] not in kill_vars[b]}
                if new_in != IN[b] or new_out != OUT[b]:
                    IN[b], OUT[b] = new_in, new_out
                    changed = True
        return IN

    def use_defs(self):
        """Map (block, index, var) -> set of definitions reaching that use."""
        IN = self.reaching()
        result = {}
        for b in self.order:
            current = {}
            for d in IN[b]:
                current.setdefault(d[0], set()).add(d)
            for i, s in enumerate(self.blocks[b]):
                for name in self.used(s):
                    result[(b, i, name)] = set(current.get(name, set()))
                for name in self.defined(s):
                    current[name] = {(name, b, i)}
        return result

    def statement(self, definition):
        _, b, i = definition
        return None if b is None else self.blocks[b][i]

    # ------------------------------------------------------------------ propagation

    def propagate(self, rounds=8):
        for _ in range(rounds):
            if not self._propagate_once():
                break
        for b in self.order:
            self.blocks[b] = [s.map_exprs(simplify) for s in self.blocks[b]]

    def _propagate_once(self):
        use_defs = self.use_defs()
        uses_of = {}
        for (b, i, name), defs in use_defs.items():
            for d in defs:
                uses_of.setdefault(d, []).append((b, i))
        changed = False
        for b in self.order:
            statements = self.blocks[b]
            for i, s in enumerate(statements):
                names = self.used(s)
                if not names:
                    continue
                mapping = {}
                for name in names:
                    defs = use_defs.get((b, i, name), set())
                    if len(defs) != 1:
                        continue
                    d = next(iter(defs))
                    if d[1] is None:
                        continue
                    source = self.statement(d)
                    if not isinstance(source, Assign):
                        continue
                    expr = source.src
                    if isinstance(expr, Call) or expr.has_call():
                        continue
                    if (d[1], d[2]) == (b, i):
                        continue
                    flags = isinstance(expr, Flags) or name == 'flags'
                    single_use = len(uses_of.get(d, [])) == 1
                    if not (single_use or isinstance(expr, CHEAP) or flags):
                        continue
                    if not self.safe_move(d, (b, i), expr):
                        continue
                    mapping[name] = expr
                if mapping:
                    statements[i] = s.map_exprs(lambda e, m=mapping: simplify(e.subst(m)))
                    changed = True
        return changed

    def safe_move(self, d, target, expr):
        """Moving `expr` from definition d to statement target keeps its value."""
        _, db, di = d
        tb, ti = target
        variables = expr.vars()
        loads = expr.has_load()
        # A self-referential definition (x = x * y) cannot move past itself.
        if set(self.defined(self.blocks[db][di])) & variables:
            return False
        if db == tb and di < ti:
            for s in self.blocks[db][di + 1:ti]:
                if set(self.defined(s)) & variables:
                    return False
                if loads and isinstance(s, (Store, ExprStmt)) or loads and isinstance(s, Assign) and s.src.has_call():
                    return False
            return True
        if loads:
            return False
        # Across blocks: the variables must not be redefined after d in its block, nor anywhere
        # on a path from d to the target. Approximation: no other definition of them exists in
        # the function (single-definition variables), parameters included.
        for s in self.blocks[db][di + 1:]:
            if set(self.defined(s)) & variables:
                return False
        for b in self.order:
            for i, s in enumerate(self.blocks[b]):
                if (b, i) == (db, di):
                    continue
                if set(self.defined(s)) & variables:
                    return False
        # The target must be reached only through d: d's block dominates the target block.
        return self.dominates(db, tb)

    def dominators(self):
        if hasattr(self, '_dom'):
            return self._dom
        order = self.order
        dom = {b: set(order) for b in order}
        dom[order[0]] = {order[0]}
        changed = True
        while changed:
            changed = False
            for b in order[1:]:
                preds = [p for p in self.preds[b] if p in dom]
                new = set(order)
                for p in preds:
                    new &= dom[p]
                new |= {b}
                if not preds:
                    new = {b}
                if new != dom[b]:
                    dom[b] = new
                    changed = True
        self._dom = dom
        return dom

    def dominates(self, a, b):
        return a in self.dominators().get(b, set())

    # ------------------------------------------------------------------ liveness / DCE

    def liveness(self):
        use = {}
        defs = {}
        for b in self.order:
            u, d = set(), set()
            for s in self.blocks[b]:
                u |= self.used(s) - d
                d |= set(self.defined(s))
            use[b], defs[b] = u, d
        live_in = {b: set() for b in self.order}
        live_out = {b: set() for b in self.order}
        changed = True
        while changed:
            changed = False
            for b in reversed(self.order):
                out = set()
                for s in self.succ.get(b, []):
                    out |= live_in.get(s, set())
                new_in = use[b] | (out - defs[b])
                if new_in != live_in[b] or out != live_out[b]:
                    live_in[b], live_out[b] = new_in, out
                    changed = True
        return live_in, live_out

    def eliminate(self):
        changed = True
        while changed:
            changed = False
            _, live_out = self.liveness()
            for b in self.order:
                live = set(live_out[b])
                kept = []
                for s in reversed(self.blocks[b]):
                    if isinstance(s, Assign):
                        if s.dst.name not in live:
                            if s.src.has_call():
                                call = next(n for n in s.src.walk() if isinstance(n, Call))
                                s = ExprStmt(call, s.address)
                            else:
                                changed = True
                                continue
                        else:
                            live.discard(s.dst.name)
                    elif isinstance(s, Clobber):
                        live -= set(s.names)
                        changed = changed or False
                        kept.append(s)
                        continue
                    live |= self.used(s)
                    kept.append(s)
                kept.reverse()
                if len(kept) != len(self.blocks[b]):
                    changed = True
                self.blocks[b] = kept
        for b in self.order:
            self.blocks[b] = [s for s in self.blocks[b] if not isinstance(s, Clobber)]

    # ------------------------------------------------------------------ return value

    def decide_return(self):
        """Keep `return rax` only when a real (non-call, non-clobber) value reaches a return."""
        use_defs = self.use_defs()
        ret = self.f.ret_reg
        returns = False
        wide = False
        size = 0

        def real(source):
            if not isinstance(source, Assign):
                return False
            if isinstance(source.src, Call):
                return source.src.returns is True
            return 'callret' not in source.src.vars()
        for b in self.order:
            for i, s in enumerate(self.blocks[b]):
                if isinstance(s, Ret) and s.value is not None:
                    for d in use_defs.get((b, i, ret), set()):
                        source = self.statement(d)
                        if real(source):
                            returns = True
                            size = max(size, value_size(source.src))
                    if self.f.word == 4:
                        for d in use_defs.get((b, i, 'edx'), set()):
                            source = self.statement(d)
                            if isinstance(source, Assign) and real(source) and returns:
                                wide = True
        if self.f.word == 4:
            if wide:
                size = 8
            else:
                for b in self.order:
                    self.blocks[b] = [Ret(Var('eax', 4), s.address, s.fvalue) if isinstance(s, Ret) and s.value is not None
                                      else s for s in self.blocks[b]]
        self.float_return = 0
        if not wide:
            float_size = self.float_return_size(use_defs, returns)
            if float_size:
                size = float_size
                for b in self.order:
                    self.blocks[b] = [Ret(s.fvalue, s.address) if isinstance(s, Ret) and s.fvalue is not None
                                      else s for s in self.blocks[b]]
                self.returns = True
                self.float_return = self.return_size = size
                return True
        # The floating-point candidate is not the return value.
        for b in self.order:
            self.blocks[b] = [Ret(s.value, s.address) if isinstance(s, Ret) and s.fvalue is not None else s
                              for s in self.blocks[b]]
        if wide:
            self.returns = True
            self.return_size = 8
            return True
        if not returns:
            for b in self.order:
                self.blocks[b] = [Ret(None, s.address) if isinstance(s, Ret) else s for s in self.blocks[b]]
        elif size and size < self.f.word:
            from .ir import Cast
            for b in self.order:
                self.blocks[b] = [Ret(Cast('trunc', s.value, size), s.address) if isinstance(s, Ret) and s.value is not None
                                  else s for s in self.blocks[b]]
        self.returns = returns
        self.return_size = size or self.f.word
        return returns

    def float_return_size(self, use_defs, int_returns):
        """4 / 8 when the floating-point candidate (xmm0 / st0) is the return value, else 0.

        It must be a computed floating-point value on every path (parameters passed through
        count only alongside one). When the integer register also holds a real value, the
        floating-point value must be written after it and be used by the returns only."""
        size = 0
        seen = False
        other_uses = None
        for b in self.order:
            for i, s in enumerate(self.blocks[b]):
                if not isinstance(s, Ret) or s.fvalue is None:
                    continue
                if not isinstance(s.fvalue, Var):
                    return 0
                seen = True
                kind = self.float_source(use_defs, (b, i), s.fvalue.name, 6)
                if kind in (0, NEUTRAL):
                    return 0
                if int_returns:
                    # Both registers hold a value: the one only feeding the return (or its own
                    # accumulation) is the result; if both qualify, the one written last.
                    if other_uses is None:
                        other_uses = self.uses_besides_returns(use_defs)
                    float_defs = use_defs.get((b, i, s.fvalue.name), set())
                    int_defs = {d for d in use_defs.get((b, i, self.f.ret_reg), set()) if d[1] is not None}
                    float_only = not (float_defs & other_uses)
                    int_only = not (int_defs & other_uses)
                    if not float_only:
                        return 0
                    if int_only:
                        last_int = max((self.statement(d).address for d in int_defs), default=-1)
                        last_float = max((self.statement(d).address for d in float_defs if d[1] is not None),
                                         default=-1)
                        if last_int > last_float:
                            return 0
                size = max(size, kind)
        if not seen:
            return 0
        return size if size in (4, 8) else 8

    def uses_besides_returns(self, use_defs):
        """Definitions read somewhere other than a return or their own update (x = x + ...)."""
        used = set()
        for (ub, ui, name), reaching in use_defs.items():
            s = self.blocks[ub][ui]
            if isinstance(s, Ret):
                continue
            if isinstance(s, Assign) and s.dst.name == name:
                continue
            used |= reaching
        return used

    def float_source(self, use_defs, at, name, depth):
        """What reaches `name` at statement `at`: 4 / 8 (float / double), FLOAT_UNKNOWN (floating
        point of unknown width), NEUTRAL (an entry value passed through) or 0 (not floating point).
        Follows plain copies (e.g. through a stack variable)."""
        from .ir import Intrinsic
        b, i = at
        defs = use_defs.get((b, i, name), set())
        if not defs:
            return 0
        size = NEUTRAL
        for d in defs:
            if d[1] is None:
                kind = NEUTRAL if name.startswith(('xmm', 'home_', 'param_')) or \
                    (name[:1] == 'v' and name[1:].isdigit()) else 0
            else:
                source = self.statement(d)
                if not isinstance(source, Assign):
                    return 0
                src = source.src
                if isinstance(src, Intrinsic) and src.name in ('_mm_set_sd', '_mm_set_ss') and src.args and \
                        isinstance(src.args[0], Call):
                    src = src.args[0]
                if isinstance(src, Call):
                    kind = src.float
                elif isinstance(src, Var) and depth > 0:
                    kind = self.float_source(use_defs, (d[1], d[2]), src.name, depth - 1)
                    if kind == NEUTRAL:
                        # An explicit copy of a parameter into the register (return a or b).
                        kind = src.size if src.size in (4, 8) else FLOAT_UNKNOWN
                else:
                    kind = float_kind(src)
            if not kind:
                return 0
            size = max(size, kind)
        return size

    # ------------------------------------------------------------------ webs

    def webs(self):
        """Rename each variable by web: definitions reaching common uses share a name."""
        use_defs = self.use_defs()
        parent = {}

        def find(x):
            while parent.setdefault(x, x) != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            parent[find(x)] = find(y)
        for key, defs in use_defs.items():
            defs = list(defs)
            for d in defs[1:]:
                union(defs[0], d)
            for d in defs:
                find(d)
        for b in self.order:
            for i, s in enumerate(self.blocks[b]):
                for name in self.defined(s):
                    find((name, b, i))
        groups = {}
        for d in parent:
            groups.setdefault(find(d), []).append(d)
        names = {}
        counter = {}
        live_in_names = {}
        for root, members in groups.items():
            if any(m[1] is None for m in members):
                counter[root[0]] = 1     # the entry value keeps the bare name
        for root, members in groups.items():
            var = root[0]
            entry = any(m[1] is None for m in members)
            if entry:
                live_in_names[var] = var
                for m in members:
                    names[m] = var
                continue
            counter[var] = counter.get(var, 0) + 1
            label = var if counter[var] == 1 else '%s_%d' % (var, counter[var])
            for m in members:
                names[m] = label
        # Rewrite definitions and uses.
        for b in self.order:
            new = []
            for i, s in enumerate(self.blocks[b]):
                mapping = {}
                for name in self.used(s):
                    defs = use_defs.get((b, i, name), set())
                    if defs:
                        label = names.get(next(iter(defs)), name)
                        if label != name:
                            mapping[name] = Var(label, size_of_use(s, name))
                if mapping:
                    s = s.map_exprs(lambda e, m=mapping: e.subst(m))
                if isinstance(s, Assign):
                    label = names.get((s.dst.name, b, i), s.dst.name)
                    if label != s.dst.name:
                        s = Assign(Var(label, s.dst.size), s.src, s.address)
                new.append(s)
            self.blocks[b] = new
        self.live_in = set(live_in_names)
        return self.live_in

    def materialize_flags(self):
        """Cond(cc, flags) whose flags come from another block (or several definitions) becomes a
        boolean variable computed right after each reaching flag definition."""
        from .ir import Cast, resolve_cond
        use_defs = self.use_defs()
        inserts = {}
        replacements = {}
        counter = 0
        for b in self.order:
            for i, s in enumerate(self.blocks[b]):
                conds = []
                for expr in s.exprs():
                    conds += [n for n in expr.walk() if isinstance(n, Cond) and isinstance(n.flags, Var)]
                for cond in conds:
                    defs = use_defs.get((b, i, cond.flags.name), set())
                    if not defs or any(d[1] is None for d in defs):
                        continue
                    sources = [self.statement(d) for d in defs]
                    if not all(isinstance(x, Assign) and isinstance(x.src, Flags) for x in sources):
                        continue
                    counter += 1
                    name = 'cond%d_%s' % (counter, cond.cc)
                    for d, source in zip(defs, sources):
                        resolved = resolve_cond(cond.cc, source.src)
                        if resolved is None:
                            break
                        inserts.setdefault((d[1], d[2]), []).append(Assign(Var(name, 1), Cast('zext', resolved, 1), source.address))
                    else:
                        replacements.setdefault((b, i), []).append((cond, Var(name, 1)))
        if not inserts:
            return
        for (b, i), pairs in replacements.items():
            def swap(e, pairs=pairs):
                for cond, var in pairs:
                    e = replace_node(e, cond, var)
                return e
            self.blocks[b][i] = self.blocks[b][i].map_exprs(swap)
        for b in self.order:
            new = []
            for i, s in enumerate(self.blocks[b]):
                new.append(s)
                new.extend(inserts.get((b, i), []))
            self.blocks[b] = new
        self.__dict__.pop('_dom', None)

    def run(self):
        self.decide_return()
        self.materialize_flags()
        self.propagate()
        self.eliminate()
        self.propagate()
        self.eliminate()
        self.webs()
        return self


NEUTRAL = -2          # float_source: an entry value passed through unchanged
FLOAT_UNKNOWN = -1    # floating point, width unknown (packed operation used on a scalar)


def float_kind(e):
    """4 / 8 when e is visibly a float / double value (scalar or the low lane of an SSE op)."""
    from .ir import Bin, Cast, FConst, Intrinsic, Load
    if isinstance(e, FConst):
        return e.size if e.size in (4, 8) else 8
    if isinstance(e, Load) and e.float:
        return e.size if e.size in (4, 8) else 8
    if isinstance(e, Bin) and e.op.endswith('f'):
        return e.size if e.size in (4, 8) else 8
    if isinstance(e, Cast) and e.kind in ('i2f', 'f2f'):
        return e.size if e.size in (4, 8) else 8
    if isinstance(e, Intrinsic):
        name = e.name
        if name.startswith(('_mm_storeu', '_mm_movemask', '_mm_cvtt', '_mm_cvts')):
            return 0
        if name.endswith('_ss'):
            return 4
        if name.endswith('_sd'):
            return 8
        if name.endswith(('_ps', '_pd')):
            return FLOAT_UNKNOWN
        from .ir import FLOAT_FUNCTIONS
        if name in FLOAT_FUNCTIONS:
            return e.size if e.size in (4, 8) else 8
    if isinstance(e, Var) and e.name.startswith('fst'):
        return 8
    from .ir import Cmp, Tern
    if isinstance(e, Tern) and e.size in (4, 8) and \
            ((isinstance(e.c, Cmp) and e.c.op.endswith('f')) or float_kind(e.a) or float_kind(e.b) or
             any(isinstance(arm, Var) and (arm.name.startswith('xmm') or (arm.name[:1] == 'v' and
                                                                           arm.name[1:].isdigit()))
                 for arm in (e.a, e.b))):
        return e.size
    return 0


def replace_node(expr, target, replacement):
    if expr is target or expr == target:
        return replacement
    kids = expr.kids()
    if not kids:
        return expr
    new = [replace_node(k, target, replacement) for k in kids]
    return expr.rebuild(new) if any(a is not b for a, b in zip(new, kids)) else expr


def size_of_use(statement, name):
    for expr in statement.exprs():
        for node in expr.walk():
            if isinstance(node, Var) and node.name == name:
                return node.size
    return 8


def value_size(expr):
    from .ir import Cast
    if isinstance(expr, Cast) and expr.kind == 'zext':
        return expr.a.size
    return expr.size
