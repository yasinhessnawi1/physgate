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
   the application logic that uses it. This is a **named, intended exception** to the pointer
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
   `n(2^(1/n) − 1)` (standards §10), which holds only for independent periodic tasks with priority
   ordered by period — interrupts included, since they run above every task [the interrupt and
   resource-sharing conditions: "Rate-monotonic scheduling," Wikipedia]. At or below the bound:
   provably schedulable under rate-monotonic priority. Above it, or where those conditions do not
   hold (shared resources, an interrupt out of period order, an aperiodic source without a sourced
   minimum inter-arrival time to use as its period): use an exact test (response-time analysis)
   rather than assuming failure — the bound is sufficient, not necessary.
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

---

## Procedure: building and sizing the firmware

1. The module is its own PlatformIO project: `platformio.ini` and `src/` in the module's
   directory, with `platform = platformio/atmelavr@5.3.0`, `board = a-star32U4` (the Balboa
   32U4's ATmega32U4 and its bootloader) and `framework = arduino`. Build it with
   `pio run -d <module directory>`, written out from where the call starts. The platform, its
   toolchain and the Pololu `Balboa32U4` 1.1.2 library are in the run's recorded tool
   environment and are found without `lib_deps`. Nothing else is, and nothing is downloaded: the
   Pololu IMU drivers (`LSM6`, `LIS3MDL`) are not there, so the library's balancing example does
   not build as it stands. Name a platform, board or library that is missing in the module's
   spec.
2. Warnings (standards §7): `build_src_flags = -Wall -Wextra -Wpedantic -Wconversion`, with all
   of the module's code under `src/`, the only code these flags reach [PlatformIO 6.2
   documentation, "build_src_flags"]; `build_flags` would reach the framework and the library
   too. The library's headers, included from `src/`, warn under `-Wpedantic` and `-Wconversion`,
   so `-Werror` fails the build on code outside the module: build without it, and show from the
   output that no warning lies in the module's own files [each setting built with PlatformIO
   6.2.0 and atmelavr 5.3.0]. A build prints warnings only for the files it compiles, so take them
   from a build into a directory no earlier build used (step 3), with its output kept:
   `PLATFORMIO_BUILD_DIR="$TMPDIR/fw-w1" pio run -d <module directory> > "$TMPDIR/fw-w1.log" 2>&1`.
   Then `grep -E '^src/[^ :]+:[0-9]+:[0-9]+: (warning|error)' "$TMPDIR/fw-w1.log"` lists the
   module's own (they print relative to the module; the library's print with absolute paths, and
   the `In file included from src/…` lines before them do not match), and
   `grep -cE '^[^ ]+:[0-9]+:[0-9]+: warning:' "$TMPDIR/fw-w1.log"` counts all of them: report both,
   and the files the others are in. No static analyser is in the environment (`pio check` would have to
   fetch `tool-cppcheck`): state the analyser run as not shown, with that reason (standards §12).
3. The build goes where the session's environment puts it (`PLATFORMIO_BUILD_DIR`, outside the
   worktree), which the session cannot read. To read a build's products (an `.elf`, `.su`
   files), give that build a directory under `$TMPDIR`: `PLATFORMIO_BUILD_DIR="$TMPDIR/fw" pio
   run -d <module directory>`. Never set `build_dir` or `workspace_dir` in `platformio.ini`,
   never build into the module, and never commit a `.pio/` directory, an `.elf` or a `.hex`:
   build output is not design state.
4. The build has no git: an `extra_scripts` step that runs `git describe` fails. Put a version in
   a constant.
5. Report size from the build's own summary, in bytes: `RAM: … (used N bytes from 2560 bytes)`
   and `Flash: … (used N bytes from 28672 bytes)`, the flash measured against the 28,672 bytes
   the bootloader leaves. `pio run -t size` prints the same bytes, but its `Program` percentage is
   of the chip's whole 32,768 bytes: quote bytes. The RAM figure is static data only (`.data`,
   `.bss`, `.noinit`); the stack comes out of what is left. For its worst case, build in an
   environment of its own without LTO (`build_unflags = -flto`,
   `build_flags = -fstack-usage -save-temps=obj`; `pio run` builds every environment, `-e <name>`
   one). Each `.su` file holds the frames of one file's functions; the calls between them come
   from the `.s` file beside it (`call`, `rcall`, `jmp`, `rjmp`), under `$TMPDIR/fw/<env>/src/`.
   Name each indirect call (`icall`, `eicall`) and each interrupt vector, with how it is bounded.
   Combine the per-function figures along the deepest call path and the deepest interrupt's with
   a script in the module, and compare the sum with what is left. That build is another binary
   (its flash and RAM differ): say which binary the figure is of. The argument holds only because
   the code has no recursion (standards §1) and keeps the heap out of steady-state operation
   (standards §2).

