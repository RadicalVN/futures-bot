import base64, os

# Full backtest.py encoded as base64
encoded = (
    "aW1wb3J0IG9zCmltcG9ydCBtYXRoCmZyb20gZGF0ZXRpbWUgaW1wb3J0IGRhdGV0aW1lLCB0aW1l"
    "em9uZSwgdGltZWRlbHRhCmZyb20gdHlwaW5nIGltcG9ydCBPcHRpb25hbApmcm9tIGZhc3RhcGkg"
    "aW1wb3J0IEFQSVJvdXRlciwgSFRUUEV4Y2VwdGlvbgpmcm9tIGZhc3RhcGkucmVzcG9uc2VzIGlt"
    "cG9ydCBGaWxlUmVzcG9uc2UKZnJvbSBweWRhbnRpYyBpbXBvcnQgQmFzZU1vZGVsCmZyb20gc3Fs"
    "YWxjaGVteSBpbXBvcnQgc2VsZWN0CmZyb20gbG9ndXJ1IGltcG9ydCBsb2dnZXIKCmZyb20gc3Jj"
    "LmRhdGFiYXNlLmRiIGltcG9ydCBnZXRfZGIKZnJvbSBzcmMuZGF0YWJhc2UubW9kZWxzIGltcG9y"
    "dCBCb3QsIEV4Y2hhbmdlQWNjb3VudApmcm9tIHNyYy5jb3JlLmV4Y2hhbmdlIGltcG9ydCBCaW5h"
    "bmNlRXhjaGFuZ2UsIGNyZWF0ZV9leGNoYW5nZV9mcm9tX2Vudgpmcm9tIHNyYy5zdHJhdGVnaWVz"
    "Lm1hX21hY2QgaW1wb3J0IE1hTWFjZFN0cmF0ZWd5CmZyb20gc3JjLnN0cmF0ZWdpZXMuY3VzdG9t"
    "X3NtYSBpbXBvcnQgQ3VzdG9tU01BU3RyYXRlZ3kKZnJvbSBzcmMuc3RyYXRlZ2llcy5jdXN0b21f"
    "bWFjZCBpbXBvcnQgQ3VzdG9tTUFDRFN0cmF0ZWd5CmZyb20gc3JjLnN0cmF0ZWdpZXMuc21hX3Ry"
    "ZW5kX2Vhcmx5X2V4aXQgaW1wb3J0IFNtYVRyZW5kRWFybHlFeGl0U3RyYXRlZ3kKZnJvbSBzcmMu"
    "c3RyYXRlZ2llcy5zbWFfcHVsbGJhY2sgaW1wb3J0IFNtYVB1bGxiYWNrU3RyYXRlZ3kKZnJvbSBz"
    "cmMuc3RyYXRlZ2llcy5zbWFfYW50aV9zaWRld2F5IGltcG9ydCBTbWFBbnRpU2lkZXdheVN0cmF0"
    "ZWd5CmZyb20gc3JjLnN0cmF0ZWdpZXMuc21hX21hY2RfY3Jvc3MgaW1wb3J0IFNtYU1hY2RDcm9z"
    "c1N0cmF0ZWd5"
)

decoded = base64.b64decode(encoded).decode('utf-8')
print(decoded[:200])
print("...")
print("Decoded OK, length:", len(decoded))
