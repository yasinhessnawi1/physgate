# Shakedown (seeds 901 and 902, never counted)

Dry runs of every arm at commit `4dd5b1c`, before any registered cycle.

- Arm A (`fake_*`), laptop: 2/2 kills landed, 2/2 clean.
- Arm B (`real_*`), server: 2/2 mid-session, 0 harness misses, 2/2 clean. `real.err`
  holds one BrokenPipe per cycle: the held request is answered after its session
  was stopped, as designed.
- Arm C (`tool_*`), server: 2/2 mid-tool, 0 harness misses, 2/2 clean. In both
  cycles the tool's shell carried the marker at the kill, the heartbeat kept
  growing between the kill and the resume's stop, and nothing wrote after it.

On the server the binary is a copy of the pinned 2.1.272 release in the
experiment's own directory, sha256 `d81396a6…` as recorded. A first server
shakedown ran from the binary's original install path, whose directory name is
internal. Its records are kept off the repository for that reason and not
otherwise. Its counts were the same: 2/2 clean in arm B and 2/2 in arm C.

`SHA256SUMS` covers every file here. The server-side sha256 of each file copied
from the server matched.
