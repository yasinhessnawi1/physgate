"""Interface contracts: which module pairs are tested, and the clause each pair is held to.

A run with the integration role tests the contract between every pair of modules that share an
interface (ARCH-051). The pairs are read from the recorded plan before any module runs
(:mod:`physgate.contracts.pairs`), so nothing the modules later write can shape the set. The
clause (:mod:`physgate.contracts.clause`) holds what each module's nodes say about an interface
quantity to what the interface node says, over the graph as the canonical journal holds it at one
revision (:mod:`physgate.contracts.graph`). Nothing here calls a model, writes a file or reads the
role register.
"""
