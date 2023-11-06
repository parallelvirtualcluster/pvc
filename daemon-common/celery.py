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


def start(celery, msg, current=1, total=2):
    logger = getLogger(__name__)
    logger.info(f"Starting: {msg}")
    celery.update_state(
        state="RUNNING", meta={"current": current, "total": total, "status": msg}
    )
    sleep(0.5)


def fail(celery, msg, current=1, total=2):
    logger = getLogger(__name__)
    logger.error(msg)
    sys.tracebacklimit = 0
    raise TaskFailure(msg)


def update(celery, msg, current=1, total=2):
    logger = getLogger(__name__)
    logger.info(f"Task update: {msg}")
    celery.update_state(
        state="RUNNING", meta={"current": current, "total": total, "status": msg}
    )
    sleep(0.5)


def finish(celery, msg, current=2, total=2):
    logger = getLogger(__name__)
    celery.update_state(
        state="RUNNING",
        meta={"current": current, "total": total, "status": "Finishing up"},
    )
    sleep(0.25)
    logger.info(f"Success: {msg}")
    return {"status": msg, "current": current, "total": total}
