# Acknowledgements

This project aggregates test ROM suites created by different authors. We do not redistribute ROM binaries. The download script fetches them from their original repositories.

## Test Suite Authors

| Suite | Author | License | Repository |
|-------|--------|---------|------------|
| jsmolka/gba-tests | jsmolka | MIT | [jsmolka/gba-tests](https://github.com/jsmolka/gba-tests) |
| ARMWrestler | destoer (fixed), mic- (original) | **Unlicensed** (see note) | [destoer/armwrestler-gba-fixed](https://github.com/destoer/armwrestler-gba-fixed) |
| FuzzARM | DenSinH | MIT | [DenSinH/FuzzARM](https://github.com/DenSinH/FuzzARM) |
| mgba-suite | endrift | MPL-2.0 | [mgba-emu/suite](https://github.com/mgba-emu/suite) |

## License Notes

**ARMWrestler:** The original ARMWrestler by mic- and the fixed version by destoer do not include an explicit license file. The ROMs are widely used in the GBA emulator community for testing. If the author objects to inclusion, please open an issue and we will remove the suite immediately.

## Reference Emulators

- **mGBA** by endrift (MPL-2.0) — V1 reference hashes generated from mGBA 0.10
- **NanoBoyAdvance** by fleroviux (MIT) — Planned gold-standard reference for v2

## Prior Art

- [c-sp/game-boy-test-roms](https://github.com/c-sp/game-boy-test-roms) — The Game Boy equivalent of this project. Inspired the curation model.
- [GBATEK](https://problemkaputt.de/gbatek.htm) by Martin Korth — The definitive GBA hardware reference.
