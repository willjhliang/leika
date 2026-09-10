"""Fixed-size ownership snapshots for caller-provided image arrays.

Capture the allocation size before reserving capacity, then copy into exactly
that storage while the caller holds its image-preparation reservation.
"""

from __future__ import annotations

import math
from typing import Any, NamedTuple

import numpy as np


class _NdarraySnapshotSpec(NamedTuple):
    shape: tuple[int, ...]
    dtype: np.dtype[Any]
    nbytes: int


def _ndarray_snapshot_spec(value: np.ndarray) -> _NdarraySnapshotSpec:
    """Capture the only shape and storage size an admitted copy may allocate."""
    if type(value) is not np.ndarray:
        raise TypeError("image must be a base numpy.ndarray")
    shape = tuple(int(size) for size in value.shape)
    dtype = value.dtype
    nbytes = math.prod(shape) * int(dtype.itemsize)
    return _NdarraySnapshotSpec(shape, dtype, nbytes)


def _private_ndarray_snapshot(
    value: np.ndarray,
    spec: _NdarraySnapshotSpec,
) -> np.ndarray:
    """Copy into fixed charged storage without trusting a later shape read.

    Callers must not mutate or resize their source while an API call is in
    progress. A buffer export blocks ordinary accidental resize; NumPy's
    explicit ``resize(refcheck=False)`` escape hatch remains outside this
    public contract, while the fixed destination still bounds Leika's own
    allocation.
    """
    shape, dtype, nbytes = spec
    if math.prod(shape) * int(dtype.itemsize) != nbytes:
        raise RuntimeError("invalid ndarray snapshot specification")
    exported = memoryview(value)
    try:
        snapshot = np.empty(shape, dtype=dtype, order="C")
        np.copyto(snapshot, value, casting="no")
    finally:
        exported.release()
    if value.shape != shape or value.dtype != dtype:
        raise ValueError("image changed shape or dtype while it was snapshotted")
    return snapshot
