"""Minimal Result type: errors as values with a user-facing message."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Ok[T]:
    value: T

    def map[U](self, fn: Callable[[T], U]) -> Ok[U]:
        return Ok(fn(self.value))

    def and_then[U](self, fn: Callable[[T], Result[U]]) -> Result[U]:
        return fn(self.value)


@dataclass(frozen=True)
class Err:
    error: str

    def map(self, _fn: Callable[..., object]) -> Err:
        return self

    def and_then(self, _fn: Callable[..., object]) -> Err:
        return self


type Result[T] = Ok[T] | Err
