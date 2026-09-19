"""Regression guard: the backend package must import cleanly.

PR #161 reverted part of the auth refactor and left ``dependencies.py``
referencing an unimported ``get_db`` and a dropped ``rotate_session``, so
``import app`` raised at module load while the suite stayed (falsely) green
behind a blanket ``except Exception`` in ``conftest._EnsuringClient``. This
test pins the fix at the earliest, cheapest point.
"""


def test_app_imports():
    import app

    assert app.app is not None
