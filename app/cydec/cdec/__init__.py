"""CyDecompilator's own x86/x64 C decompiler.

Pipeline: lifter (Capstone instructions -> IR with stack, flags and calling conventions)
-> dataflow (expression propagation, dead code, variables, parameters, return value)
-> structure (if/else, loops, switch, goto fallback) -> cgen (types and C text).
Ghidra remains the preferred engine when installed; this one needs nothing but Python.
"""