## On target, with no board and no simulator

No board is attached to a session: upload, programming, fuse, bootloader, erase and serial
monitor commands are refused, and serial devices are closed. This environment provides no
simulator of the target, so on-target behaviour (a loop's timing, a fault's timing) is stated as
not shown in this run, with that reason (standards §12). Nor does it record a host compiler, and
`pio test` runs nothing here (its `native` platform is not installed, and a session may only
build tests). The evidence is the strict build, its size, and a model check of the law's
arithmetic (the next procedure); that the compiled logic ran is stated as not shown.

## Procedure: checking the control law's arithmetic and the trips without a host compiler

1. Write a model of the module's law, and of each trip the diff changes, in a script under the
   module, run with the session's `python3`, that computes as the compiled code does (avr-gcc 7.3
   on this chip): `int` is 16 bits and `long` 32, `char` is signed unless declared `unsigned`, and
   each intermediate result follows C's integer promotion and truncates (an `int16_t * int16_t`
   product is 16 bits, even when assigned to an `int32_t`, unless an operand is cast wider first;
   an integer literal too large for `int`, such as `40000`, makes its expression 32-bit); `float`
   and `double` are both 32-bit (numpy's `float32`, not Python's `float`); `/` truncates toward
   zero while `>>` floors (Python's and numpy's `//` floor), and `%` takes the dividend's sign
   (`np.fmod`, not numpy's `%`); saturation and the order of operations as in the source. numpy
   does not promote as C does (a `uint8` product stays 8-bit, where C computes it in `int`;
   `int16` with `uint16` gives `int32`, where C gives a 16-bit `unsigned int`): set each
   intermediate's type explicitly to the one C computes in. Signed overflow is undefined in C
   (avr-gcc folds `a + 1 > a` to true): the script checks that no signed intermediate leaves its
   type's range over the inputs, and states the range checked. Use numpy's fixed-width integers,
   or explicit wrapping and clamping: Python's own integers never overflow. The script reads the
   code's constants from the module's source, and the designer's coefficients from control's
   node; neither is retyped.
2. Run it over the inputs the spec names and the ends of each input's range, against the same law
   in floating point with the designer's coefficients; report the largest difference with its
   unit, and every clamp or wrap the inputs reach. Exercise each trip in the model (the tilt
   limit, the command timeout, the sensor-fault rule) with the values the specification gives, on
   both sides of each limit, and show the outputs it commands going off. A forced reset and a
   physically disconnected sensor are stated as not shown, with the reason (DS-12).
3. Label the result as a model of the code, not the compiled code. Change the model with the
   code: a model that departs from the code is a finding.

## What a session's checks refuse

- `git`, in any form: the orchestrator commits.
- A `pio` command or option outside its build-only uses, and a word of `pio`'s that only running
  decides (`-d "$W"`): write the words out.
- Reads of the environment's store (`$PLATFORMIO_CORE_DIR`, the library's sources among it) and
  of the session's home.
- After a `cd` to a bare relative path, any relative word that could name a device (`*.su`,
  `USBCore`): use paths from where the call starts.

## Antipatterns: build and size

- **A size as a percentage with no denominator.** 12.5 % and 10.9 % are the same 3,570 bytes of
  flash against two totals.
- **"RAM fits" because the static figure is under 2,560 bytes.** The stack still has to fit in
  what is left, at its deepest.
- **A library in `lib_deps` by its registry name**, even the installed one: written as
  `pololu/Balboa32U4@1.1.2`, it is fetched again, and the build fails on the download, not on the
  code.
- **"Verified on target" for what was only built or modelled.** Say what ran, and that on-target
  behaviour was not shown.
- **A model check reported as a test of the code.** It shows the arithmetic, not that the compiled
  logic ran.
