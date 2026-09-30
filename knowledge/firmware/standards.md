# Firmware — standards

> **Status: DRAFT candidate, staged for review — not promoted.** Researched and drafted by the
> implementing agent (Yasin's content-authorship correction, 29.09.2026). Read
> `knowledge/cross/standards.md` first. Almost every rule here is **judgement-only**: the physics
> gate checks declared physical quantities, not code style or scheduling behaviour, so this domain's
> discipline is enforced by the role's own on-target test and the reviewer, not by the gate — stated
> plainly rather than implied, per this file's own rule 7.

## 1. Control flow stays simple and statically boundable

Avoid `goto`, `setjmp`/`longjmp`, and recursion (direct or indirect); give every loop a fixed,
statically determinable upper bound. These are rules 1 and 2 of JPL's ten rules for safety-critical
code, adopted as Flight Software's own institutional coding standard two years after publication
[G. J. Holzmann, "The Power of 10: Rules for Developing Safety-Critical Code," *IEEE Computer*,
vol. 39, no. 6, pp. 95–99, June 2006]. The reason stated there is verifiability: a human or a tool
must be able to bound a loop's behaviour by reading it, not by running it.

**Judgement-only** — no static analysis is wired into this project's gate; the on-target test and
the reviewer are the check.

## 2. No dynamic memory allocation after initialization

Do not call `malloc`/`calloc`/`realloc`/`free` (or C++ equivalents) after system startup; pre-allocate
what a component needs during initialization. This is Holzmann's rule 3, and separately Rule 21.3 of
MISRA C:2012, the safety-critical C coding standard, in its **Required** tier — "the memory
allocation and deallocation functions of `<stdlib.h>` shall not be used" — which permits a
documented, justified deviation rather than forbidding one outright the way MISRA's stricter
**Mandatory** tier would (MISRA C:2012 has three severity tiers — Mandatory, Required, Advisory —
and this rule is not in the first one) [MISRA C:2012, Rule 21.3, verified against secondary rule
references since the standard itself is paywalled]. MISRA C is not itself a certification
requirement here: ISO 26262 (automotive functional safety) references and recommends MISRA C as one
way to satisfy its own coding-guideline requirements, and IEC 61508-based software commonly uses it
to reduce systematic-fault risk, but neither standard makes MISRA C compliance itself a strict
certification gate [IEC 61508, "Functional Safety of Electrical/Electronic/Programmable Electronic
Safety-related Systems," International Electrotechnical Commission]. The rule's own rationale here
is timing determinism as much as safety either way: heap allocation and deallocation are
non-deterministic in execution time (dependent on heap state and fragmentation), which breaks a
real-time budget even when it never fails outright.

**Judgement-only.**

## 3. Every function has a bound on its size, and a stated minimum of self-checks

No function should be too large to read and verify as a unit (Holzmann's rule of thumb: printable on
a single sheet, roughly 60 lines) [Holzmann, 2006, rule 4]; functions check the return values and
parameters they are given rather than assuming success (rule 7), and carry a working minimum of
runtime assertions on their own preconditions and invariants (rule 5 — Holzmann's guidance is a
floor of roughly two assertions per function, not a ceiling).

**Judgement-only.**

## 4. Data objects are declared at the smallest scope that works

Do not widen a variable's scope beyond what it needs — prefer a local over a file-scope static,
a file-scope static over a global, and do not reuse one variable for two unrelated purposes. This
is Holzmann's rule 6, and the rationale given is as much about fault diagnosis as data-hiding: the
fewer statements that could have assigned an object's value, the fewer places a wrong value could
have come from [Holzmann, 2006, rule 6].

**Judgement-only.**

## 5. The preprocessor is used only for header inclusion and simple, complete macros

No token pasting, no variable-argument macros, no recursive macro expansion, and no macro that
expands to less than a complete syntactic unit. Conditional compilation beyond the standard
include-guard boilerplate needs a justification in the code, not just a `#ifdef` — ten independent
conditional-compilation directives multiply into up to 2¹⁰ versions of the code, each in principle
needing its own test [Holzmann, 2006, rule 8].

**Judgement-only.**

## 6. Pointer use is restricted, and a function-pointer HAL is a stated, deliberate exception to that

Holzmann's rule 9 is blunt: "no more than one level of dereferencing is allowed... Function pointers
are not permitted" [Holzmann, 2006, rule 9] — but it is not a totally blanket ban; its own text
contemplates an exception, permitting function pointers "only... if there is a strong justification
for their use, and ideally alternate means are provided to assist tool-based checkers determine flow
of control and function call hierarchies." **This project's own skill file recommends a
function-pointer-based interface for HAL and driver portability and testability**
(`knowledge/firmware/skill.md`, "HAL conventions"), which is a real, named conflict with rule 9, not
an oversight to paper over — and the resolution is exactly what that escape clause asks for: a
fixed, init-time-populated, never-reassigned vtable is a statically enumerable, unchanging
call-target set, which is the "alternate means" the rule names, not the unconstrained pointer
arithmetic it is actually defending against. State which choice was made for a given module and why,
rather than silently picking one convention and never naming the other.

**Judgement-only.**

## 7. All code compiles warning-free at the compiler's strictest setting, and is checked daily by static analysis

From day one of development, not as a pre-release cleanup: compile with every warning the toolchain
offers enabled, at its most pedantic setting, and treat any warning as something to fix rather than
suppress — including a warning believed to be the compiler's own mistake, which should still be
addressed by rewriting the code so the confusion cannot recur. Run at least one static analyzer
daily and treat a non-zero warning count from it the same way [Holzmann, 2006, rule 10].

**Judgement-only** for this project's own gate (it runs no compiler and no static analyzer over
firmware code); this rule is enforceable directly and mechanically by the firmware toolchain itself,
independent of anything this project builds — the cheapest rule on this page to actually satisfy.

## 8. An interrupt service routine does the least possible work, and never blocks

Keep interrupt handlers short: no busy-waits, no blocking I/O, no calls into functions whose
execution time is not itself bounded and known. Delegate the substantive work to a lower-priority
task or the main loop — set a flag, copy into a buffer, or post to a queue, and return
[summarized consistently across embedded practitioner guidance, e.g. Embedded.com, "5 best practices
for writing interrupt service routines"]. A slow or blocking ISR is a direct, common cause of missed
deadlines elsewhere in the system, independent of what that elsewhere schedules.

**Judgement-only.**

## 9. A watchdog timer is kicked by evidence that the system is alive, not by a timer of its own

Do not kick a watchdog from a hardware timer interrupt on a fixed schedule — that proves the timer
fired, not that the application is making progress. Kick it only when every task expected to be
alive has given some sign of forward progress since the last kick, so that one task dying still
results in a reset [pattern documented consistently in embedded watchdog practice, e.g. Interrupt
(Memfault), "A Guide to Watchdog Timers for Embedded Systems," and the "Better Embedded System SW"
series on proper watchdog use].

**Judgement-only.**

## 10. A periodic task set's schedulability is checked against its own bound, not assumed

For a set of independent periodic tasks scheduled rate-monotonically (fixed priority, shortest
period highest priority), a sufficient (not necessary) condition for every deadline to be met is
`Σ (Cᵢ/Tᵢ) ≤ n(2^(1/n) − 1)`, where `Cᵢ` is task `i`'s worst-case execution time, `Tᵢ` its period,
and `n` the number of tasks — a bound that falls toward `ln 2 ≈ 0.693` as `n` grows large
[C. L. Liu and J. W. Layland, "Scheduling Algorithms for Multiprogramming in a Hard-Real-Time
Environment," *Journal of the ACM*, vol. 20, no. 1, pp. 46–61, Jan. 1973]. This is a **sufficient**
bound: a task set below it is provably schedulable; one above it is not automatically unschedulable,
but needs an exact test (e.g. response-time analysis) rather than an assumption either way.

Separately from the provable bound, practitioner guidance is more conservative in practice: staying
near or under roughly 70% steady-state CPU utilization is commonly recommended so that timing stays
predictable under worst-case interrupt load, and moving from roughly 70% to 90% utilization has been
reported, anecdotally but consistently, to roughly double integration and debugging time on a
project, tripling near 95% [J. G. Ganssle, embedded systems consultant, cited consistently across
practitioner sources, e.g. Embedded Artistry, "Embedded Rules of Thumb"]. State the worst-case
utilization figure and which bound (the provable one, or the practitioner margin) it is being
compared against — the two are different claims and should not be conflated.

**Judgement-only until a timing-budget quantity is added to the physics gate's own vocabulary** — the
gate's catalogue does not yet name a firmware timing quantity, so a name introduced here needs adding
to that catalogue before the gate can compare it to anything. Until then, a declared timing-budget
number is unit-checked like any other quantity (cross-domain standards §1–2) but not compared against this
bound by the gate itself.

## 11. State plainly which rules above are gate-enforced and which are not

None of rules 1–10 above are gate-enforced today — say so, rather than let a role or a reviewer
assume the gate is covering scheduling and code-style discipline it does not check. Rule 7
(compiler warnings and static analysis) is the one exception worth naming precisely: it is fully
mechanically enforceable, just not by anything this project runs — it is the firmware toolchain's
own job. The gate's own enforcement (cross-domain standards §1–6) covers declared physical
quantities: units, sourced magnitude ranges, power/energy balance, propagation, and
thermal/mechanical margins. Firmware's own domain discipline — bounded control flow, no dynamic
allocation, scope discipline, preprocessor and pointer restriction, warning/analyzer cleanliness,
ISR hygiene, watchdog design, and schedulability — is judged by the on-target test, the firmware
toolchain, and the reviewer reading the trajectory, until or unless a future spec adds a
corresponding gate check.
