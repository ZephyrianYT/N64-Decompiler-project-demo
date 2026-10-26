# Legacy: the original concept

These files are the first concept for this project: a Banjo-Kazooie-specific
drag-and-drop wrapper (`BanjoRecomp.cpp`) around a PowerShell pipeline
(`BanjoRecomp.ps1`) that disassembled the ROM with Capstone and generated C
stubs.

They are kept for reference only. The working tool is `n64lab/` at the
top of the repository (see the main README). It does what this concept
described, minus the stubs: it translates every instruction into C, builds a
real runtime, and produces a Windows executable that runs.

The documents in this folder (`SETUP.md`, `PROJECT_OVERVIEW.md`,
`QUICK_REFERENCE.md`, `DELIVERY_SUMMARY.md`) describe the old design, not
n64lab.
