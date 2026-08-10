# Vendored third-party libraries

These libraries are vendored so the project works without installing
dependencies (`bootstrap()` in `src/common.py` adds `vendor/` to `sys.path`).
Do **not** modify them by hand — re-run `scripts/update_vendor.sh` instead.

| Package   | Version   | PyPI project             | Upstream source                                        | License      |
|-----------|-----------|--------------------------|--------------------------------------------------------|--------------|
| msgpack   | 1.1.2     | https://pypi.org/project/msgpack/    | https://github.com/msgpack/msgpack-python   | Apache 2.0  |
| flatbuffers | 25.12.19 | https://pypi.org/project/flatbuffers/ | https://github.com/google/flatbuffers        | Apache 2.0  |

- `vendor/msgpack/` — retained files: `__init__.py`, `ext.py`, `fallback.py`, `exceptions.py`. License text: `COPYING` (Apache 2.0, from upstream).
- `vendor/flatbuffers/` — retained files: `bootstrap_byte_reader`, `builder`, `compat`, `encode`, `flexbuffers`, `number_types`, `packer`, `table`, `util`, `_version` (all `.py`). License text: `LICENSE` (Apache 2.0, from upstream).

Verification: vendored files are byte-for-byte identical to the matching
PyPI wheel (`pip download --no-deps`), confirmed via `md5sum` on 2026-08-10.