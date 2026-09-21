"""Compare two Python files for everything except type annotations and layout.

This is the part the whole workload-equivalence argument rests on, so it is
written to be read rather than to be short.

**The problem.** The seeded workload that produced the store comparison's numbers
cannot be copied into this suite unchanged: it fails the strict type checker
twenty times, the linter once and the formatter twice, and the test tree is
covered by all three. Excluding the copy would put a second hole in the fence
that keeps those tools out of the frozen tree — inside the directory where they
are meant to reach, uncovered by the tests that guard that fence, and inherited
by everything built after this. So the copy is adapted, and the adaptation has to
be proven to change nothing.

**Why an abstract syntax tree and not a diff.** Reading a hundred-and-eighteen
line diff and concluding it is "only annotations" is an eyeball, and an eyeball
is what this project is trying not to rely on. An abstract syntax tree contains
no comments, no blank lines and no line breaks, so a reformatting is invisible to
it by construction. If two trees compare equal after annotations are removed from
both, the only differences that existed were annotations, comments and layout.

**What is discounted, and why each one is safe.**

1. *Annotations.* Removed from both sides before comparing: every parameter
   annotation, every return annotation, and annotated assignments are rewritten
   to plain assignments. An annotation cannot change what runs.
2. *The ``typing.Any`` import.* The annotations that were added need a name to be
   spelled with. Removing the annotations but leaving their import would report a
   difference that exists only to serve the thing already discounted.
3. *A named rename.* One class was renamed to satisfy a linter rule about
   exception naming. The old name is rewritten to the new one in the frozen side
   before comparing, and the caller has to name the pair — a silent rename would
   let this function hide a substitution.
4. *A named import redirect.* One module-level import may be redeclared as coming
   from somewhere else, when the caller names both the symbol and the fact. The
   symbol itself is not discounted: if its call sites moved, that shows.

Everything else — a changed constant, a reordered statement, an inverted
condition, an extra call, a different argument — survives all four and makes the
comparison fail.
"""

from __future__ import annotations

import ast
from pathlib import Path


class _StripAnnotations(ast.NodeTransformer):
    """Remove every type annotation, leaving what executes."""

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        node.returns = None
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        node.returns = None
        self.generic_visit(node)
        return node

    def visit_arg(self, node: ast.arg) -> ast.AST:
        node.annotation = None
        return node

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST:
        """``x: T = v`` becomes ``x = v``; a bare ``x: T`` declares nothing to run."""
        self.generic_visit(node)
        if node.value is None:
            return ast.Pass()
        return ast.Assign(targets=[node.target], value=node.value, type_comment=None)


class _DropTypingAny(ast.NodeTransformer):
    """Remove the ``typing.Any`` import that the added annotations require."""

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST | None:
        if node.module != "typing":
            return node
        node.names = [alias for alias in node.names if alias.name != "Any"]
        return node if node.names else None


class _Rename(ast.NodeTransformer):
    """Rewrite one name to another, wherever it is bound or referenced."""

    def __init__(self, old: str, new: str) -> None:
        self.old = old
        self.new = new

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if node.id == self.old:
            node.id = self.new
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        if node.name == self.old:
            node.name = self.new
        self.generic_visit(node)
        return node


class _RedirectImport(ast.NodeTransformer):
    """Rewrite the module one named symbol is imported from."""

    def __init__(self, symbol: str, to_module: str) -> None:
        self.symbol = symbol
        self.to_module = to_module

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST:
        if any(alias.name == self.symbol for alias in node.names):
            node.module = self.to_module
        return node


def normalised(
    path: Path,
    *,
    renames: dict[str, str] | None = None,
    import_redirects: dict[str, str] | None = None,
) -> str:
    """Return a canonical form of ``path`` with annotations and layout removed.

    Args:
        path: the file to read.
        renames: old name to new name, applied before the comparison. Naming a
            rename here is how a rename is declared rather than hidden.
        import_redirects: symbol name to the module it should be treated as
            coming from. Same reasoning.

    Returns:
        A string that is equal for two files differing only in the four things
        this module's docstring lists.
    """
    tree = ast.parse(path.read_text())
    for old, new in (renames or {}).items():
        tree = _Rename(old, new).visit(tree)
    for symbol, module in (import_redirects or {}).items():
        tree = _RedirectImport(symbol, module).visit(tree)
    tree = _StripAnnotations().visit(tree)
    tree = _DropTypingAny().visit(tree)
    ast.fix_missing_locations(tree)
    return ast.dump(tree, annotate_fields=True, include_attributes=False)
