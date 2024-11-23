# Copyright (c) 2023 nggit

import multiprocessing as mp
import os
import signal

from threading import Thread

PARENT = 0
CHILD = 1


def sigterm_handler(signum, frame):
    raise KeyboardInterrupt


class ProcessManager:
    processes = {}

    @classmethod
    def _wait_main(cls, conn):
        while True:
            try:
                if conn.poll(1):
                    conn.recv()
                    continue
            except EOFError:  # parent has exited
                os.kill(os.getpid(), signal.SIGTERM)
                break
            except OSError:  # handle is closed
                break

    @classmethod
    def _target(cls, conn, func, *args, **kwargs):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, sigterm_handler)
        conn[PARENT].close()

        t = Thread(target=cls._wait_main, args=(conn[CHILD],))
        t.start()

        try:
            conn[CHILD].send(os.getpid())  # started, send pid to parent

            func(*args, **kwargs)
        except KeyboardInterrupt:
            pass
        finally:
            conn[CHILD].close()  # trigger handle is closed, also notify parent
            t.join()

    def spawn(self, target, args=(), kwargs={}, name=None, exit_cb=None):
        conn = mp.Pipe()
        process = mp.Process(target=self._target, name=name,
                             args=(conn, target, *args), kwargs=kwargs)
        process.start()
        conn[CHILD].close()

        self.processes[process.name] = {
            'target': target,
            'args': args,
            'kwargs': kwargs,
            'exit_cb': exit_cb,
            'parent_conn': conn[PARENT],
            'process': process
        }
        # block until the child starts, receive its pid
        return conn[PARENT].recv()

    def wait(self):
        signal.signal(signal.SIGTERM, sigterm_handler)

        while self.processes:
            try:
                connections = [info['parent_conn'] for info in
                               self.processes.values()]
                for conn in mp.connection.wait(connections):
                    # a child has exited, clean up
                    # there is no need to call recv() since EOF is expected
                    for name in self.processes:
                        if self.processes[name]['parent_conn'] is conn:
                            info = self.processes.pop(name)

                            info['process'].join()
                            conn.close()

                            if callable(info['exit_cb']):
                                info['exit_cb'](**info)

                            break
            except KeyboardInterrupt:
                while self.processes:
                    _, info = self.processes.popitem()
                    process = info['process']

                    if process.is_alive():
                        os.kill(process.pid, signal.SIGTERM)
                        process.join(5)

                    info['parent_conn'].close()

                    if process.exitcode == 0 and callable(info['exit_cb']):
                        info['exit_cb'](**info)
