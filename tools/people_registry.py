#!/usr/bin/env python3
"""
people_registry.py - the B4-PEOPLE policy (ledger E00571) as a check later stages import.  (build: production-boundary-v1)

    from people_registry import check_text
    result = check_text(text, piece_yes={"CHILD-1"})     # Daniel's per-piece yes, by label
    result.ok            # True only when nothing was found AND the known-names list was loaded
    result.findings      # what was refused, with the rule
    result.known_names_loaded   # False => the known-person half is UNKNOWN, not clean

    py tools/people_registry.py draft.html [--yes CHILD-1]       # exit 0 clean, 1 refused, 2 could not run

THE RULES (data/people_registry.json, from E00571):
  client            never named.
  business partner  by role only.
  wife              by role only.
  children          first name only, only with Daniel's yes for THIS piece, never an age.
  Daniel's own directing, fumbles included, is fair game (nothing to check).
  Any capitalised personal name the registry does not know is refused: the program does not guess.

WHERE THE NAMES COME FROM. b4him is public, so the repo holds roles and rules only. Real names are read from
data/people_names.local.json (git-ignored) if it is present:
    {"people": [{"label": "CHILD-1", "role": "child", "names": ["Firstname"]}, ...]}
or as salted hashes in the registry's name_hashes (`py tools/people_registry.py --hash "Some Name"` prints one).
With neither, the known-person check CANNOT run; the result says so (known_names_loaded False, ok False) rather than
passing. The unknown-name heuristic still runs.

LIMITS (best effort, stated so nobody mistakes it for a guarantee):
  * Known names are matched as whole words, case-insensitively, as 1-3 word sequences, with a trailing 's removed.
    A nickname, misspelling, initial or description ("the tall one from the Henderson job") is not known to it.
  * Unknown names are found by three signals only: a run of 2+ capitalised words none of which is a safe term; a
    capitalised word on data/common_first_names.txt; a capitalised word right after "named/called", "Mr/Ms/Dr", or
    "my <relative/colleague word>". A lone surname, a lowercase name, a name inside a longer capitalised phrase that
    contains a safe term, and a name that is also a common word all slip through. Title-Case heading lines are
    exempt from the first signal (they would drown it), which is a deliberate hole.
  * Ages: a number or number-word near a child's name or a child role word, in the same sentence.
  It reads text, not images, and not what a reader could infer from several pieces taken together.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
REGISTRY_FILE = DATA / "people_registry.json"
LOCAL_NAMES_FILE = DATA / "people_names.local.json"
FIRST_NAMES_FILE = DATA / "common_first_names.txt"

WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
CAP = re.compile(r"^[A-Z][a-z]{1,}(?:[-'’][A-Z]?[a-z]+)*$")
TAG = re.compile(r"<[^>]+>")
SENTENCE_END = re.compile(r"[.!?]\s+|\n+")

#: Words that are capitalised without being people. Extendable through the registry's safe_terms.
SAFE = {w.lower() for w in """
I I'm I've I'd I'll The A An This That These Those It Its He She We They You Your My Our His Her Their There Here
When Where What Why How Who Which While If But And Or So Because Then Now Also Not No Yes One Two Three Every Each
Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April May June July August
September October November December Claude Anthropic Opus Sonnet Haiku Fable GPT Gemini Google Microsoft Windows
Linux Mac Python JavaScript HTML CSS Git GitHub Pages n8n Ollama Docker Excel Word Chrome Firefox Edge Safari
PowerShell NVIDIA OneDrive Gmail Drive Calendar Airtable Artifact Artifacts Code Tuesday Glossary Tier Module Lesson
Lessons Phase Build Gate Release Daniel Slocum B4HIM Harness Ledger Octopus Mythos Sobevista Omen Purple Team
""".split()}
CUES = re.compile(
    r"\b(?:(?:named|called|name\s+was)\s+|(?:Mr|Mrs|Ms|Miss|Dr|Prof)\.?\s+|"
    r"(?:my|our|his|her|their)\s+(?:friend|colleague|coworker|co-worker|boss|neighbou?r|cousin|brother|sister|mother|"
    r"father|mom|dad|uncle|aunt|manager|teacher|mentor|buddy)\s*,?\s+(?:(?:named|called)\s+)?)([A-Z][a-z]+)")
AGE = re.compile(r"\b(?:\d{1,2}|(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
                 r"fifteen|sixteen|seventeen|eighteen|nineteen|twenty))[- ]?(?:years?|yrs?|y/?o)[- ]?(?:old)?\b|"
                 r"\b(?:aged?|turned|turning)\s+(?:\d{1,2}|[a-z]+)\b|\b(?:age|aged)\s*[:=]?\s*\d{1,2}\b|"
                 r"\b(?:is|was|being)\s+\d{1,2}\b(?!\s*(?:%|st|nd|th|rd))|,\s*\d{1,2}\s*,", re.I)


def normalise(name: str) -> str:
    name = re.sub(r"(?:'s|’s)$", "", name.strip(), flags=re.I)
    return " ".join(w.lower() for w in WORD.findall(name))


def hash_name(name: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{normalise(name)}".encode("utf-8")).hexdigest()


class RegistryError(RuntimeError):
    pass


@dataclass
class Finding:
    kind: str          # known-outside-rule | unknown-name | age
    text: str
    rule: str
    label: str | None = None
    role: str | None = None
    offset: int = 0

    def __str__(self) -> str:
        who = f" [{self.label}/{self.role}]" if self.label else ""
        return f"{self.kind}{who}: {self.text!r} - {self.rule}"


@dataclass
class Result:
    findings: list[Finding] = field(default_factory=list)
    known_names_loaded: bool = False
    known_count: int = 0

    @property
    def ok(self) -> bool:
        """Clean AND the known-person half could run. UNKNOWN never rounds to OK."""
        return not self.findings and self.known_names_loaded

    def status(self) -> str:
        if self.findings:
            return "REFUSED"
        return "CLEAN" if self.known_names_loaded else "UNKNOWN (known-names list not loaded; only the unknown-name heuristic ran)"


class Registry:
    def __init__(self, data: dict, local: dict | None, first_names: set[str]):
        self.data = data
        self.roles = data["roles"]
        for need in ("client", "business_partner", "wife", "child", "own_directing"):
            if need not in self.roles:
                raise RegistryError(f"registry lacks the {need} role")
        self.salt = data.get("salt", "")
        self.safe = SAFE | {s.lower() for s in data.get("safe_terms", [])}
        self.first_names = first_names
        self.child_words = {w.lower() for w in data.get("role_terms", {}).get("child", [])}
        self.by_label = {p["label"]: p for p in data["people"]}
        #: {normalised name or hash: (label, role, form)} form = "first" (one word) or "full"
        self.plain: dict[str, tuple[str, str, str]] = {}
        self.hashed: dict[str, tuple[str, str, str]] = {}
        for p in data["people"]:
            for h in p.get("name_hashes", []):
                self.hashed[h["hash"] if isinstance(h, dict) else h] = (
                    p["label"], p["role"], h.get("form", "first") if isinstance(h, dict) else "first")
        for p in (local or {}).get("people", []):
            role = p.get("role") or self.by_label.get(p.get("label"), {}).get("role")
            if role not in self.roles:
                raise RegistryError(f"local names file: {p.get('label')!r} has no valid role")
            for n in p.get("names", []):
                key = normalise(n)
                if key:
                    self.plain[key] = (p.get("label", "?"), role, "first" if len(key.split()) == 1 else "full")
        self.known_names_loaded = bool(self.plain or self.hashed)

    def lookup(self, phrase: str):
        key = normalise(phrase)
        if key in self.plain:
            return self.plain[key]
        if self.salt and self.hashed:
            return self.hashed.get(hash_name(phrase, self.salt))
        return None


def load_registry(registry_path: Path | None = None, local_path: Path | None = None,
                  first_names_path: Path | None = None) -> Registry:
    try:
        data = json.loads((registry_path or REGISTRY_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RegistryError(f"people registry unreadable: {e}") from None
    lp = local_path or LOCAL_NAMES_FILE
    local = None
    if lp.exists():
        try:
            local = json.loads(lp.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise RegistryError(f"local names file unreadable ({lp}): {e}") from None
    fp = first_names_path or FIRST_NAMES_FILE
    try:
        first = {l.strip().lower() for l in fp.read_text(encoding="utf-8").splitlines() if l.strip()}
    except OSError as e:
        raise RegistryError(f"common first names list unreadable: {e}") from None
    return Registry(data, local, first)


def visible_text(text: str) -> str:
    """Drop script/style and tags so markup names (class, href) are not read as people; keep the words."""
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
    return TAG.sub(" ", text)


def _sentence_starts(text: str) -> set[int]:
    starts = {0}
    for m in SENTENCE_END.finditer(text):
        starts.add(m.end())
    return starts


def _is_heading(line: str) -> bool:
    words = [w for w in WORD.findall(line) if len(w) > 2]
    if line.lstrip().startswith("#"):
        return True
    return 2 <= len(words) <= 12 and len(line) < 100 and all(w[0].isupper() for w in words) and not line.rstrip().endswith(".")


def check_text(text: str, piece_yes=(), registry: Registry | None = None, markup: bool = True) -> Result:
    """Check `text` against the registry. `piece_yes` is the set of child labels Daniel has said yes to for this piece."""
    reg = registry or load_registry()
    raw = visible_text(text) if markup else text
    piece_yes = set(piece_yes)
    res = Result(known_names_loaded=reg.known_names_loaded, known_count=len(reg.plain) + len(reg.hashed))
    toks = [(m.group(0), m.start(), m.end()) for m in WORD.finditer(raw)]
    claimed: set[int] = set()            # token indexes already judged as a known person
    sentences = _sentence_starts(raw)
    sentence_of = lambda off: max(s for s in sentences if s <= off)          # noqa: E731

    # ---- known people: longest sequence first (3, 2, 1 words), only across plain whitespace
    child_hits: list[tuple[int, int]] = []
    i = 0
    while i < len(toks):
        hit = None
        for n in (3, 2, 1):
            if i + n > len(toks):
                continue
            seq = toks[i:i + n]
            if any(raw[seq[k][2]:seq[k + 1][1]].strip() for k in range(n - 1)):
                continue
            phrase = " ".join(t[0] for t in seq)
            found = reg.lookup(phrase)
            if found:
                hit = (n, found, phrase, seq[0][1])
                break
        if not hit:
            i += 1
            continue
        n, (label, role, form), phrase, off = hit
        claimed.update(range(i, i + n))
        rule = reg.roles[role]["rule"]
        if rule == "never":
            res.findings.append(Finding("known-outside-rule", phrase, "client: never named", label, role, off))
        elif rule == "role_only":
            res.findings.append(Finding("known-outside-rule", phrase, f"{role.replace('_', ' ')}: by role only, never by name",
                                        label, role, off))
        elif rule == "first_name_with_piece_yes":
            nxt = toks[i + n] if i + n < len(toks) else None
            surname_follows = (nxt is not None and not raw[toks[i + n - 1][2]:nxt[1]].strip()
                               and CAP.match(nxt[0]) and nxt[0].lower() not in reg.safe)
            if form == "full" or surname_follows:
                res.findings.append(Finding("known-outside-rule", phrase,
                                            "child: first name only, never a surname", label, role, off))
            elif label not in piece_yes:
                res.findings.append(Finding("known-outside-rule", phrase,
                                            "child: first name only with Daniel's yes for this piece; none given",
                                            label, role, off))
            child_hits.append((off, off + len(phrase)))
        i += n

    # ---- ages next to a child (a named child, or a child role word) in the same sentence
    child_spans = list(child_hits)
    for k, (w, s, e) in enumerate(toks):
        if w.lower() in reg.child_words:
            child_spans.append((s, e))
    for s, _ in child_spans:
        st = sentence_of(s)
        en = min([x for x in sentences if x > s] or [len(raw)])
        for m in AGE.finditer(raw[st:en]):
            res.findings.append(Finding("age", m.group(0), "child: never an age", None, "child", st + m.start()))
    # one age finding per offset
    seen, uniq = set(), []
    for f in res.findings:
        key = (f.kind, f.offset, f.text)
        if key not in seen:
            seen.add(key)
            uniq.append(f)
    res.findings = uniq

    # ---- unknown personal names (heuristic)
    starts = sentences
    line_of = {}
    pos = 0
    for line in raw.split("\n"):
        for p in range(pos, pos + len(line) + 1):
            line_of[p] = line
        pos += len(line) + 1
    flagged: set[int] = set()
    # signal 1: runs of 2+ capitalised words, none a safe term, none already a known person
    j = 0
    while j < len(toks):
        w, s, e = toks[j]
        if j in claimed or not CAP.match(w) or w.lower() in reg.safe:
            j += 1
            continue
        k = j
        while (k + 1 < len(toks) and not raw[toks[k][2]:toks[k + 1][1]].strip()
               and (k + 1) not in claimed and CAP.match(toks[k + 1][0]) and toks[k + 1][0].lower() not in reg.safe):
            k += 1
        if k > j and not _is_heading(line_of.get(s, "")):
            phrase = raw[s:toks[k][2]]
            res.findings.append(Finding("unknown-name", phrase, "a capitalised name the registry does not know", None, None, s))
            flagged.update(range(j, k + 1))
        j = k + 1
    # signal 2: a capitalised common first name, anywhere
    for idx, (w, s, e) in enumerate(toks):
        if idx in claimed or idx in flagged or not CAP.match(w):
            continue
        if w.lower() in reg.first_names and w.lower() not in reg.safe:
            res.findings.append(Finding("unknown-name", w, "a common first name the registry does not know", None, None, s))
            flagged.add(idx)
    # signal 3: cues (named X, Mr X, my friend X)
    for m in CUES.finditer(raw):
        name = m.group(1)
        if name.lower() in reg.safe or reg.lookup(name):
            continue
        s = m.start(1)
        if not any(f.offset == s for f in res.findings):
            res.findings.append(Finding("unknown-name", name, "named as a person by context; the registry does not know them",
                                        None, None, s))
    res.findings.sort(key=lambda f: f.offset)
    return res


def assert_clean(text: str, piece_yes=(), registry: Registry | None = None, require_known: bool = True) -> None:
    """For a stage that must stop: raises RegistryError unless the text is clean. With require_known (default) an
    unloaded known-names list also raises: a check that could not run is not a pass."""
    r = check_text(text, piece_yes, registry)
    if r.findings:
        raise RegistryError("; ".join(str(f) for f in r.findings))
    if require_known and not r.known_names_loaded:
        raise RegistryError("UNKNOWN: the known-names list is not loaded (data/people_names.local.json absent); "
                            "the people check could not run in full")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?")
    ap.add_argument("--yes", action="append", default=[], help="child label Daniel said yes to for this piece")
    ap.add_argument("--hash", help="print the salted hash of a name for the registry, then exit")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        reg = load_registry()
        if a.hash:
            print(hash_name(a.hash, reg.salt))
            return 0
        if not a.file:
            ap.error("a file to check is required")
        r = check_text(Path(a.file).read_text(encoding="utf-8"), set(a.yes), reg)
    except (RegistryError, OSError) as e:
        print("COULD NOT RUN:", e)
        return 2
    for f in r.findings:
        print(f)
    print(r.status())
    return 0 if r.ok else (1 if r.findings else 2)


if __name__ == "__main__":
    sys.exit(main())
