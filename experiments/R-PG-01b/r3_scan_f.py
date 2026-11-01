"""R3, before the run: nothing that states an answer is readable from where a reviewer runs.
Usage: r3_scan.py <checkout> <review-root> <run-dir> <install-dir>
Read-only. Exit 0 only if every check holds; prints one JSON line."""
import hashlib, json, sys
from pathlib import Path
from physgate.evaluation.inject.corpus import load_corpus
from physgate.reviewers.places import require_review_root

checkout, root, run, install = (Path(a).expanduser().resolve() for a in sys.argv[1:5])
corpus_dir = checkout / "corpora" / "injected-errors" / "v1-fullsheet"
corpus = load_corpus(corpus_dir)
problems = []
require_review_root(root)  # raises: telltale word in the path, or inside a git checkout
if root.exists() and any(root.iterdir()):
    problems.append("review root exists and is not empty")
for name, p in (("corpus", corpus_dir), ("run", run), ("install", install), ("checkout", checkout)):
    if p == root or root in p.parents or p in root.parents:
        problems.append(f"{name} and the review root contain one another")
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
answer_hashes = {sha(p) for p in corpus_dir.rglob("*") if p.is_file()}
# What a reviewer is shown besides its artefact: the library under knowledge/ (rubrics included).
shown = [p for p in (checkout / "knowledge").rglob("*") if p.is_file()]
leaked = [str(p.relative_to(checkout)) for p in shown if sha(p) in answer_hashes]
if leaked:
    problems.append(f"library files equal to corpus files: {leaked[:5]}")
for p in shown:
    text = p.read_text(errors="replace")
    if corpus.manifest_sha256 in text or corpus.manifest.label in text:
        problems.append(f"{p.relative_to(checkout)} names the corpus")
print(json.dumps({"review_root": str(root), "library_files_checked": len(shown),
                  "corpus_files": len(answer_hashes), "problems": problems}, sort_keys=True))
sys.exit(1 if problems else 0)
