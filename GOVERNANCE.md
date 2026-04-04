# Governance

## Project Owner

cadfan has final merge authority. This is a BDFL (Benevolent Dictator For Life) model appropriate for the project's current size.

## Reference Emulator Tiers

When multiple emulators produce different hashes for the same test, the tier system determines which is authoritative:

| Tier | Name | Criteria | Examples |
|------|------|----------|----------|
| 1 | Hardware-Verified | Matches real GBA hardware capture or verified FPGA core | MiSTer GBA core, real GBA + capture card |
| 2 | Consensus Emulator | Passes 100% of Tier 1 suites, widely adopted | NanoBoyAdvance |
| 3 | Community Reference | Passes known-good suites, actively maintained | mGBA |
| 4 | Experimental | New emulator or WIP | Any new submission |

Higher tier wins in disputes. If no hardware data exists, the dispute is tracked as an open issue until hardware verification is available.

## Hash Dispute Resolution

1. Open an issue using the "Hash Disagreement" template
2. Provide: emulator name, version, commit, BIOS mode, the hash you produced
3. Include a screenshot if the visual output looks correct
4. 7-day comment period for technical discussion
5. Project owner decides based on the tier system

Both hashes may be added as valid references if the disagreement is due to legitimate timing differences (documented in the manifest as `timing_sensitive = true`).

## Adding a Reference Emulator

To propose a new emulator as a Tier 2 or Tier 3 reference:

1. Open an issue with: emulator name, version, pass rate against existing suites
2. Demonstrate provenance: version, commit SHA, BIOS mode used
3. 7-day comment period
4. Project owner merges or requests changes

## Versioning

- Tooling (compare.py, runners): semver (breaking CLI = major, new feature = minor, bugfix = patch)
- Test data (manifests, references): tagged releases (v0.1.0, v0.2.0, etc.)
- Schema: versioned in-file (schema_version field). New required fields = schema bump.
