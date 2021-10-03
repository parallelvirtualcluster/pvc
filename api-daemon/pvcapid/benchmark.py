#!/usr/bin/env python3

# benchmark.py - PVC API Benchmark functions
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2021 Joshua M. Boniface <joshua@boniface.me>
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

from json import loads, dumps

from pvcapid.Daemon import config

from daemon_lib.zkhandler import ZKHandler

import daemon_lib.common as pvc_common
import daemon_lib.ceph as pvc_ceph


#
# Exceptions (used by Celery tasks)
#
class BenchmarkError(Exception):
    """
    An exception that results from the Benchmark job.
    """
    def __init__(self, message, job_name=None, db_conn=None, db_cur=None, zkhandler=None):
        self.message = message
        if job_name is not None:
            # Clean up our dangling result
            query = "DELETE FROM storage_benchmarks WHERE job = %s;"
            args = (job_name,)
            db_cur.execute(query, args)
            db_conn.commit()
            # Close the database connections cleanly
            close_database(db_conn, db_cur)
            zkhandler.disconnect()

    def __str__(self):
        return str(self.message)

#
# Common functions
#


# Database connections
def open_database(config):
    conn = psycopg2.connect(
        host=config['database_host'],
        port=config['database_port'],
        dbname=config['database_name'],
        user=config['database_user'],
        password=config['database_password']
    )
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn, cur


def close_database(conn, cur, failed=False):
    if not failed:
        conn.commit()
    cur.close()
    conn.close()


def list_benchmarks(job=None):
    if job is not None:
        query = "SELECT * FROM {} WHERE job = %s;".format('storage_benchmarks')
        args = (job, )
    else:
        query = "SELECT * FROM {} ORDER BY id DESC;".format('storage_benchmarks')
        args = ()

    conn, cur = open_database(config)
    cur.execute(query, args)
    orig_data = cur.fetchall()
    data = list()
    for benchmark in orig_data:
        benchmark_data = dict()
        benchmark_data['id'] = benchmark['id']
        benchmark_data['job'] = benchmark['job']
        benchmark_data['test_format'] = benchmark['test_format']
        if benchmark['result'] == 'Running':
            benchmark_data['benchmark_result'] = 'Running'
        else:
            try:
                benchmark_data['benchmark_result'] = loads(benchmark['result'])
            except Exception:
                benchmark_data['benchmark_result'] = {}
        # Append the new data to our actual output structure
        data.append(benchmark_data)
    close_database(conn, cur)
    if data:
        return data, 200
    else:
        return {'message': 'No benchmark found.'}, 404


def run_benchmark(self, pool):
    # Runtime imports
    import time
    from datetime import datetime

    # Define the current test format
    TEST_FORMAT = 1

    time.sleep(2)

    # Phase 0 - connect to databases
    try:
        db_conn, db_cur = open_database(config)
    except Exception:
        print('FATAL - failed to connect to Postgres')
        raise Exception

    try:
        zkhandler = ZKHandler(config)
        zkhandler.connect()
    except Exception:
        print('FATAL - failed to connect to Zookeeper')
        raise Exception

    cur_time = datetime.now().isoformat(timespec='seconds')
    cur_primary = zkhandler.read('base.config.primary_node')
    job_name = '{}_{}'.format(cur_time, cur_primary)

    print("Starting storage benchmark '{}' on pool '{}'".format(job_name, pool))

    print("Storing running status for job '{}' in database".format(job_name))
    try:
        query = "INSERT INTO storage_benchmarks (job, test_format, result) VALUES (%s, %s, %s);"
        args = (job_name, TEST_FORMAT, "Running",)
        db_cur.execute(query, args)
        db_conn.commit()
    except Exception as e:
        raise BenchmarkError("Failed to store running status: {}".format(e), job_name=job_name, db_conn=db_conn, db_cur=db_cur, zkhandler=zkhandler)

    # Phase 1 - volume preparation
    self.update_state(state='RUNNING', meta={'current': 1, 'total': 3, 'status': 'Creating benchmark volume'})
    time.sleep(1)

    volume = 'pvcbenchmark'

    # Create the RBD volume
    retcode, retmsg = pvc_ceph.add_volume(zkhandler, pool, volume, "8G")
    if not retcode:
        raise BenchmarkError('Failed to create volume "{}": {}'.format(volume, retmsg), job_name=job_name, db_conn=db_conn, db_cur=db_cur, zkhandler=zkhandler)
    else:
        print(retmsg)

    # Phase 2 - benchmark run
    self.update_state(state='RUNNING', meta={'current': 2, 'total': 3, 'status': 'Running fio benchmarks on volume'})
    time.sleep(1)

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
        'seq_read': {
            'direction': 'read',
            'iodepth': '64',
            'bs': '4M',
            'rw': 'read'
        },
        'seq_write': {
            'direction': 'write',
            'iodepth': '64',
            'bs': '4M',
            'rw': 'write'
        },
        'rand_read_4M': {
            'direction': 'read',
            'iodepth': '64',
            'bs': '4M',
            'rw': 'randread'
        },
        'rand_write_4M': {
            'direction': 'write',
            'iodepth': '64',
            'bs': '4M',
            'rw': 'randwrite'
        },
        'rand_read_4K': {
            'direction': 'read',
            'iodepth': '64',
            'bs': '4K',
            'rw': 'randread'
        },
        'rand_write_4K': {
            'direction': 'write',
            'iodepth': '64',
            'bs': '4K',
            'rw': 'randwrite'
        },
        'rand_read_4K_lowdepth': {
            'direction': 'read',
            'iodepth': '1',
            'bs': '4K',
            'rw': 'randread'
        },
        'rand_write_4K_lowdepth': {
            'direction': 'write',
            'iodepth': '1',
            'bs': '4K',
            'rw': 'randwrite'
        },
    }

    results = dict()
    for test in test_matrix:
        print("Running test '{}'".format(test))
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
            volume=volume,
            iodepth=test_matrix[test]['iodepth'],
            bs=test_matrix[test]['bs'],
            rw=test_matrix[test]['rw'])

        print("Running fio job: {}".format(' '.join(fio_cmd.split())))
        retcode, stdout, stderr = pvc_common.run_os_command(fio_cmd)
        if retcode:
            raise BenchmarkError("Failed to run fio test: {}".format(stderr), job_name=job_name, db_conn=db_conn, db_cur=db_cur, zkhandler=zkhandler)

        results[test] = loads(stdout)

    # Phase 3 - cleanup
    self.update_state(state='RUNNING', meta={'current': 3, 'total': 3, 'status': 'Cleaning up and storing results'})
    time.sleep(1)

    # Remove the RBD volume
    retcode, retmsg = pvc_ceph.remove_volume(zkhandler, pool, volume)
    if not retcode:
        raise BenchmarkError('Failed to remove volume "{}": {}'.format(volume, retmsg), job_name=job_name, db_conn=db_conn, db_cur=db_cur, zkhandler=zkhandler)
    else:
        print(retmsg)

    print("Storing result of tests for job '{}' in database".format(job_name))
    try:
        query = "UPDATE storage_benchmarks SET result = %s WHERE job = %s;"
        args = (dumps(results), job_name)
        db_cur.execute(query, args)
        db_conn.commit()
    except Exception as e:
        raise BenchmarkError("Failed to store test results: {}".format(e), job_name=job_name, db_conn=db_conn, db_cur=db_cur, zkhandler=zkhandler)

    close_database(db_conn, db_cur)
    zkhandler.disconnect()
    del zkhandler

    return {'status': "Storage benchmark '{}' completed successfully.", 'current': 3, 'total': 3}
