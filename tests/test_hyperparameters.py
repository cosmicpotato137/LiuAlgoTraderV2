import logging

import pandas as pd
import pytest

from liualgotrader.common.hyperparameter import Hyperparameters, Parameter

logger = logging.getLogger(__name__)


def test_hyper_param_1():
    p1 = Parameter("p1", int, 5, 6)

    _ = next(p1)
    _ = next(p1)

    return True


def test_hyper_param_single():
    p1 = Parameter("p1", int, 5, 5)

    logger.info("single %s", next(p1))

    return True


def test_hyper_param_1_ex():
    p1 = Parameter("p1", int, 5, 5)

    next(p1)

    try:
        a3 = next(p1)
    except StopIteration:
        return True

    raise AssertionError(f"Expected Exception StopIteration, but got {a3}")


def test_hyper_params_int():
    logger.info("test_hyper_params_int")
    p1 = Parameter("p1", int, 5, 7)
    h = Hyperparameters([p1])

    for i in iter(h):
        logger.info("%s", i)

    return True


def test_hyper_params_two_int():
    logger.info("test_hyper_params_two_int")
    p1 = Parameter("p1", int, 5, 7)
    p2 = Parameter("p2", int, 8, 17)

    h = Hyperparameters([p1, p2])

    for i in iter(h):
        logger.info("%s", i)

    return True


def test_hyper_params_int_float():
    logger.info("test_hyper_params_int_float")
    i = Parameter("int", int, 5, 7)
    f = Parameter("float", float, 0.01, 0.05, delta=0.01)

    h = Hyperparameters([i, f])

    for i in iter(h):
        logger.info("%s", i)

    return True


def test_hyper_params_float_missing():
    logger.info("test_hyper_params_int_float")
    f = Parameter("float", float, 0.01, 0.05)

    h = Hyperparameters([f])

    try:
        for i in iter(h):
            logger.info("%s", i)
    except AttributeError:
        return True

    raise AssertionError(
        "Expected AttributeError in test_hyper_params_float_missing"
    )
