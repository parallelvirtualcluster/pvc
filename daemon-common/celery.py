#!/usr/bin/env python3

# celery.py - PVC client function library, Celery helper fuctions
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2023 Joshua M. Boniface <joshua@boniface.me>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
###############################################################################


import sys

from logging import getLogger
from time import sleep


class TaskFailure(Exception):
    pass


def start(celery, msg, current=0, total=1):
    logger = getLogger(__name__)
    logger.info(f"Starting {current}/{total}: {msg}")
    if celery is None:
        return
    celery.update_state(
        state="RUNNING", meta={"current": current, "total": total, "status": msg}
    )
    sleep(1)


def fail(celery, msg, exception=None, current=1, total=1):
    if exception is None:
        exception = TaskFailure

    msg = f"{type(exception()).__name__}: {msg}"

    logger = getLogger(__name__)
    logger.error(msg)

    sys.tracebacklimit = 0
    raise exception(msg)


def log_info(celery, msg):
    logger = getLogger(__name__)
    logger.info(f"Task log: {msg}")


def log_warn(celery, msg):
    logger = getLogger(__name__)
    logger.warning(f"Task log: {msg}")


def log_err(celery, msg):
    logger = getLogger(__name__)
    logger.error(f"Task log: {msg}")


def update(celery, msg, current=1, total=2):
    logger = getLogger(__name__)
    logger.info(f"Task update {current}/{total}: {msg}")
    if celery is None:
        return
    celery.update_state(
        state="RUNNING", meta={"current": current, "total": total, "status": msg}
    )
    sleep(1)


def finish(celery, msg, current=2, total=2):
    logger = getLogger(__name__)
    logger.info(f"Task update {current}/{total}: Finishing up")
    if celery is None:
        return
    celery.update_state(
        state="RUNNING",
        meta={"current": current, "total": total, "status": "Finishing up"},
    )
    sleep(1)
    logger.info(f"Success {current}/{total}: {msg}")
    return {"status": msg, "current": current, "total": total}
