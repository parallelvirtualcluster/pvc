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

from distutils.util import strtobool as dustrtobool

import daemon_lib.common as pvc_common
import daemon_lib.ceph as pvc_ceph

config = None  # Set in this namespace by flaskapi


def strtobool(stringv):
    if stringv is None:
        return False
    if isinstance(stringv, bool):
        return bool(stringv)
    try:
        return bool(dustrtobool(stringv))
    except Exception:
        return False


#
# Exceptions (used by Celery tasks)
#
class BenchmarkError(Exception):
    """
    An exception that results from the Benchmark job.
    """
    def __init__(self, message, cur_time=None, db_conn=None, db_cur=None, zk_conn=None):
        self.message = message
        if cur_time is not None:
            # Clean up our dangling result
            query = "DELETE FROM storage_benchmarks WHERE job = %s;"
            args = (cur_time,)
            db_cur.execute(query, args)
            db_conn.commit()
            # Close the database connections cleanly
            close_database(db_conn, db_cur)
            pvc_common.stopZKConnection(zk_conn)

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
        benchmark_data['benchmark_result'] = benchmark['result']
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
    import json
    from datetime import datetime

    time.sleep(2)

    cur_time = datetime.now().isoformat(timespec='seconds')

    print("Starting storage benchmark '{}' on pool '{}'".format(cur_time, pool))

    # Phase 0 - connect to databases
    try:
        db_conn, db_cur = open_database(config)
    except Exception:
        print('FATAL - failed to connect to Postgres')
        raise Exception

    try:
        zk_conn = pvc_common.startZKConnection(config['coordinators'])
    except Exception:
        print('FATAL - failed to connect to Zookeeper')
        raise Exception

    print("Storing running status for job '{}' in database".format(cur_time))
    try:
        query = "INSERT INTO storage_benchmarks (job, result) VALUES (%s, %s);"
        args = (cur_time, "Running",)
        db_cur.execute(query, args)
        db_conn.commit()
    except Exception as e:
        raise BenchmarkError("Failed to store running status: {}".format(e), cur_time=cur_time, db_conn=db_conn, db_cur=db_cur, zk_conn=zk_conn)

    # Phase 1 - volume preparation
    self.update_state(state='RUNNING', meta={'current': 1, 'total': 3, 'status': 'Creating benchmark volume'})
    time.sleep(1)

    volume = 'pvcbenchmark'

    # Create the RBD volume
    retcode, retmsg = pvc_ceph.add_volume(zk_conn, pool, volume, "8G")
    if not retcode:
        raise BenchmarkError('Failed to create volume "{}": {}'.format(volume, retmsg), cur_time=cur_time, db_conn=db_conn, db_cur=db_cur, zk_conn=zk_conn)
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
            'bs': '4M',
            'rw': 'read'
        },
        'seq_write': {
            'direction': 'write',
            'bs': '4M',
            'rw': 'write'
        },
        'rand_read_4M': {
            'direction': 'read',
            'bs': '4M',
            'rw': 'randread'
        },
        'rand_write_4M': {
            'direction': 'write',
            'bs': '4M',
            'rw': 'randwrite'
        },
        'rand_read_256K': {
            'direction': 'read',
            'bs': '256K',
            'rw': 'randread'
        },
        'rand_write_256K': {
            'direction': 'write',
            'bs': '256K',
            'rw': 'randwrite'
        },
        'rand_read_4K': {
            'direction': 'read',
            'bs': '4K',
            'rw': 'randread'
        },
        'rand_write_4K': {
            'direction': 'write',
            'bs': '4K',
            'rw': 'randwrite'
        }
    }
    parsed_results = dict()
    for test in test_matrix:
        print("Running test '{}'".format(test))
        fio_cmd = """
            fio \
                --output-format=terse \
                --terse-version=5 \
                --ioengine=rbd \
                --pool={pool} \
                --rbdname={volume} \
                --direct=1 \
                --randrepeat=1 \
                --iodepth=64 \
                --size=8G \
                --name={test} \
                --bs={bs} \
                --readwrite={rw}
        """.format(
            pool=pool,
            volume=volume,
            test=test,
            bs=test_matrix[test]['bs'],
            rw=test_matrix[test]['rw'])

        retcode, stdout, stderr = pvc_common.run_os_command(fio_cmd)
        if retcode:
            raise BenchmarkError("Failed to run fio test: {}".format(stderr), cur_time=cur_time, db_conn=db_conn, db_cur=db_cur, zk_conn=zk_conn)

        # Parse the terse results to avoid storing tons of junk
        # Reference: https://fio.readthedocs.io/en/latest/fio_doc.html#terse-output
        # This is written out broken up because the man page didn't bother to do this, and I'm putting it here for posterity.
        # Example Read test (line breaks to match man ref):
        #    I 5;fio-3.12;test;0;0; (5) [0, 1, 2, 3, 4]
        #    R 8388608;2966268;724;2828; (4) [5, 6, 7, 8]
        #      0;0;0.000000;0.000000; (4) [9, 10, 11, 12]
        #      0;0;0.000000;0.000000; (4) [13, 14, 15, 16]
        #      0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0; (20) [17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32,33, 34, 35, 36]
        #      0;0;0.000000;0.000000; (4) [37, 38, 39, 40]
        #      2842624;3153920;100.000000%;2967142.400000;127226.797479;5; (6) [41, 42, 43, 44, 45, 46]
        #      694;770;724.400000;31.061230;5; (5) [47, 48, 49, 50, 51]
        #    W 0;0;0;0; (4) [52, 53, 54, 55]
        #      0;0;0.000000;0.000000; (4) [56, 57, 58, 59]
        #      0;0;0.000000;0.000000; (4) [60, 61, 62, 63]
        #      0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0; (20) [64, 65, 66, 67, 68. 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83]
        #      0;0;0.000000;0.000000; (4) [84, 85, 86, 87]
        #      0;0;0.000000%;0.000000;0.000000;0; (6) [88, 89, 90, 91, 92, 93]
        #      0;0;0.000000;0.000000;0; (5) [94, 95, 96, 97, 98]
        #    T 0;0;0;0; (4) [99, 100, 101, 102]
        #      0;0;0.000000;0.000000; (4) [103, 104, 105, 106]
        #      0;0;0.000000;0.000000; (4) [107, 108, 109, 110]
        #      0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0; (20) [111, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125, 126, 127, 128, 129, 130]
        #      0;0;0.000000;0.000000; (4) [131, 132, 133, 134]
        #      0;0;0.000000%;0.000000;0.000000;0; (6) [135, 136, 137, 138, 139, 140]
        #      0;0;0.000000;0.000000;0; (5) [141, 142, 143, 144, 145]
        #    C 0.495225%;0.000000%;2083;0;13; (5) [146, 147, 148, 149, 150]
        #    D 0.1%;0.1%;0.2%;0.4%;0.8%;1.6%;96.9%; (7) [151, 152, 153, 154, 155, 156, 157]
        #    U 0.00%;0.00%;0.00%;0.00%;0.00%;0.00%;0.00%;0.00%;0.00%;0.00%; (10) [158, 159, 160, 161, 162, 163, 164, 165, 166, 167]
        #    M 0.00%;0.00%;0.00%;0.00%;0.00%;0.00%;0.00%;0.00%;0.00%;0.00%;0.00%;0.00%; (12) [168, 169, 170, 171, 172, 173, 174, 175, 176, 177, 178. 179]
        #    B dm-0;0;110;0;0;0;4;4;0.15%; (9) [180, 181, 182, 183, 184, 185, 186, 187, 188]
        #      slaves;0;118;0;28;0;23;0;0.00%; (9) [189, 190, 191, 192, 193, 194, 195, 196, 197]
        #      sde;0;118;0;28;0;23;0;0.00% (9) [198, 199, 200, 201, 202, 203, 204, 205, 206]
        # Example Write test:
        #    I 5;fio-3.12;test;0;0; (5)
        #    R 0;0;0;0; (4)
        #      0;0;0.000000;0.000000; (4)
        #      0;0;0.000000;0.000000; (4)
        #      0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0; (20)
        #      0;0;0.000000;0.000000; (4)
        #      0;0;0.000000%;0.000000;0.000000;0; (6)
        #      0;0;0.000000;0.000000;0; (5)
        #    W 8388608;1137438;277;7375; (4)
        #      0;0;0.000000;0.000000; (4)
        #      0;0;0.000000;0.000000; (4)
        #      0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0; (20)
        #      0;0;0.000000;0.000000; (4)
        #      704512;1400832;99.029573%;1126400.000000;175720.860374;14; (6)
        #      172;342;275.000000;42.900601;14; (5)
        #    T 0;0;0;0; (4)
        #      0;0;0.000000;0.000000; (4)
        #      0;0;0.000000;0.000000; (4)
        #      0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0;0%=0; (20)
        #      0;0;0.000000;0.000000; (4)
        #      0;0;0.000000%;0.000000;0.000000;0; (6)
        #      0;0;0.000000;0.000000;0; (5)
        #    C 12.950909%;1.912124%;746;0;95883; (5)
        #    D 0.1%;0.1%;0.2%;0.4%;0.8%;1.6%;96.9%; (7)
        #    U 0.00%;0.00%;0.00%;0.00%;0.00%;0.00%;0.00%;0.00%;0.00%;0.00%; (10)
        #    M 0.00%;0.00%;0.00%;0.00%;0.00%;0.00%;0.00%;0.00%;0.00%;0.00%;0.00%;0.00%; (12)
        #    B dm-0;0;196;0;0;0;12;12;0.16%; (9)
        #      slaves;0;207;0;95;0;39;16;0.21%; (9)
        #      sde;0;207;0;95;0;39;16;0.21% (9)
        results = stdout.split(';')
        if test_matrix[test]['direction'] == 'read':
            # Stats
            #         5:   Total IO (KiB)
            #         6:   bandwidth (KiB/sec)
            #         7:   IOPS
            #         8:   runtime (msec)
            # Total latency
            #         37:  min
            #         38:  max
            #         39:  mean
            #         40:  stdev
            # Bandwidth
            #         41:  min
            #         42:  max
            #         44:  mean
            #         45:  stdev
            #         46:  # samples
            # IOPS
            #         47:  min
            #         48:  max
            #         49:  mean
            #         50:  stdev
            #         51:  # samples
            # CPU
            #         146: user
            #         147: system
            #         148: ctx switches
            #         149: maj faults
            #         150: min faults
            parsed_results[test] = {
                "overall": {
                    "iosize": results[5],
                    "bandwidth": results[6],
                    "iops": results[7],
                    "runtime": results[8]
                },
                "latency": {
                    "min": results[37],
                    "max": results[38],
                    "mean": results[39],
                    "stdev": results[40]
                },
                "bandwidth": {
                    "min": results[41],
                    "max": results[42],
                    "mean": results[44],
                    "stdev": results[45],
                    "numsamples": results[46],
                },
                "iops": {
                    "min": results[47],
                    "max": results[48],
                    "mean": results[49],
                    "stdev": results[50],
                    "numsamples": results[51]
                },
                "cpu": {
                    "user": results[146],
                    "system": results[147],
                    "ctxsw": results[148],
                    "majfault": results[149],
                    "minfault": results[150]
                }
            }

        if test_matrix[test]['direction'] == 'write':
            # Stats
            #         52:  Total IO (KiB)
            #         53:  bandwidth (KiB/sec)
            #         54:  IOPS
            #         55:  runtime (msec)
            # Total latency
            #         84:  min
            #         85:  max
            #         86:  mean
            #         87:  stdev
            # Bandwidth
            #         88:  min
            #         89:  max
            #         91:  mean
            #         92:  stdev
            #         93:  # samples
            # IOPS
            #         94:  min
            #         95:  max
            #         96:  mean
            #         97:  stdev
            #         98:  # samples
            # CPU
            #         146: user
            #         147: system
            #         148: ctx switches
            #         149: maj faults
            #         150: min faults
            parsed_results[test] = {
                "overall": {
                    "iosize": results[52],
                    "bandwidth": results[53],
                    "iops": results[54],
                    "runtime": results[55]
                },
                "latency": {
                    "min": results[84],
                    "max": results[85],
                    "mean": results[86],
                    "stdev": results[87]
                },
                "bandwidth": {
                    "min": results[88],
                    "max": results[89],
                    "mean": results[91],
                    "stdev": results[92],
                    "numsamples": results[93],
                },
                "iops": {
                    "min": results[94],
                    "max": results[95],
                    "mean": results[96],
                    "stdev": results[97],
                    "numsamples": results[98]
                },
                "cpu": {
                    "user": results[146],
                    "system": results[147],
                    "ctxsw": results[148],
                    "majfault": results[149],
                    "minfault": results[150]
                }
            }

    # Phase 3 - cleanup
    self.update_state(state='RUNNING', meta={'current': 3, 'total': 3, 'status': 'Cleaning up and storing results'})
    time.sleep(1)

    # Remove the RBD volume
    retcode, retmsg = pvc_ceph.remove_volume(zk_conn, pool, volume)
    if not retcode:
        raise BenchmarkError('Failed to remove volume "{}": {}'.format(volume, retmsg), cur_time=cur_time, db_conn=db_conn, db_cur=db_cur, zk_conn=zk_conn)
    else:
        print(retmsg)

    print("Storing result of tests for job '{}' in database".format(cur_time))
    try:
        query = "UPDATE storage_benchmarks SET result = %s WHERE job = %s;"
        args = (json.dumps(parsed_results), cur_time)
        db_cur.execute(query, args)
        db_conn.commit()
    except Exception as e:
        raise BenchmarkError("Failed to store test results: {}".format(e), cur_time=cur_time, db_conn=db_conn, db_cur=db_cur, zk_conn=zk_conn)

    close_database(db_conn, db_cur)
    pvc_common.stopZKConnection(zk_conn)
    return {'status': "Storage benchmark '{}' completed successfully.", 'current': 3, 'total': 3}
