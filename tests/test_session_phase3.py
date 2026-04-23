from datetime import datetime, timedelta
from session import Session


def test_is_on_break_returns_false_when_no_break():
    session = Session()
    assert session.is_on_break() is False


def test_is_on_break_returns_true_when_break_in_future():
    session = Session()
    session.break_end = datetime.now() + timedelta(minutes=5)
    assert session.is_on_break() is True


def test_is_on_break_returns_false_when_break_expired():
    session = Session()
    session.break_end = datetime.now() - timedelta(seconds=1)
    assert session.is_on_break() is False


def test_end_requested_defaults_to_false():
    session = Session()
    assert session.end_requested is False
