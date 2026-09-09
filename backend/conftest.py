import os
# T003: enable the X-Test-User auth bypass ONLY via the explicit test flag.
# Must be set before the app module is imported (get_current_user reads env at
# request time, but ENVIRONMENT=test must also hold per the belt & suspenders gate).
os.environ.setdefault("STW_TEST_AUTH", "1")
os.environ.setdefault("ENVIRONMENT", "test")
