#!/usr/bin/env python3

# benchmark.py - PVC API Benchmark functions
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2024 Joshua M. Boniface <joshua@boniface.me>
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

import psycopg2
import psycopg2.extras

from datetime import datetime
from json import loads, dumps

from daemon_lib.celery import start, fail, log_info, update, finish

import daemon_lib.common as pvc_common
import daemon_lib.ceph as pvc_ceph


# Define the current test format
TEST_FORMAT = 1


# We run a total of 8 tests, to give a generalized idea of performance on the cluster:
#   1. A sequential read test of 8GB with a 4M block size
#   2. A sequential write test of 8GB with a 4M block size
#   3. A random read test of 8GB with a 4M block size
#   4. A random write test of 8GB with a 4M block size
#   5. A random read test of 8GB with a 256k block size
#   6. A random write test of 8GB with a 256k block size
#   7. A random read test of 8GB with a 4k block size
#   8. A random write test of 8GB with a 4k block size
# Taken together, these 8 results should give a very good indication of the overall storage performance
# for a variety of workloads.
test_matrix = {
    "seq_read": {
        "direction": "read",
        "iodepth": "64",
        "bs": "4M",
        "rw": "read",
    },
    "seq_write": {
        "direction": "write",
        "iodepth": "64",
        "bs": "4M",
        "rw": "write",
    },
    "rand_read_4M": {
        "direction": "read",
        "iodepth": "64",
        "bs": "4M",
        "rw": "randread",
    },
    "rand_write_4M": {
        "direction": "write",
        "iodepth": "64",
        "bs": "4M",
        "rw": "randwrite",
    },
    "rand_read_4K": {
        "direction": "read",
        "iodepth": "64",
        "bs": "4K",
        "rw": "randread",
    },
    "rand_write_4K": {
        "direction": "write",
        "iodepth": "64",
        "bs": "4K",
        "rw": "randwrite",
    },
    "rand_read_4K_lowdepth": {
        "direction": "read",
        "iodepth": "1",
        "bs": "4K",
        "rw": "randread",
    },
    "rand_write_4K_lowdepth": {
        "direction": "write",
        "iodepth": "1",
        "bs": "4K",
        "rw": "randwrite",
    },
}


# Specify the benchmark volume name and size
benchmark_volume_name = "pvcbenchmark"
benchmark_volume_size = "8G"


#
# Exceptions (used by Celery tasks)
#
class BenchmarkError(Exception):
    pass


#
# Common functions
#


def cleanup(job_name, db_conn=None, db_cur=None, zkhandler=None):
    if db_conn is not None and db_cur is not None:
        # Clean up our dangling result
        query = "DELETE FROM storage_benchmarks WHERE job = %s;"
        args = (job_name,)
        db_cur.execute(query, args)
        db_conn.commit()
        # Close the database connections cleanly
        close_database(db_conn, db_cur)
    if zkhandler is not None:
        zkhandler.disconnect()
        del zkhandler


# Database connections
def open_database(config):
    conn = psycopg2.connect(
        host=config["api_postgresql_host"],
        port=config["api_postgresql_port"],
        dbname=config["api_postgresql_dbname"],
        user=config["api_postgresql_user"],
        password=config["api_postgresql_password"],
    )
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn, cur


def close_database(conn, cur, failed=False):
    if not failed:
        conn.commit()
    cur.close()
    conn.close()


def list_benchmarks(config, job=None):
    if job is not None:
        query = "SELECT * FROM {} WHERE job = %s;".format("storage_benchmarks")
        args = (job,)
    else:
        query = "SELECT * FROM {} ORDER BY id DESC;".format("storage_benchmarks")
        args = ()

    conn, cur = open_database(config)
    cur.execute(query, args)
    orig_data = cur.fetchall()
    data = list()
    for benchmark in orig_data:
        benchmark_data = dict()
        benchmark_data["id"] = benchmark["id"]
        benchmark_data["job"] = benchmark["job"]
        benchmark_data["test_format"] = benchmark["test_format"]
        if benchmark["result"] == "Running":
            benchmark_data["benchmark_result"] = "Running"
        else:
            try:
                benchmark_data["benchmark_result"] = loads(benchmark["result"])
            except Exception:
                benchmark_data["benchmark_result"] = {}
        # Append the new data to our actual output structure
        data.append(benchmark_data)
    close_database(conn, cur)
    if data:
        return data, 200
    else:
        return {"message": "No benchmark found."}, 404


def prepare_benchmark_volume(
    pool, job_name=None, db_conn=None, db_cur=None, zkhandler=None
):
    # Create the RBD volume
    retcode, retmsg = pvc_ceph.add_volume(
        zkhandler, pool, benchmark_volume_name, benchmark_volume_size
    )
    if not retcode:
        cleanup(
            job_name,
            db_conn=db_conn,
            db_cur=db_cur,
            zkhandler=zkhandler,
        )
        fail(
            None,
            f'Failed to create volume "{benchmark_volume_name}" on pool "{pool}": {retmsg}',
        )
    else:
        log_info(None, retmsg)


