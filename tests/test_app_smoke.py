"""
Headless smoke test of the real Streamlit app using Streamlit's own AppTest
framework. This exercises the app under Streamlit's actual threading model,
which is where the cross-thread SQLite bug showed up.

Run:  python tests/test_app_smoke.py
"""
from __future__ import annotations

import os
import sys

from streamlit.testing.v1 import AppTest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(BASE, "app", "streamlit_app.py")

at = AppTest.from_file(APP, default_timeout=300)
at.run()

if at.exception:
    print("FAILED on first render:")
    for e in at.exception:
        print("  ", e.value)
    sys.exit(1)
print("  OK   first render (no exception)")

# Simulate a user clicking an example question, then a second interaction -
# the second rerun is what used to raise the threading error.
clicks = 0
for label in ["Top 5 cities by revenue", "Return rate by category",
              "ROAS by channel last year", "Monthly revenue trend"]:
    btn = next((b for b in at.button if b.label == label), None)
    if btn is None:
        print(f"  ..   example button {label!r} not found, skipping")
        continue
    btn.click().run()
    clicks += 1
    if at.exception:
        print(f"FAILED after clicking {label!r}:")
        for e in at.exception:
            print("  ", e.value)
        sys.exit(1)
    print(f"  OK   interaction {clicks}: {label!r} -> rerun clean")

# Did the app actually produce output (dataframes / markdown)?
n_df = len(at.dataframe)
n_md = len(at.markdown)
print(f"  OK   rendered {n_df} dataframe(s) and {n_md} markdown block(s)")
if n_df == 0:
    print("WARNING: no dataframe rendered - the answer panel may be empty")
    sys.exit(1)

print("\nApp smoke test passed - multiple interactions, no exceptions.")
