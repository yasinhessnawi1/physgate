"""The cross-check's tolerance, frozen before any comparison was run.

The discrete loop's margins are checked against the continuous control scorer's, the
zero-order hold taken there as a delay of half a period. That approximation is exact to
first order in ``ω·T``; its phase error at a crossover ``ω_c`` is of order ``(ω_c·T)³/24``
rad and its gain error of order ``(ω·T)²/24``. On the fixtures, whose crossovers lie at
``ω·T`` of 0.2 or less, both are well under the bounds below, which leave room for the
continuous scorer's grid and the Padé-free exact delay on either side.
"""

#: The largest difference in phase margin, degrees.
PHASE_MARGIN_DEGREES = 1.0
#: The largest relative difference in the downward gain margin.
GAIN_MARGIN_RELATIVE = 0.05
#: The fixtures' largest ``ω·T`` at a crossover, for which the tolerance is stated.
LARGEST_OMEGA_T = 0.2
