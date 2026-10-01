# Firmware — skill

> Procedures and antipatterns,
> reusable across firmware tasks; every numbered standard it cites lives in
> `knowledge/firmware/standards.md`, drafted alongside this file and under the same review.

## HAL conventions

Separate three layers, and do not let a caller reach past the one it needs:

1. **The vendor/driver layer** — the microcontroller vendor's own peripheral driver or register
   access, wrapped rather than called directly from application code.
2. **The hardware abstraction layer (HAL)** — a stable, hardware-independent API (e.g.
   `gpio_write(pin, level)`, `timer_start(id, period_us)`) that the application calls, with the
   vendor layer behind it. The point of the layer is that swapping a microcontroller or a board
   revision changes the HAL's implementation, not the application code that calls it
   [pattern documented consistently across embedded practitioner references, e.g. J. Beningo,
   "Creating a Hardware Abstraction Layer (HAL) in C," Embedded Related].
3. **The application/driver-pattern layer** — a function-pointer-based interface (a `struct` of
   function pointers, or a small vtable) for a peripheral driver is a common, testable way to keep
   drivers swappable and to allow a host-side unit test to substitute a fake driver without touching
   the application logic that uses it. This is a **named, deliberate exception** to the pointer
   restriction in standards §6, not an oversight — state it as one where it is used, the way
   standards §6 itself asks.

State which layer a change belongs to in the module's spec, and do not add a vendor-specific call
inside application logic "just this once" — that is exactly the coupling the layering exists to
prevent.

## Procedure: establishing a timing budget

1. Enumerate every periodic task and interrupt source with its period `Tᵢ` and its measured or
   estimated worst-case execution time `Cᵢ` (not an average — a schedulability argument needs the
   worst case).
2. Compute `Σ (Cᵢ/Tᵢ)` and compare it against the rate-monotonic sufficient bound
   `n(2^(1/n) − 1)` (standards §10). Below the bound: provably schedulable under rate-monotonic
   priority. At or above it: use an exact test (response-time analysis) rather than assuming
   failure — the bound is sufficient, not necessary.
3. Separately, check the same total against the practitioner CPU-headroom guidance (standards §10)
   and state which of the two comparisons is being reported, since they are different claims.
4. Record the enumerated tasks, their `Cᵢ`/`Tᵢ`, the utilization total, and which test it was
   compared against, in the module's spec — a "timing budget met" claim with no enumerated tasks
   behind it is not a checkable claim.

## Antipatterns

- **Reporting "timing budget met" as a bare assertion.** Without the enumerated tasks and their
  `Cᵢ`/`Tᵢ`, there is nothing for a reviewer to check the arithmetic on (skill §"Procedure: establishing
  a timing budget").
- **Measuring execution time with an average instead of a worst case.** A rate-monotonic bound is a
  worst-case argument; an average-case `Cᵢ` invalidates the whole comparison even if every other
  number is correct.
- **Kicking the watchdog from the same interrupt that is meant to detect a hang.** This proves the
  interrupt still fires, not that the monitored task is alive (standards §9).
- **Doing real work inside an ISR "because it was convenient."** The most common source of missed
  deadlines elsewhere in the system is an ISR that does not return quickly (standards §8);
  reclassifying "just a quick calculation" as deferred work is usually the fix.
- **Allocating memory dynamically during steady-state operation, even if it "usually" succeeds.**
  Fragmentation-driven allocation failure and non-deterministic allocation timing are both real
  failure modes of the same rule (standards §2), and "usually works in testing" is not evidence
  against either.
- **A function-pointer HAL that is not named as the exception it is.** The pattern itself is fine
  (HAL conventions, above), but a module that uses it without saying so, beside a standards file
  that otherwise restricts pointers to one level of dereferencing, reads as an inconsistency rather
  than a stated choice (standards §6).
- **A vendor-specific call inside application logic, justified as temporary.** This is the coupling
  the HAL layering exists to prevent, and "temporary" workarounds are the ones a codebase keeps.
