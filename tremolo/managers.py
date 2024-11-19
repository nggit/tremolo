# Copyright (c) 2023 nggit

import multiprocessing as mp
import os
import signal

from threading import Thread


def sigterm_handler(signum, frame):
    raise KeyboardInterrupt


class ProcessManager:
    processes = {}

    def __init__(self):
        mp.set_start_method('spawn', force=True)

    @classmethod
    def _wait_main(cls, conn):
        try:
            conn.recv()
        except EOFError:
            os.kill(os.getpid(), signal.SIGTERM)

    @classmethod
    def _target(cls, conn, func, *args, **kwargs):
        t = Thread(target=cls._wait_main, args=(conn,), daemon=True)
        t.start()

        try:
            conn.send(os.getpid())  # started, send pid to parent

            return func(*args, **kwargs)
        finally:
            conn.send(mp.current_process().name)  # exited, send name to parent
            conn.close()

    def spawn(self, target, args=(), kwargs={}, name=None, exit_cb=None):
        parent_conn, child_conn = mp.Pipe()
        process = mp.Process(target=self._target, name=name,
                             args=(child_conn, target, *args), kwargs=kwargs)
        process.start()

        self.processes[process.name] = {
            'target': target,
            'args': args,
            'kwargs': kwargs,
            'exit_cb': exit_cb,
            'parent_conn': parent_conn,
            'process': process
        }
        # block until the child starts, receive its pid
        return parent_conn.recv()

    def wait(self):
        signal.signal(signal.SIGTERM, sigterm_handler)

        while self.processes:
            try:
                connections = [info['parent_conn'] for info in
                               self.processes.values()]
                for conn in mp.connection.wait(connections, 1):
                    # a child has exited, receive its name, clean up
                    try:
                        name = conn.recv()
                    except EOFError:
                        for name in self.processes:
                            if self.processes[name]['parent_conn'] is conn:
                                break

                    info = self.processes.pop(name)
                    exit_cb = info['exit_cb']

                    info['process'].join()

                    if callable(exit_cb):
                        exit_cb(**info)
            except KeyboardInterrupt:
                while self.processes:
                    _, info = self.processes.popitem()
                    exit_cb = info['exit_cb']

                    info['parent_conn'].close()
                    info['process'].join()

                    if callable(exit_cb):
                        exit_cb(**info)
