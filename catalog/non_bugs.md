# Non-bugs / not-yet-reproduced vehicles

## False alarms (environmental — not crashes)
Exit code 1 from `ModuleNotFoundError` (target module not installed), not a memory crash:
- `python-4/psutil-exitcode1` — psutil not installed
- `python-4/psutil__ntuples-exitcode1` — psutil not installed
- `python-4/psutil__ntuples-exitcode1-2` — psutil not installed
- `python-4/psutil__psutil_linux-exitcode1` — psutil not installed
- `python-4/uv-exitcode1` — uv not installed

## Did not reproduce on the local build matrix
Captured on a different build (`/home/ubuntu/...`); allocation timing differs, so the
exact failing `start` doesn't line up. Re-check if we get matching builds:
- `python-4/concurrent_interpreters__crossinterp-segmentation_fault`
- `python-4/fractions-segmentation_fault`
- `python-4/xml_etree_cElementTree-segmentation_fault`