def cleanup_benchmark_volume(
    pool, job_name=None, db_conn=None, db_cur=None, zkhandler=None
):
    # Remove the RBD volume
    retcode, retmsg = pvc_ceph.remove_volume(zkhandler, pool, benchmark_volume_name)
    if not retcode:
        cleanup(
            job_name,
            db_conn=db_conn,
            db_cur=db_cur,
            zkhandler=zkhandler,
        )
        fail(
            None,
            f'Failed to remove volume "{benchmark_volume_name}" from pool "{pool}": {retmsg}',
        )
    else:
        log_info(None, retmsg)


def run_benchmark_job(
    test, pool, job_name=None, db_conn=None, db_cur=None, zkhandler=None
):
    test_spec = test_matrix[test]
    log_info(None, f"Running test '{test}'")
    fio_cmd = """
            fio \
                --name={test} \
                --ioengine=rbd \
                --pool={pool} \
                --rbdname={volume} \
                --output-format=json \
                --direct=1 \
                --randrepeat=1 \
                --numjobs=1 \
                --time_based \
                --runtime=75 \
                --group_reporting \
                --iodepth={iodepth} \
                --bs={bs} \
                --readwrite={rw}
        """.format(
        test=test,
        pool=pool,
        volume=benchmark_volume_name,
        iodepth=test_spec["iodepth"],
        bs=test_spec["bs"],
        rw=test_spec["rw"],
    )

    log_info(None, "Running fio job: {}".format(" ".join(fio_cmd.split())))
    retcode, stdout, stderr = pvc_common.run_os_command(fio_cmd)
    try:
        jstdout = loads(stdout)
        if retcode:
            raise
    except Exception:
        cleanup(
            job_name,
            db_conn=db_conn,
            db_cur=db_cur,
            zkhandler=zkhandler,
        )
        fail(
            None,
            f"Failed to run fio test '{test}': {stderr}",
        )

    return jstdout


def worker_run_benchmark(zkhandler, celery, config, pool):
    # Phase 0 - connect to databases
    cur_time = datetime.now().isoformat(timespec="seconds")
    cur_primary = zkhandler.read("base.config.primary_node")
    job_name = f"{cur_time}_{cur_primary}"

    current_stage = 0
    total_stages = 13
    start(
        celery,
        f"Running storage benchmark '{job_name}' on pool '{pool}'",
        current=current_stage,
        total=total_stages,
    )

    try:
        db_conn, db_cur = open_database(config)
    except Exception:
        cleanup(
            job_name,
            db_conn=None,
            db_cur=None,
            zkhandler=zkhandler,
        )
        fail(
            celery,
            "Failed to connect to Postgres",
        )

    current_stage += 1
    update(
        celery,
        "Storing running status in database",
        current=current_stage,
        total=total_stages,
    )

    try:
        query = "INSERT INTO storage_benchmarks (job, test_format, result) VALUES (%s, %s, %s);"
        args = (
            job_name,
            TEST_FORMAT,
            "Running",
        )
        db_cur.execute(query, args)
        db_conn.commit()
    except Exception as e:
        cleanup(
            job_name,
            db_conn=db_conn,
            db_cur=db_cur,
            zkhandler=zkhandler,
        )
        fail(celery, f"Failed to store running status: {e}", exception=BenchmarkError)

    current_stage += 1
    update(
        celery,
        "Creating benchmark volume",
        current=current_stage,
        total=total_stages,
    )

    prepare_benchmark_volume(
        pool,
        job_name=job_name,
        db_conn=db_conn,
        db_cur=db_cur,
        zkhandler=zkhandler,
    )

    # Phase 2 - benchmark run
    results = dict()
    for test in test_matrix:
        current_stage += 1
        update(
            celery,
            f"Running benchmark job '{test}'",
            current=current_stage,
            total=total_stages,
        )

        results[test] = run_benchmark_job(
            test,
            pool,
            job_name=job_name,
            db_conn=db_conn,
            db_cur=db_cur,
            zkhandler=zkhandler,
        )

    # Phase 3 - cleanup
    current_stage += 1
    update(
        celery,
        "Cleaning up venchmark volume",
        current=current_stage,
        total=total_stages,
    )

    cleanup_benchmark_volume(
        pool,
        job_name=job_name,
        db_conn=db_conn,
        db_cur=db_cur,
        zkhandler=zkhandler,
    )

    current_stage += 1
    update(
        celery,
        "Storing results in database",
        current=current_stage,
        total=total_stages,
    )

    try:
        query = "UPDATE storage_benchmarks SET result = %s WHERE job = %s;"
        args = (dumps(results), job_name)
        db_cur.execute(query, args)
        db_conn.commit()
    except Exception as e:
        cleanup(
            job_name,
            db_conn=db_conn,
            db_cur=db_cur,
            zkhandler=zkhandler,
        )
        fail(celery, f"Failed to store test results: {e}", exception=BenchmarkError)

    cleanup(
        job_name,
        db_conn=db_conn,
        db_cur=db_cur,
        zkhandler=zkhandler,
    )

    current_stage += 1
    return finish(
        celery,
        f"Storage benchmark {job_name} completed successfully",
        current=current_stage,
        total=total_stages,
    )
