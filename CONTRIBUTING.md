# Contributing to gba-accuracy-tests

## Adding a Runner for Your Emulator

1. Copy `runners/TEMPLATE.py` to `runners/my_emulator.py`
2. Implement `run_test(rom_path, frames, output_path) -> bool`
3. Implement `is_available() -> bool`
4. Set `RUNNER = MyEmulatorRunner()` at module level
5. Test: `python compare.py run --runner my-emulator --suite jsmolka`
6. Submit a PR with your runner + validation output

### PR Checklist for Runners

- [ ] Runner script in `runners/`
- [ ] `is_available()` checks the emulator binary exists
- [ ] `run_test()` respects the 60-second timeout
- [ ] Output is PNG (240x160) or raw BGR555 .bin (76800 bytes)
- [ ] Validated against at least the `jsmolka` suite
- [ ] Added to the runner table in README.md

## Adding a New Test Suite

1. Create `suites/<name>/manifest.toml` following the schema in [schema.md](schema.md)
2. Create `suites/<name>/references.json` with at least one reference hash
3. Add ROM download info to `scripts/download_roms.py`
4. Provide provenance for all reference hashes

### PR Checklist for Suites

- [ ] Manifest validates (TOML parses, required fields present)
- [ ] References have full provenance metadata
- [ ] ROMs download successfully via `download_roms.py`
- [ ] ROM SHA256 in manifest matches downloaded binary
- [ ] Suite license documented in ACKNOWLEDGEMENTS.md

## Updating Reference Hashes

Use `scripts/generate_refs.py` to regenerate references from a runner:

```bash
python scripts/generate_refs.py --runner mgba --suite jsmolka
```

When submitting updated references:
- Include full provenance (emulator version, commit, BIOS mode)
- Do not remove existing references. Add alongside them.
- If your hash differs from existing references, note why in the `note` field.

## Reporting Hash Disagreements

If your emulator produces a different hash than the reference and you believe both are correct (e.g., timing-sensitive test), open an issue with:
- Your emulator name and version
- The test ID and your hash
- Whether the visual output looks correct (include a screenshot)
- Your BIOS mode (HLE, real, skip)

See [GOVERNANCE.md](GOVERNANCE.md) for how disagreements are resolved.
