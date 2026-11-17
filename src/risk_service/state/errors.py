"""Errors raised by the state layer.

``StateError`` means the state cannot be trusted or reached: callers must fail
closed. ``OrderLifecycleError`` means the caller asked for something invalid
(a duplicate order, a fill for an unknown order) and should be told so.
"""


class StateError(Exception):
    pass


class CorruptStateError(StateError):
    pass


class StateContentionError(StateError):
    """A transaction kept losing to concurrent writers and gave up."""


class OrderLifecycleError(Exception):
    pass


class DuplicateOrderError(OrderLifecycleError):
    pass


class UnknownOrderError(OrderLifecycleError):
    pass


class OverfillError(OrderLifecycleError):
    pass
