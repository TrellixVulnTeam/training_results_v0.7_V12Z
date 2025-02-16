"""
Utilities for MLPerf logging
"""
import collections
import os
import subprocess

from mlperf_logging import mllog
from mlperf_logging.mllog import constants

import torch

_MLLOGGER = mllog.get_mllogger()

def log_start(*args, **kwargs):
    "log with start tag"
    _log_print(_MLLOGGER.start, *args, **kwargs)
def log_end(*args, **kwargs):
    "log with end tag"
    _log_print(_MLLOGGER.end, *args, **kwargs)
def log_event(*args, **kwargs):
    "log with event tag"
    _log_print(_MLLOGGER.event, *args, **kwargs)
def _log_print(logger, *args, **kwargs):
    "makes mlperf logger aware of distributed execution"
    if 'stack_offset' not in kwargs:
        kwargs['stack_offset'] = 3
    if 'value' not in kwargs:
        kwargs['value'] = None

    if kwargs.pop('log_all_ranks', False):
        log = True
    else:
        log = (get_rank() == 0)

    if log:
        logger(*args, **kwargs)



def config_logger(benchmark):
    "initiates mlperf logger"
    mllog.config(filename=os.path.join(os.path.dirname(os.path.abspath(__file__)), f'{benchmark}.log'))
    _MLLOGGER.logger.propagate = False


def barrier():
    """
    Works as a temporary distributed barrier, currently pytorch
    doesn't implement barrier for NCCL backend.
    Calls all_reduce on dummy tensor and synchronizes with GPU.
    """
    if torch.distributed.is_available() and torch.distributed.is_initialized():
        torch.distributed.all_reduce(torch.cuda.FloatTensor(1))
        torch.cuda.synchronize()


def get_rank():
    """
    Gets distributed rank or returns zero if distributed is not initialized.
    """
    if torch.distributed.is_available() and torch.distributed.is_initialized():
        rank = torch.distributed.get_rank()
    else:
        rank = 0
    return rank


def mlperf_submission_log(benchmark):
    """
    Logs information needed for MLPerf submission
    """

    num_nodes = os.environ.get('SLURM_NNODES', 1)

    config_logger(benchmark)

    log_event(
        key=constants.SUBMISSION_BENCHMARK,
        value=benchmark,
        )

    log_event(
        key=constants.SUBMISSION_ORG,
        value='Inspur')

    log_event(
        key=constants.SUBMISSION_DIVISION,
        value='closed')

    log_event(
        key=constants.SUBMISSION_STATUS,
        value='onprem')

    log_event(
        key=constants.SUBMISSION_PLATFORM,
        value=f'{num_nodes}xNF5488')
